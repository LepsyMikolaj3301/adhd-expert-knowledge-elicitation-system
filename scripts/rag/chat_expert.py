"""Chat with the expert-notes generator and rate every answer as a clinician (human gold ratings).

Usage: python scripts/rag/chat_expert.py --rater mk [--tier silver|gold] [--model qwen3.5:9b]
           [--representation B1] [--budget 500]

A terminal loop over the same retrieval and generator as eval_expert_generation.py. Two modes:
  :a   a clinician question ("how do I tell goal-loss digression from rumination in an email?")
  :b   analysis of a patient text: paste one (Esc then Enter), or `:v V006` to load a fixture
       vignette (its units and its A/B sibling's are hidden from retrieval); then ask about it
Other commands: :new (forget the conversation), :tips, :q. Anything else is your question.

After each answer you rate it with the judge's fields (key_points fidelity attribution usefulness
citations, 1-5, `-` when not applicable), flag unsupported claims, mark which notes were relevant
and may list the key points you expected. Everything goes to data/eval/expert_runs/human-<rater>/:
generations.json (a normal expert run) and judgments_human.json, so judge_generations.py can export
the same run blind to Claude agents (--export-blind --tag j1) and
`eval_expert_generation.py --report <run dir>` compares human and judge. Running again resumes.
"""

import argparse
import json
import random
import sys
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any

import numpy as np
from elicitation_units import sentences
from eval_expert_generation import EXPERT_SYSTEM_PROMPT, build_prompt, checks
from eval_expert_units import parse
from expert_metrics import fill_budget
from expert_retrieval import LEAN, ROOT, Searcher, build_indexes, load_fixture, make_embed
from judge_generations import write_judgments
from make_unit_keys import load_units
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rag_common import (
    EXPERT_FIELDS,
    GENERATION_OPTIONS,
    NOT_IN_SOURCES,
    OllamaChat,
    bm25_config,
    query_embedder,
    write_json,
)

from expert_knowledge_core.prompts import PATIENT_SYSTEM_PROMPT, build_patient_prompt  # noqa: F401

RUNS = ROOT / "data/eval/expert_runs"
DEFAULT_B_QUESTION = (
    "Which passages would colleagues read as ADHD-related, and what else could explain them?"
)
KEEP_TURNS = 3  # earlier question/answer pairs sent back to the model
CONTEXT_OF = {"a": "units", "b": "patient"}
TYPE_OF = {"a": "clinician_question", "b": "patient_text"}

TIPS = """How to ask (keep it similar to what the notes are about):
  - Ask in general terms, as before seeing any particular patient: no names, no "this text".
    Good: "how do I tell goal-loss digression from rumination in a patient's email?"
  - Vary the topic: reading style, alternative explanations (low mood, sleep, anxiety), base rates,
    what is missing from a text, how a reading changes with context, over- and under-reading.
  - The notes are answers to six questions: Q1 which fragments and why, Q2 what else could explain
    them, Q3 what is missing, Q4 how their hypothesis changes (-2 reinforced .. +2 changes
    completely) given one more fact about the writer ("what if they had an exam that day?"),
    Q5 what a less experienced clinician would over- or under-read. Questions that
    fit one of these land on notes.
  - Follow-ups work ("and if the person is a student?"); :new starts again.
  - Mode B (:b): paste 120-250 words of first-person text, or `:v <id>`; then ask about it, or
    press Enter for the default question."""


# --- pure helpers (tested in tests/test_gold.py) -----------------------------------------------


def parse_scores(text: str) -> dict:
    """'4 - 5 4 -' -> the five judge fields; `-` is None (allowed for fidelity and citations)."""
    parts = text.split()
    if len(parts) != len(EXPERT_FIELDS):
        raise ValueError(f"need {len(EXPERT_FIELDS)} values: {' '.join(EXPERT_FIELDS)}")
    out = {}
    for name, part in zip(EXPERT_FIELDS, parts, strict=True):
        if part == "-" and name in ("fidelity", "citation_quality"):
            out[name] = None
        elif part in {"1", "2", "3", "4", "5"}:
            out[name] = int(part)
        else:
            raise ValueError(
                f"{name}: type 1-5" + (" or -" if name in ("fidelity", "citation_quality") else "")
            )
    return out


