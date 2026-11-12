"""A human clinician answers the vignettes in the terminal: the gold tier (docs/fixtures.md).

Usage: python scripts/elicitation/answer_vignettes.py --expert E01 --role "consultant psychiatrist,
           12 years adult ADHD" [--from silver] [--vignettes V001 V006] [--order shuffle|fixed]

Shows each vignette (never its hidden design), asks its questions Q1-Q6 and writes an
ElicitationDocument to data/fixtures/<source>/gold/documents/DOC-<n>.json, next to the vignettes it
copied from the `--from` tier. Answers are multi-line: Esc then Enter submits. Commands, typed as
the whole answer: `:skip` skips the vignette, `:quit` pauses. The draft is saved after every answer
(data/fixtures/<source>/gold/drafts/<expert>.json); running the same command again resumes it.

Reference claims are not written here: scripts/elicitation/make_gold_claims.py has a Claude agent
write them from the finished document.

Q1-Q3 come first and each needs an answer; only then are Q4-Q6 shown, and Q1-Q3 are locked (the
"hypothesis so far" is not rewritten after seeing Q4's what-if). Q4 is a -2..+2 scale with an
hypothesis line, a direction (only for +1/+2) and a why (only when not 0), all required.
"""

import argparse
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from elicitation_schema import (
    ElicitationDocument,
    Response,
    ShiftAnswer,
    Vignette,
    is_synthetic_id,
)
from elicitation_units import MIN_QUOTE_WORDS, _quotes
from make_fixtures import fixture_dir, write_json
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML

