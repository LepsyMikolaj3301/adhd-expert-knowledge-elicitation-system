"""The rules behind notebooks/answer_vignettes.ipynb: citations, chips, the lock-in, the document.

A clinician answers the chip vignettes the way the web platform asks them (docs/frontend-vignettes.md):
cite passages, give each a direction, write free text that cites them, lock in Q1-Q3, then answer
Q4-Q6. The result is a gold ChipDocument in data/fixtures_chips/synthetic/gold.

No widgets here, so all of it can be tested. In a draft, answers hold `⟦hN⟧` chips; the expert sees
and types them as `[N]`, because a plain text box can't show a chip as one unit.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import answer_vignettes as av
from chips_schema import CHIP_RE, Q1_CHIPS, ChipDocument, ChipResponse, Highlight
from make_fixtures import CHIP_SOURCE, fixture_dir, write_json

from app.assignments.answers import count_words
from app.elicitation.questions import QUESTIONS_BY_ID, render_question
from app.elicitation.schema import ShiftAnswer, Vignette, is_synthetic_id
from app.vignettes.questions import HYPOTHESIS_MIN_WORDS, QUESTION_IDS, QUESTIONS

SOURCE = CHIP_SOURCE
REVIEW = "review"
WHATIFS = Path(__file__).with_name("chip_whatifs.json")

MAX_CITATION_LENGTH = 2000  # the platform's limit on one citation
Q1_NUDGE_WORDS = 60
_WORD_CHARACTER = re.compile(r"[\w'’-]")
_NUMBER = re.compile(r"\[(\d+)\]")
_QUOTE_MARKS = "\"'“”‘’"


# --- which vignettes ----------------------------------------------------------------------------


def source_tiers() -> list[str]:
    """The tiers with vignettes to answer. Gold is where the answers go, not where they come from."""
    base = fixture_dir("gold", SOURCE, av.FIXTURES).parent
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "vignettes").is_dir() and p.name != "gold")


def load_vignettes(gold: Path, source: Path, wanted: list[str] | None) -> dict[str, Vignette]:
    """The chip vignettes as the platform asks them: all six questions, with the what-if for Q4.
    The fixture files have neither, as the chip test left Q4 out. Their text doesn't change."""
    whatifs: dict[str, str] = json.loads(WHATIFS.read_text())
    out: dict[str, Vignette] = {}
    for path in sorted((source / "vignettes").glob("V*.json")):
        raw = json.loads(path.read_text())
        whatif = whatifs.get(raw["id"])
        if not whatif:
            raise av.SetupError(f"{raw['id']} has no what-if in {WHATIFS.name}")
        raw |= {"q4_whatif": whatif, "question_ids": list(QUESTION_IDS)}
        v = Vignette.model_validate(raw)
        target = gold / "vignettes" / path.name
        if not target.exists():
            write_json(target, raw)
        if wanted is None or v.id in wanted:
            out[v.id] = v
    return out


def open_session(
    expert: str, role: str | None, source: str, order: str = "shuffle"
) -> tuple[Path, dict[str, Vignette], dict]:
    return av.open_session(expert, role, source, None, order, SOURCE, load=load_vignettes)


def question_text(qid: str, v: Vignette) -> str:
    return Q1_CHIPS if qid == "Q1" else render_question(QUESTIONS_BY_ID[qid], v.q4_whatif)


# --- citations ----------------------------------------------------------------------------------


def _find_passage(text: str, pasted: str) -> tuple[int, int] | None:
    """Where the pasted words are. Copying can change the spaces and add quotation marks."""
    words = pasted.strip().strip(_QUOTE_MARKS).split()
    match = re.search(r"\s+".join(map(re.escape, words)), text)
    if not match:
        return None
    start, end = match.span()
    # A selection that stopped inside a word still means the word.
    while start > 0 and _WORD_CHARACTER.match(text[start]) and _WORD_CHARACTER.match(text[start - 1]):
        start -= 1
    while (
        end < len(text) and _WORD_CHARACTER.match(text[end - 1]) and _WORD_CHARACTER.match(text[end])
    ):
        end += 1
    return start, end