def parse_numbers(text: str, n: int) -> list[int]:
    """'1 3' or '1,3' -> [1, 3], each within 1..n."""
    nums = [int(x) for x in text.replace(",", " ").split()]
    if any(not 1 <= k <= n for k in nums):
        raise ValueError(f"notes are numbered 1-{n}")
    return sorted(set(nums))


def human_pass(scores: dict, unsupported: bool) -> bool:
    """The rubric's pass rule (EXPERT_JUDGE_RUBRIC)."""
    fidelity = scores["fidelity"]
    return (
        (fidelity is None or fidelity >= 4)
        and scores["attribution"] >= 4
        and scores["key_points"] >= 3
        and not unsupported
    )


def judgment_row(
    qid: str, model: str, context: str, scores: dict, unsupported: bool,
    abstention_ok: bool | None, comment: str,
) -> dict:  # fmt: skip
    """One row in the shape of an LLM judge's judgments (judge_generations.write_judgments)."""
    return {
        "id": qid, "model": model, "context": context, "sample": 1, **scores,
        "unsupported_claims": unsupported, "abstention_ok": abstention_ok,
        "pass": human_pass(scores, unsupported), "rationale": comment,
    }  # fmt: skip


def siblings(vignettes: dict, vid: str) -> set[str]:
    """The vignette and its A/B partner: their units would just echo the text being analysed."""
    v = vignettes[vid]
    return {
        w.id
        for w in vignettes.values()
        if w.id == vid or (v.variant and w.variant and w.variant.pair_id == v.variant.pair_id)
    }


def judged_question(mode: str, patient_text: str | None, earlier: list[str], question: str) -> str:
    """The question as a judge must read it alone: patient text and earlier questions included."""
    parts = []
    if mode == "b":
        parts.append(f'Patient text:\n"{patient_text}"')
    if earlier:
        parts.append("Earlier in the conversation the clinician asked: " + " | ".join(earlier))
    parts.append(f"Question: {question}" if parts else question)
    return "\n\n".join(parts)


# --- retrieval and generation ------------------------------------------------------------------


class Notes:
    """The expert answers of a tier, indexed as in the experiment (default B1), searched hybrid."""

    def __init__(
        self, tier: str, representation: str, budget: int, source: str = "synthetic"
    ) -> None:
        self.budget = budget
        self.vignettes, _, answers = load_fixture(tier, source)
        units, lean = load_units(tier, source=source), load_units(tier, source=source, **LEAN)
        if not units:
            raise SystemExit(f"no expert answers in data/fixtures/{source}/{tier}/documents")
        self.name, self.mode, self.diversity = parse(representation)
        items = build_indexes(units, lean, answers, {})[self.name]
        self.unit_vignette = {u.unit_id: u.vignette_id for u in units}
        self.searcher = Searcher(items, make_embed(query_embedder()), bm25_config())
        shown = set(self.unit_vignette.values())
        self.targets = {
            vid: v.design.knowledge_target or v.design.purpose
            for vid, v in self.vignettes.items()
            if vid in shown
        }

    def get(
        self, strings: list[str], hide: Collection[str] = frozenset()
    ) -> tuple[list[dict], list[str]]:
        """(notes within the token budget, the top 20 unit ids retrieved)."""
        s = self.searcher
        allowed = np.array([self.unit_vignette[it.unit_ids[0]] not in hide for it in s.items])
        ranked = [s.items[i] for i in s.rank(strings, allowed, self.mode, self.diversity)[:50]]
        notes = [
            {"id": it.unit_ids[0], "text": it.shown} for it in fill_budget(ranked, self.budget)
        ]
        return notes, [it.unit_ids[0] for it in ranked[:20]]