from app.vignettes.questions import (
    GATE,
    Q4_HYPOTHESIS,
    Q4_TOWARD,
    Q4_WHY,
    QUESTIONS,
    SHIFT_LABELS,
    SHIFT_LEAD,
    TOWARD_LABELS,
    describe_shift,
    render_question,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data/fixtures"
QUALITY = (
    "answers written by real clinicians in the terminal (answer_vignettes.py); reference claims "
    "written by a Claude agent from those answers (make_gold_claims.py) and not yet confirmed by "
    "the expert. The tier to report results on once the claims are member-checked"
)


# --- pure helpers ------------------------------------------------------------------------------


def quoted_fragments(answers: dict[str, str], vignette_text: str) -> tuple[list[str], list[str]]:
    """(exact fragments of the vignette quoted in the answers, longer quotes that match nothing).

    A quote with "..." is split at the dots first; the pieces are what must be exact."""
    found: list[str] = []
    missing: list[str] = []
    for answer in answers.values():
        for *_, quote in _quotes(answer):
            for piece in (p.strip() for p in quote.replace("…", "...").split("...")):
                if not piece:
                    continue
                if piece in vignette_text:
                    if piece not in found:
                        found.append(piece)
                elif len(piece.split()) >= MIN_QUOTE_WORDS and piece not in missing:
                    missing.append(piece)
    return found, missing


def gate_ids(v: Vignette) -> list[str]:
    """The gate questions this vignette asks: they need answers before anything else is shown."""
    return [q for q in GATE if q in v.question_ids]


def gate_open(v: Vignette, entry: dict) -> bool:
    """True once every asked gate question has a non-blank answer."""
    return all(entry["answers"].get(q, "").strip() for q in gate_ids(v))


def gate_locked(entry: dict) -> bool:
    """True once the expert has moved past the gate: the gate answers are then read-only."""
    return bool(entry.get("gate_passed_at"))


def pass_gate(entry: dict) -> None:
    entry.setdefault("gate_passed_at", now_iso())


def clean_q4(raw: dict | None) -> dict | None:
    """The draft's Q4 answer, normalised: blanks are None, toward only for +1/+2, the other
    explanation only with toward=other. None until a shift is chosen."""
    if not raw or raw.get("shift") is None:
        return None
    shift = int(raw["shift"])

    def text(key: str) -> str | None:
        return (raw.get(key) or "").strip() or None

    toward = raw.get("toward") if shift > 0 else None
    other = text("other_explanation") if toward == "other" else None
    if toward == "other" and not other:
        toward = None  # "another explanation" without naming it says nothing more than the shift
    return {"hypothesis": text("hypothesis"), "shift": shift, "toward": toward,
            "other_explanation": other}  # fmt: skip


def q4_incomplete(entry: dict) -> str | None:
    """What the Q4 step still needs, as a message for the expert; None when complete. All parts
    are required: the hypothesis, the scale, a direction for +1/+2 (with a name for "another
    explanation") and a why unless the scale is 0."""
    raw = entry.get("q4") or {}
    if not (raw.get("hypothesis") or "").strip():
        return "Write your working hypothesis in one sentence."
    if raw.get("shift") is None:
        return "Pick a point on the scale (0 means no change)."
    shift = int(raw["shift"])
    if shift > 0 and raw.get("toward") not in TOWARD_LABELS:
        return "Say which way your hypothesis moves."
    if shift > 0 and raw["toward"] == "other" and not (raw.get("other_explanation") or "").strip():
        return "Name the other explanation."
    if shift != 0 and not entry["answers"].get("Q4", "").strip():
        return "Say why it changes."
    return None


def q4_summary(q4: dict | None) -> str:
    """'+1 partly changes, towards less ADHD-like' (or 'not answered')."""
    q4 = clean_q4(q4)
    if q4 is None:
        return "not answered"
    return describe_shift(q4["shift"], q4["toward"], q4["other_explanation"])


def next_session_id(documents: Path) -> str:
    used = {int(p.stem.rsplit("-", 1)[1]) for p in documents.glob("DOC-[0-9]*.json")}
    return f"DOC-{max(used, default=0) + 1:04d}"


def build_document(
    draft: dict, vignettes: dict[str, Vignette], session_id: str, now: datetime
) -> ElicitationDocument:
    """The document for the vignettes the draft has finished, in the order they were shown."""
    expert_id = draft["expert_id"]
    if is_synthetic_id(expert_id):
        raise ValueError(f"{expert_id!r} is a synthetic id: gold answers are written by people")
    done = [
        (vid, draft["answers"][vid])
        for vid in draft["order"]
        if draft["answers"].get(vid, {}).get("done")
    ]
    if not done:
        raise ValueError("nothing answered yet")
    responses = []
    for vid, entry in done:
        v = vignettes[vid]
        answers = {q: a.strip() for q, a in entry["answers"].items() if a.strip()}
        q4 = clean_q4(entry.get("q4"))
        if q4 is None or q4["shift"] == 0:
            answers.pop("Q4", None)  # a why only goes with a change
        responses.append(
            Response(
                vignette_id=vid,
                vignette_version=v.version,
                vignette_hash=v.content_hash,
                expert_id=expert_id,
                is_synthetic=False,
                answers=answers,
                quoted_fragments=quoted_fragments(answers, v.text)[0],
                rating=entry.get("rating"),
                insufficient_information=entry.get("insufficient", False),
                q4=ShiftAnswer(**q4) if q4 else None,
                started_at=entry["started_at"],
                submitted_at=entry["submitted_at"],
            )
        )
    return ElicitationDocument(
        session_id=session_id,
        expert_id=expert_id,
        created_at=now,
        is_synthetic=False,
        vignettes=[vignettes[vid] for vid, _ in done],
        responses=responses,
    )


class SetupError(ValueError):
    """The session cannot start (bad expert id, missing role, nothing left to answer)."""


# --- files -------------------------------------------------------------------------------------


def load_vignettes(gold: Path, source: Path, wanted: list[str] | None) -> dict[str, Vignette]:
    """The wanted vignettes of the source tier. All of its vignettes are copied unchanged into
    gold/vignettes (same text, same hash), so the tier always has the whole set."""
    out = {}
    for path in sorted((source / "vignettes").glob("V*.json")):
        v = Vignette.model_validate_json(path.read_text())
        target = gold / "vignettes" / path.name
        if not target.exists():
            write_json(target, json.loads(path.read_text()))
        if wanted is None or v.id in wanted:
            out[v.id] = v
    if wanted and (unknown := set(wanted) - out.keys()):
        raise SetupError(f"no such vignettes in {source}: {sorted(unknown)}")
    return out


def answered_before(gold: Path, expert_id: str) -> set[str]:
    done: set[str] = set()
    for path in (gold / "documents").glob("DOC-*.json"):
        doc = json.loads(path.read_text())
        if doc["expert_id"] == expert_id:
            done |= {r["vignette_id"] for r in doc["responses"]}
    return done


def add_manifest_entries(
    gold: Path, doc: ElicitationDocument, source_tier: str, how: str = "human:terminal"
) -> None:
    path = gold / "manifest.json"
    manifest: dict[str, Any] = (
        json.loads(path.read_text()) if path.exists() else {"tier": "gold", "entries": []}
    )
    manifest["quality"] = QUALITY
    have = {(e["id"], e["kind"]) for e in manifest["entries"]}
    created = doc.created_at.isoformat(timespec="seconds")
    new = [
        dict(id=v.id, kind="vignette", tier="gold", source=f"copied:{source_tier}",
             prompt=None, model=None, seed=None, created_at=created,
             path=f"vignettes/{v.id}.json", track=v.design.track, origin=v.design.origin)
        for v in doc.vignettes
    ]  # fmt: skip
    new.append(
        dict(id=doc.session_id, kind="document", tier="gold", source=how,
             expert_id=doc.expert_id, prompt=None, model=None, seed=None, created_at=created,
             path=f"documents/{doc.session_id}.json",
             claims_by="claude-agent", claims_prompt="Gold_reference_claims.v1")
    )  # fmt: skip
    manifest["entries"] += [e for e in new if (e["id"], e["kind"]) not in have]
    write_json(path, manifest)


# --- sessions (terminal and notebook) -----------------------------------------------------------


def draft_path_for(gold: Path, expert_id: str) -> Path:
    return gold / "drafts" / f"{expert_id}.json"


def open_session(
    expert: str,
    role: str | None,
    source: str,
    wanted: list[str] | None,
    order: str = "shuffle",
    text_source: str = "synthetic",
    load=load_vignettes,
) -> tuple[Path, dict[str, Vignette], dict]:
    """(gold dir, the vignettes to ask, the draft: resumed from disk or new). Raises SetupError.

    `source` is the tier the vignettes come from, `text_source` their origin (synthetic|reddit):
    gold lands next to them in data/fixtures/<text_source>/gold. `load` reads the vignettes:
    the notebook passes its own (chip_answers.py)."""
    if is_synthetic_id(expert):
        raise SetupError("expert ids starting with SYN- are synthetic; use e.g. E01")
    gold = fixture_dir("gold", text_source, FIXTURES)
    vignettes = load(gold, fixture_dir(source, text_source, FIXTURES), wanted)
    experts_path = gold / "experts.json"
    experts = json.loads(experts_path.read_text()) if experts_path.exists() else {}
    if role:
        experts[expert] = role
        write_json(experts_path, experts)
    elif expert not in experts:
        raise SetupError("a new expert needs a role, e.g. 'consultant psychiatrist, 12 years'")
    path = draft_path_for(gold, expert)
    if path.exists():
        return gold, vignettes, json.loads(path.read_text())
    todo = [i for i in vignettes if i not in answered_before(gold, expert)]
    if not todo:
        raise SetupError(f"{expert} has already answered all of these vignettes")
    if order == "shuffle":
        random.Random(expert).shuffle(todo)
    return gold, vignettes, {"expert_id": expert, "order": todo, "answers": {}, "skipped": []}


def finish_draft(
    gold: Path, draft: dict, vignettes: dict[str, Vignette], source: str
) -> ElicitationDocument:
    """Write the document of the finished vignettes, its manifest entries, and drop the draft.
    Raises ValueError if nothing is finished."""
    session_id = next_session_id(gold / "documents")
    doc = build_document(draft, vignettes, session_id, datetime.now(UTC))
    write_json(gold / "documents" / f"{session_id}.json", doc.model_dump(mode="json"))
    add_manifest_entries(gold, doc, source)
    draft_path_for(gold, draft["expert_id"]).unlink(missing_ok=True)
    return doc


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --- the terminal app --------------------------------------------------------------------------


class Quit(Exception):
    pass


class Skip(Exception):
    pass


def ask(
    session: PromptSession, label: str, default: str = "", required: bool = False,
    need: str = f"{'/'.join(GATE)} need an answer before the next questions.",
) -> str:  # fmt: skip
    """One multi-line answer. `:quit` / `:skip` as the whole answer raise. `required`: a blank
    answer is asked again, with the message `need`."""
    print(f"\n{label}\n")
    blank = "needed" if required else "no answer"
    while True:
        text = session.prompt(
            HTML("<b>&gt;</b> "),
            default=default,
            bottom_toolbar=f" Esc then Enter: submit   blank: {blank}   :skip   :quit pause ",
        ).strip()
        if text == ":quit":
            raise Quit
        if text == ":skip":
            raise Skip
        if text or not required:
            return text
        print(need)


def ask_line(session: PromptSession, label: str) -> str:
    raw = session.prompt(HTML(label + "\n&gt; ")).strip()
    if raw == ":quit":
        raise Quit
    if raw == ":skip":
        raise Skip
    return raw


def ask_q4(session: PromptSession, line: PromptSession, v: Vignette, entry: dict) -> None:
    """Q4: hypothesis line, the -2..+2 scale, a direction for +1/+2, a why unless 0."""
    question = render_question(QUESTIONS["Q4"], v.q4_whatif)
    print(f"\nQ4: {question}")
    old = entry.get("q4") or {}
    if old.get("hypothesis"):
        print(f"(Enter keeps: {old['hypothesis']})")
    while not (hypothesis := ask_line(line, f"\n{Q4_HYPOTHESIS}") or old.get("hypothesis") or ""):
        print("The hypothesis is needed.")
    print(f"\n{SHIFT_LEAD}")
    for k, label in SHIFT_LABELS.items():
        print(f"  {k:+d} {label}" if k else f"   0 {label}")
    while True:
        raw = ask_line(line, "type -2, -1, 0, +1 or +2").replace("+", "")
        if raw in {"-2", "-1", "0", "1", "2"}:
            shift = int(raw)
            break
    toward, other = None, None
    if shift > 0:
        keys = {"m": "more_adhd", "l": "less_adhd", "o": "other"}
        menu = "   ".join(f"{k}: {TOWARD_LABELS[t]}" for k, t in keys.items())
        while True:
            raw = ask_line(line, f"{Q4_TOWARD}   {menu}").lower()
            if raw in keys:
                break
        toward = keys[raw]
        while toward == "other" and not other:
            other = ask_line(line, "Which explanation?") or None
    entry["q4"] = clean_q4({"hypothesis": hypothesis, "shift": shift, "toward": toward,
                            "other_explanation": other})  # fmt: skip
    if shift != 0:
        entry["answers"]["Q4"] = ask(
            session, Q4_WHY, default=entry["answers"].get("Q4", ""), required=True,
            need="Say why it changes (at 0 no reason is asked).",
        )  # fmt: skip
    else:
        entry["answers"].pop("Q4", None)


def ask_rating(session: PromptSession) -> tuple[int | None, bool]:
    while True:
        raw = session.prompt(
            HTML("\n<b>Q6</b> " + QUESTIONS["Q6"].text.replace("&", "&amp;") + "\n&gt; ")
        ).strip().lower()  # fmt: skip
        if raw == ":quit":
            raise Quit
        if raw == ":skip":
            raise Skip
        if raw in {"1", "2", "3", "4", "5"}:
            return int(raw), False
        if raw in {"i", "insufficient", "insufficient information"}:
            return None, True
        print("type 1-5, or i for insufficient information")


def answer_vignette(
    session: PromptSession, line: PromptSession, v: Vignette, entry: dict, save
) -> None:
    """Fill `entry` question by question (resuming), then review. `save()` writes the draft."""
    print("\n" + "=" * 100)
    print(f"{v.id}  ({v.framing.replace('_', ' ')}, {v.word_count} words)\n")
    print(v.text)
    gate = gate_ids(v)
    for qid in v.question_ids:
        kind = QUESTIONS[qid].kind
        if qid not in gate and not gate_locked(entry):
            pass_gate(entry)  # every gate question is answered by now
            save()
        if kind == "open":
            if entry["answers"].get(qid, "").strip() or (
                qid not in gate and qid in entry["answers"]
            ):
                continue
            entry["answers"][qid] = ask(
                session, f"{qid}: {render_question(QUESTIONS[qid], v.q4_whatif)}",
                required=qid in gate,
            )  # fmt: skip
        elif kind == "shift":
            if q4_incomplete(entry) is None:  # the notebook may leave a half-answered Q4
                continue
            ask_q4(session, line, v, entry)
        elif "rating" not in entry:
            entry["rating"], entry["insufficient"] = ask_rating(session)
        save()
    open_ids = [q for q in v.question_ids if QUESTIONS[q].kind == "open"]
    while True:  # review
        locked = gate_locked(entry)
        print("\n" + "-" * 100 + "\nYour answers:")
        for qid in v.question_ids:
            if qid == "Q4":
                q4 = clean_q4(entry.get("q4"))
                print(f"\nQ4: {q4_summary(q4)}")
                if q4 and q4["hypothesis"]:
                    print(f"    hypothesis: {q4['hypothesis']}")
                if entry["answers"].get("Q4"):
                    print(f"    why: {entry['answers']['Q4']}")
            elif qid == "Q6":
                shown = "insufficient information" if entry["insufficient"] else entry["rating"]
                print(f"\nQ6: {shown}")
            else:
                lock = " (locked)" if locked and qid in gate else ""
                print(f"\n{qid}{lock}: {entry['answers'][qid] or '(blank)'}")
        _, unmatched = quoted_fragments(entry["answers"], v.text)
        for q in unmatched:
            print(f"\n  note: quoted but not an exact piece of the text: {q!r}")
        editable = [q for q in v.question_ids if not (locked and q in gate)]
        menu = "   ".join(
            f"{q[1]}: {'re-rate' if q == 'Q6' else 'redo' if q == 'Q4' else 're-edit'} {q}"
            for q in editable
        )
        choice = session.prompt(f"\nEnter: accept   {menu}   > ").strip()
        if not choice:
            break
        qid = f"Q{choice}"
        if qid not in editable:
            if qid in gate:
                print(f"{qid} is locked: you have seen the questions after it.")
            continue
        if qid == "Q6":
            entry["rating"], entry["insufficient"] = ask_rating(session)
        elif qid == "Q4":
            ask_q4(session, line, v, entry)
        elif qid in open_ids:
            entry["answers"][qid] = ask(
                session, f"{qid}: edit", default=entry["answers"][qid], required=qid in gate
            )
        save()
    if (
        not any(entry["answers"].values())
        and not entry.get("rating")
        and not entry.get("insufficient")
        and not entry.get("q4")
    ):
        raise Skip
    entry["done"], entry["submitted_at"] = True, now_iso()


def run(args: argparse.Namespace) -> int:
    resumed = draft_path_for(fixture_dir("gold", args.text_source, FIXTURES), args.expert).exists()
    try:
        gold, vignettes, draft = open_session(
            args.expert, args.role, args.source, args.vignettes, args.order, args.text_source
        )
    except SetupError as e:
        raise SystemExit(str(e)) from e
    draft_path = draft_path_for(gold, args.expert)
    if resumed:
        print(f"resuming draft of {args.expert}")

    def save() -> None:
        write_json(draft_path, draft)

    session = PromptSession(multiline=True)
    line = PromptSession()
    todo = [i for i in draft["order"] if i not in draft["skipped"]
            and not draft["answers"].get(i, {}).get("done")]  # fmt: skip
    print(f"{len(todo)} vignettes to go")
    try:
        for n, vid in enumerate(todo, 1):
            if draft["answers"].get(vid) is None:
                what = line.prompt(
                    f"\n[{n}/{len(todo)}] {vid}: Enter start, s skip, f finish, q pause > "
                )
                if what.strip() == "q":
                    raise Quit
                if what.strip() == "f":
                    break
                if what.strip() == "s":
                    draft["skipped"].append(vid)
                    save()
                    continue
                draft["answers"][vid] = {"started_at": now_iso(), "answers": {}}
            try:
                answer_vignette(session, line, vignettes[vid], draft["answers"][vid], save)
            except Skip:
                draft["answers"].pop(vid, None)
                draft["skipped"].append(vid)
            save()
    except (Quit, KeyboardInterrupt, EOFError):
        save()
        print(f"\npaused; run the same command to resume ({draft_path})")
        return 0

    try:
        doc = finish_draft(gold, draft, vignettes, args.source)
    except ValueError as e:
        print(f"no document written: {e}")
        return 1
    print(
        f"\nwrote {doc.session_id} with {len(doc.responses)} vignettes. Next: make_gold_claims.py"
    )
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--expert", required=True, help="expert id, e.g. E01 (not SYN-...)")
    ap.add_argument(
        "--role", help="e.g. 'consultant psychiatrist, 12 years in an adult ADHD service'"
    )
    ap.add_argument("--from", dest="source", default="silver", help="tier to take vignettes from")
    ap.add_argument(
        "--source",
        dest="text_source",
        default="synthetic",
        choices=["synthetic", "reddit"],
        help="whose vignettes: model-written or real r/ADHD posts",
    )
    ap.add_argument("--vignettes", nargs="+", help="only these ids (default: all)")
    ap.add_argument("--order", choices=["shuffle", "fixed"], default="shuffle")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