def add_citation(citations: list[dict], text: str, pasted: str) -> tuple[list[dict], str]:
    """(the citations, what happened): added, duplicate:<chip>, not_found, too_long or empty."""
    if not pasted.strip().strip(_QUOTE_MARKS).strip():
        return citations, "empty"
    found = _find_passage(text, pasted)
    if found is None:
        return citations, "not_found"
    start, end = found
    for existing in citations:
        if list(existing["span"]) == [start, end]:
            return citations, f"duplicate:{existing['chip']}"
    if end - start > MAX_CITATION_LENGTH:
        return citations, "too_long"
    new = {"chip": len(citations) + 1, "text": text[start:end], "span": [start, end],
           "direction": None}  # fmt: skip
    return [*citations, new], "added"


def _without_chip(answer: str, chip: int) -> str:
    def replace(match: re.Match[str]) -> str:
        at, before, after = match.start(), match.group(1), match.group(2)
        following = answer[match.end() : match.end() + 1]
        if at == 0 or answer[at - 1] == "\n" or re.match(r"[.,;:!?)]", following):
            return ""
        return " " if before and after else before + after

    return re.sub(rf"( ?)⟦h{chip}⟧( ?)", replace, answer)


def remove_citation(
    citations: list[dict], answers: dict[str, str], chip: int
) -> tuple[list[dict], dict[str, str]]:
    """Takes a citation out and moves the later ones up, so that the numbers stay 1..n. Locked
    answers can't change: they cite only locked citations, which come first and are never removed."""

    def renumber(match: re.Match[str]) -> str:
        n = int(match.group(1))
        return f"⟦h{n - 1}⟧" if n > chip else match.group(0)

    return (
        [
            {**c, "chip": c["chip"] - 1} if c["chip"] > chip else c
            for c in citations
            if c["chip"] != chip
        ],
        {q: CHIP_RE.sub(renumber, _without_chip(a, chip)) for q, a in answers.items()},
    )


def to_tokens(shown: str, count: int) -> str:
    """`[2]` as the expert types it to `⟦h2⟧` as it is stored, if citation 2 exists."""
    return _NUMBER.sub(
        lambda m: f"⟦h{m.group(1)}⟧" if 1 <= int(m.group(1)) <= count else m.group(0), shown
    )


def to_display(stored: str) -> str:
    return CHIP_RE.sub(lambda m: f"[{m.group(1)}]", stored)


def unknown_numbers(shown: str, count: int) -> list[int]:
    numbers = (int(n) for n in _NUMBER.findall(shown))
    return list(dict.fromkeys(n for n in numbers if not 1 <= n <= count))


def uncited(citations: list[dict], answers: dict[str, str]) -> list[int]:
    cited = {int(n) for answer in answers.values() for n in CHIP_RE.findall(answer)}
    return [c["chip"] for c in citations if c["chip"] not in cited]


# --- what each step needs -----------------------------------------------------------------------


def _short(label: str, text: str, minimum: int | None) -> str | None:
    words = count_words(text)
    if minimum is not None and words < minimum:
        return f"{label} has {words} of {minimum} different words."
    return None


def _q4_problem(entry: dict) -> str | None:
    raw = entry.get("q4") or {}
    hypothesis = (raw.get("hypothesis") or "").strip()
    if hypothesis and (short := _short("Your hypothesis", hypothesis, HYPOTHESIS_MIN_WORDS)):
        return short
    if missing := av.q4_incomplete(entry):
        return missing
    if int(raw["shift"]) == 0:
        return None
    return _short("Why?", entry["answers"].get("Q4", ""), QUESTIONS["Q4"].min_words)


def step_problem(v: Vignette, entry: dict, qid: str) -> str | None:
    """The first thing stopping the expert from leaving this question, in words they can act on."""
    kind = QUESTIONS_BY_ID[qid].kind
    if kind == "shift":
        return _q4_problem(entry)
    if kind == "rating_1_5":
        if entry.get("rating") or entry.get("insufficient"):
            return None
        return "Pick a rating from 1 to 5, or “Insufficient information”."
    return _short(qid, entry["answers"].get(qid, ""), QUESTIONS[qid].min_words)