def patient_prompt(text: str, question: str, notes: list[dict]) -> str:
    return build_patient_prompt(text, question, [c["text"] for c in notes])


# --- the loop ----------------------------------------------------------------------------------


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def print_tips(notes: Notes) -> None:
    print("\n" + TIPS)
    print("\nWhat the answers behind the notes are about (vignette: what it was meant to teach):")
    for vid, target in notes.targets.items():
        print(f"  {vid}: {target}")
    latest = ROOT / "data/eval/expert_units/latest.json"
    if latest.exists():
        examples = [q["question"] for q in json.loads(latest.read_text())["questions"]]
        print("\nExample questions:")
        for q in random.sample(examples, min(3, len(examples))):
            print(f"  - {q}")
    print("\nCommands: :a  :b  :v <id>  :new  :tips  :q\n")


def load_vignette(notes: Notes, vid: str) -> tuple[str | None, set[str]]:
    """(text, units to hide) for a fixture vignette used as the patient text."""
    if vid not in notes.vignettes:
        print(f"no vignette {vid!r}; have {', '.join(notes.vignettes)}")
        return None, set()
    hide = siblings(notes.vignettes, vid)
    text = notes.vignettes[vid].text
    print(f"\n{text}\n(hiding notes on {', '.join(sorted(hide))})")
    return text, hide


def rate(
    session: PromptSession, notes: list[dict], abstained: bool, qid: str, model: str, context: str
):
    """Ask for the rating; returns (judgment row | None, relevant note numbers, expected points)."""
    print(f"\nRate it. Fields: {' '.join(EXPERT_FIELDS)} (1-5; - if not applicable); s = skip")
    while True:
        raw = session.prompt("scores > ").strip()
        if raw == "s":
            return None, [], []
        try:
            scores = parse_scores(raw)
            break
        except ValueError as e:
            print(f"  {e}")
    unsupported = (
        session.prompt("states something the notes do not support? [y/N] > ")
        .strip()
        .lower()
        .startswith("y")
    )
    abstention_ok = None
    if abstained:
        abstention_ok = (
            session.prompt("it abstained: were the notes really irrelevant? [y/N] > ")
            .strip()
            .lower()
            .startswith("y")
        )
    relevant: list[int] = []
    while notes:
        try:
            relevant = parse_numbers(
                session.prompt("notes that were relevant, e.g. 1 3 (Enter: none) > "), len(notes)
            )
            break
        except ValueError as e:
            print(f"  {e}")
    print("key points a good answer should contain, one per line (Enter on an empty line to end):")
    points = []
    while line := session.prompt("  - ").strip():
        points.append(line)
    comment = session.prompt("comment (optional) > ").strip()
    row = judgment_row(qid, model, context, scores, unsupported, abstention_ok, comment)
    print(f"  -> {'PASS' if row['pass'] else 'fail'} by the rubric's rule")
    return row, relevant, points


def run(args: argparse.Namespace) -> int:
    notes_index = Notes(args.tier, args.representation, args.budget, args.source)
    run_dir = RUNS / f"human-{args.rater}"
    path = run_dir / "generations.json"
    run_data: dict[str, Any]
    if path.exists():
        run_data = json.loads(path.read_text())
        print(f"resuming {path}: {len(run_data['questions'])} questions so far")
    else:
        run_data = {
            "kind": "expert", "generated_at": now(), "rater": args.rater, "model": args.model,
            "options": {**GENERATION_OPTIONS, "temperature": 0.3}, "tier": args.tier,
            "source": args.source,
            "representation": args.representation, "budget": args.budget, "labels": "human",
            "questions": {}, "generations": [],
        }  # fmt: skip
    chat = OllamaChat(args.model, think=False, temperature=0.3, seed=1)
    session = PromptSession()
    paste = PromptSession(multiline=True)
    mode, patient_text, hide = "a", None, set()
    history: list[tuple[str, str]] = []  # (question, answer)
    print_tips(notes_index)

    while True:
        try:
            if mode == "b" and patient_text is None:
                text = paste.prompt(
                    HTML("<b>Patient text</b> (Esc then Enter to submit, or :v V006)\n&gt; ")
                ).strip()
                if text.startswith(":v"):
                    patient_text, hide = load_vignette(notes_index, text[2:].strip())
                else:
                    patient_text, hide = text or None, set()
                history = []
                if patient_text is None:
                    continue
            prompt = f"[{'clinician question' if mode == 'a' else 'about the text'}] > "
            line = session.prompt(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in (":q", ":quit"):
            break
        if line == ":tips":
            print_tips(notes_index)
        elif line == ":new":
            history = []
        elif line in (":a", ":b"):
            mode, patient_text, hide, history = line[1], None, set(), []
        elif line.startswith(":v"):
            mode, history = "b", []
            patient_text, hide = load_vignette(notes_index, line[2:].strip())
        elif line.startswith(":"):
            print("commands: :a :b :new :tips :q")
        elif line or mode == "b":
            question = line or DEFAULT_B_QUESTION
            earlier = [q for q, _ in history]
            patient = patient_text or ""  # set in mode b: the loop above asks for it first
            strings = sentences(patient) if mode == "b" else []
            strings = [*strings, question, *earlier[-1:]]
            notes, retrieved = notes_index.get(strings, hide)
            system = PATIENT_SYSTEM_PROMPT if mode == "b" else EXPERT_SYSTEM_PROMPT
            user = (
                patient_prompt(patient, question, notes)
                if mode == "b"
                else build_prompt(question, notes)
            )
            past = [
                m
                for q, a in history[-KEEP_TURNS:]
                for m in ({"role": "user", "content": q}, {"role": "assistant", "content": a})
            ]
            try:
                answer, stats = chat.chat(system, user, past)
            except Exception as e:  # keep the session alive if Ollama hiccups
                print(f"generation failed: {type(e).__name__}: {e}")
                continue
            print("\nNotes retrieved:")
            for n, c in enumerate(notes, 1):
                print(f"  [E{n}] {c['text']}\n")
            print(f"Answer ({stats['seconds']}s):\n\n{answer}")
            history.append((question, answer))

            qid = f"Q{len(run_data['questions']) + 1:03d}"
            context = CONTEXT_OF[mode]
            item: dict[str, Any] = {
                "question": judged_question(mode, patient_text, earlier, question),
                "type": TYPE_OF[mode], "patient_text": patient_text, "reference_points": [],
                "relevant_units": [], "retrieved": retrieved, "contexts": {context: notes},
            }  # fmt: skip
            row, relevant, points = rate(
                session, notes, NOT_IN_SOURCES in answer, qid, args.model, context
            )
            item["relevant_units"] = [notes[k - 1]["id"] for k in relevant]
            item["reference_points"] = points
            run_data["questions"][qid] = item
            run_data["generations"].append(
                {
                    "id": qid,
                    "model": args.model,
                    "context": context,
                    "sample": 1,
                    "answer": answer,
                    "checks": checks(item, answer, notes),
                    "stats": stats,
                }  # fmt: skip
            )
            write_json(path, run_data)
            if row:
                write_judgments(
                    run_dir,
                    f"human:{args.rater}",
                    [row],
                    [],
                    "human rating with the fields of EXPERT_JUDGE_RUBRIC",
                    "human",
                )
            print(f"saved {qid}\n")
    print(f"\nbye: {len(run_data['questions'])} questions in {path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rater", required=True, help="short name; the run is human-<rater>")
    ap.add_argument("--tier", default="silver", choices=["bronze", "silver", "gold"],
                    help="whose expert answers are the notes")  # fmt: skip
    ap.add_argument("--source", default="synthetic", choices=["synthetic", "chips"])
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument(
        "--representation", default="B1", help="experiment label, as in eval_expert_units"
    )
    ap.add_argument("--budget", type=int, default=500, help="tokens of notes per answer")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