def first_open_step(v: Vignette, entry: dict) -> str:
    """Where to open a vignette. Before the lock-in that is at most Q3, which holds its button."""
    gate = av.gate_ids(v)
    locked = av.gate_locked(entry)
    if not locked:
        for qid in gate:
            if step_problem(v, entry, qid):
                return qid
        if gate:
            return gate[-1]
    for qid in v.question_ids:
        if qid not in gate and step_problem(v, entry, qid):
            return qid
    return REVIEW


def _direction_problem(entry: dict) -> str | None:
    missing = [c["chip"] for c in entry.get("highlights", []) if not c.get("direction")]
    if not missing:
        return None
    if len(missing) == 1:
        return f"Choose a direction for citation {missing[0]}."
    return f"Choose a direction for citations {', '.join(map(str, missing))}."


def lock_problem(v: Vignette, entry: dict) -> str | None:
    for qid in av.gate_ids(v):
        if problem := step_problem(v, entry, qid):
            return problem
    return _direction_problem(entry)


def _uncited_warning(entry: dict) -> list[str]:
    numbers = uncited(entry.get("highlights", []), entry["answers"])
    if not numbers:
        return []
    listed = ", ".join(map(str, numbers))
    return [f"Citation {listed} is not cited in any answer." if len(numbers) == 1
            else f"Citations {listed} are not cited in any answer."]  # fmt: skip


def lock_warnings(entry: dict) -> list[str]:
    """Worth a second look, but never a reason to stop: some texts have nothing to cite."""
    if not entry.get("highlights"):
        return ["You have no citations. Some texts have nothing to cite, but check you meant this."]
    return _uncited_warning(entry)


def submit_warnings(entry: dict) -> list[str]:
    return _uncited_warning(entry)


def lock_in(entry: dict) -> None:
    """Q1-Q3 and the citations so far can't change from here on. The first time recorded stands."""
    av.pass_gate(entry)
    entry.setdefault("locked_highlights", len(entry.get("highlights", [])))


def q1_nudge(answer: str) -> bool:
    return len(answer.split()) > Q1_NUDGE_WORDS and not CHIP_RE.search(answer)


def accept_problem(v: Vignette, entry: dict) -> str | None:
    if not av.gate_locked(entry):
        return "Lock in your results first."
    for qid in v.question_ids:
        if qid not in av.gate_ids(v) and (problem := step_problem(v, entry, qid)):
            return problem
    return _direction_problem(entry)


# --- the document -------------------------------------------------------------------------------


def build_document(
    draft: dict, vignettes: dict[str, Vignette], session_id: str, now: datetime
) -> ChipDocument:
    """The document of the vignettes the draft has finished, in the order they were shown."""
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
        q4 = av.clean_q4(entry.get("q4"))
        if q4 is None or q4["shift"] == 0:
            answers.pop("Q4", None)  # the screen remembers it, but a why only goes with a change
        citations = [Highlight(**c) for c in entry.get("highlights", [])]
        responses.append(
            ChipResponse(
                vignette_id=vid,
                vignette_version=v.version,
                vignette_hash=v.content_hash,
                expert_id=expert_id,
                is_synthetic=False,
                answers=answers,
                quoted_fragments=list(dict.fromkeys(c.text for c in citations)),
                highlights=citations,
                locked_highlights=entry.get("locked_highlights", 0),
                rating=entry.get("rating"),
                insufficient_information=entry.get("insufficient", False),
                q4=ShiftAnswer(**q4) if q4 else None,
                started_at=entry["started_at"],
                submitted_at=entry["submitted_at"],
            )
        )
    return ChipDocument(
        session_id=session_id,
        expert_id=expert_id,
        created_at=now,
        is_synthetic=False,
        vignettes=[vignettes[vid] for vid, _ in done],
        responses=responses,
    )


def finish_draft(
    gold: Path, draft: dict, vignettes: dict[str, Vignette], source: str
) -> ChipDocument:
    """Write the document and its manifest entries, and drop the draft. ValueError if nothing is
    finished."""
    session_id = av.next_session_id(gold / "documents")
    doc = build_document(draft, vignettes, session_id, datetime.now(UTC))
    write_json(gold / "documents" / f"{session_id}.json", doc.model_dump(mode="json"))
    av.add_manifest_entries(gold, doc, source, how="human:notebook")
    av.draft_path_for(gold, draft["expert_id"]).unlink(missing_ok=True)
    return doc
