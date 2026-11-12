"""Chip answers -> fragment units (steps 2, 4, 6, 7, 9 of docs/new-chips-knowledge.md). No models.

Records are plain dicts (JSON in, JSON out). One record per response:
  highlights  [{id h1|i1, origin expert|implicit, chip, span, text, direction}]
  sentences   [{id Q1.3, question_id, idx, span, text, targets [h1.. | i1.. | case], assigned_by}]
  units       [{id, kind fragment|case, highlight, direction, sentences, context, body, i1, i3}]
  flags       checks that only flag (coverage, direction vs text)
Step 3 (the classifier, ids only) happens outside this module; `apply_classification` takes its
output. Sentence splitting and quote matching are written here because the B1 helpers in
scripts/elicitation/elicitation_units.py are tuned to other inputs (sentence starts, a fixed 0.8
ratio).

This is the one copy of the pipeline: the web application's worker uses it, and so do the scripts
(scripts/elicitation/chip_findings.py re-exports it). What the retrieval side shares with it
(sentence splitting, chip rendering, the units' header, packing) lives in
expert_knowledge_core.notes.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.vignettes.questions import QUESTIONS
from expert_knowledge_core.notes import (  # noqa: F401  (re-exported: the scripts and app modules use findings.<name>)
    CHIP_RE,
    FRAMING_LABEL,
    MIN_SENTENCE_WORDS,
    RENDER_WORDS,
    by_question,
    case_label,
    header,
    merge_groups,
    overall,
    pack_block,
    quote_pieces,
    render_sentence,
    short_quote,
    split_sentences,
)
from expert_knowledge_core.records import CASE, FINDINGS_VERSION

MIN_QUOTE_WORDS, QUOTE_RATIO = 2, 0.6  # the doc's example matches a 2-word quote at 0.67

LOWERING = re.compile(
    r"\bmore likely\b.*\bthan\b|\brather than\b|\bbetter explained by\b|\bnot\b|n't\b|\bunlikely\b",
    re.IGNORECASE,
)
RAISING = re.compile(
    r"\bsuggests?\b|\bpoints? to\b|\bconsistent with\b|\btypical of\b", re.IGNORECASE
)


# --- what is filed ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Highlight:
    chip: int
    text: str
    span: tuple[int, int]  # [start, end) in the vignette
    direction: str | None


@dataclass(frozen=True)
class Response:
    vignette_id: str
    vignette_version: int
    answers: dict[str, str]  # open questions only
    highlights: list[Highlight]
    rating: int | None
    insufficient_information: bool


def is_filed(question_id: str) -> bool:
    """Whether an answer is cut into units: open questions only. Q4's why is about a what-if,
    and the rating isn't text."""
    return QUESTIONS[question_id].kind == "open" and question_id != "Q4"


def response_from_submission(
    payload: dict[str, Any], vignette_code: str, vignette_version: int
) -> Response:
    """A frozen submission as the response to file. Only open questions are filed: Q4's why is
    about a what-if, and the rating isn't text."""
    return Response(
        vignette_id=vignette_code,
        vignette_version=vignette_version,
        answers={
            question_id: text
            for question_id, text in payload.get("answers", {}).items()
            if is_filed(question_id)
        },
        highlights=[
            Highlight(h["chip"], h["text"], (h["span"][0], h["span"][1]), h.get("direction"))
            for h in payload.get("highlights", [])
        ],
        rating=payload.get("rating"),
        insufficient_information=bool(payload.get("insufficient_information", False)),
    )


# --- step 2: sentences, chips, quotes ----------------------------------------------------------


def _words(text: str) -> int:
    return len(text.split())


def _norm(token: str) -> str:
    return token.lower().strip(" .,;:!?\"'“”()")


def match_in_text(piece: str, text: str) -> tuple[int, int, float] | None:
    """Where `piece` is in `text`: exact (case-insensitive) first, then the best word window with
    difflib ratio >= QUOTE_RATIO. None if it is not there."""
    bare = piece.strip(" .,;:!?")
    n = _words(bare)
    if n < MIN_QUOTE_WORDS:
        return None
    hit = text.lower().find(bare.lower())
    if hit >= 0:
        return hit, hit + len(bare), 1.0
    words = [(m.start(), m.end(), _norm(m.group())) for m in re.finditer(r"\S+", text)]
    target = " ".join(_norm(w) for w in bare.split())
    best: tuple[int, int, float] | None = None
    for size in {max(n - 1, 1), n, n + 1}:
        for i in range(len(words) - size + 1):
            window = words[i : i + size]
            ratio = SequenceMatcher(None, target, " ".join(w[2] for w in window)).ratio()
            if ratio >= QUOTE_RATIO and (best is None or ratio > best[2]):
                best = (window[0][0], window[-1][1], ratio)
    return best


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True if the overlap is at least half of the shorter span."""
    common = min(a[1], b[1]) - max(a[0], b[0])
    return common > 0 and common * 2 >= min(a[1] - a[0], b[1] - b[0])


def expert_highlights(highlights: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        dict(id=f"h{h.chip}", origin="expert", chip=h.chip, span=list(h.span), text=h.text,
             direction=h.direction)
        for h in highlights
    ]  # fmt: skip


def link_text(text: str, highlights: list[dict], vignette: str) -> tuple[list[str], str | None]:
    """Rules 1-3 for one sentence: its chips, else its quotes that match a highlight, else its
    quotes that match only the vignette (a new implicit highlight is appended to `highlights`).
    Returns (targets, assigned_by); ([], None) when nothing matched."""
    targets: list[str] = [f"h{n}" for n in dict.fromkeys(map(int, CHIP_RE.findall(text)))]
    if targets:
        return targets, "chip"
    for piece in quote_pieces(text):
        hit = match_in_text(piece, vignette)
        if hit is None:
            continue
        span = (hit[0], hit[1])
        found = [h["id"] for h in highlights if _overlaps(span, tuple(h["span"]))]
        if not found:
            new = len([h for h in highlights if h["origin"] == "implicit"]) + 1
            highlights.append(
                dict(id=f"i{new}", origin="implicit", chip=None, span=list(span),
                     text=vignette[span[0] : span[1]], direction=None)
            )  # fmt: skip
            found = [f"i{new}"]
        targets += [t for t in found if t not in targets]
    return targets, "quote" if targets else None


def unresolved(sentences: list[dict]) -> list[str]:
    return [s["id"] for s in sentences if not s["targets"]]


def apply_classification(sentences: list[dict], labels: dict[str, list[str]]) -> list[str]:
    """Step 3's output into the sentences. `prev` inherits the previous sentence of the same answer.
    A sentence the classifier left out or got wrong becomes `case` (the safe target); those ids are
    returned so the report can count them."""
    fallback = []
    for i, s in enumerate(sentences):
        if s["targets"]:
            continue
        got = labels.get(s["id"])
        before = sentences[i - 1] if i else None
        prev = before if before and before["question_id"] == s["question_id"] else None
        if got == ["prev"] and prev and prev["targets"]:
            s["targets"] = list(prev["targets"])
        elif got and got != ["prev"]:
            s["targets"] = list(dict.fromkeys(got))
        else:
            s["targets"] = [CASE]
            fallback.append(s["id"])
        s["assigned_by"] = "llm"
    return fallback


# --- step 4: checks ----------------------------------------------------------------------------


def check(highlights: list[dict], sentences: list[dict]) -> list[dict]:
    """Flags only; nothing is changed. Direction patterns are crude on purpose (the expert is asked,
    a false flag costs a click)."""
    flags = []
    for h in highlights:
        mine = [s for s in sentences if h["id"] in s["targets"]]
        if h["origin"] == "expert" and not mine:
            message = f"You highlighted [{h['chip']}] but didn't say anything about it."
            flags.append(dict(kind="coverage", highlight=h["id"], message=message))
            continue
        pattern = {"toward": LOWERING, "away": RAISING}.get(h["direction"])
        if pattern:
            for s in mine:
                if pattern.search(CHIP_RE.sub("", s["text"])):
                    word = "toward" if h["direction"] == "toward" else "away from"
                    flags.append(dict(kind="direction", highlight=h["id"], sentence=s["id"],
                                      message=f"You marked [{h['chip']}] as pointing {word} ADHD, "
                                      f"but in {s['question_id']} you wrote: {s['text'].strip()} "
                                      "Keep, change, or mark unclear?"))  # fmt: skip
                    break
    return flags


# --- step 6/7: units and the text that is embedded ---------------------------------------------


def build_units(rec: dict) -> list[dict]:
    """One fragment unit per highlight that has sentences, one case unit. I1 = header + the unit's
    sentences, each question's sentences prefixed with the question label; I3 adds the patient's
    words after the header. Highlights cited together become each other's `context`."""
    meta, sents = rec["meta"], rec["sentences"]
    by_id = {h["id"]: h for h in rec["highlights"]}
    targeted: dict[str, list[dict]] = {}
    context: dict[str, list[str]] = {}
    for s in sents:
        for t in s["targets"]:
            targeted.setdefault(t, []).append(s)
        cited = [t for t in s["targets"] if t != CASE]
        for t in cited:
            for other in cited:
                if other != t and other not in context.setdefault(t, []):
                    context[t].append(other)
    units = []
    for t in [h["id"] for h in rec["highlights"] if h["id"] in targeted] + (
        [CASE] if CASE in targeted else []
    ):
        h = by_id.get(t)
        unit = dict(
            id=f"{rec['session_id']}:{rec['vignette_id']}:{t}:1",
            kind="case" if t == CASE else "fragment",
            highlight=None if t == CASE else t,
            direction=h["direction"] if h else None,
            sentences=[s["id"] for s in targeted[t]],
            context=context.get(t, []),
        )
        lines = by_question(targeted[t], rec["highlights"])
        head = header(meta, unit)
        # What a reviewer reads, and the tail of what is embedded: the same sentences either way.
        unit["body"] = "\n".join(lines)
        unit["i1"] = "\n".join([head, *lines])
        unit["i3"] = "\n".join([head, f'Patient: "{h["text"]}"', *lines]) if h else unit["i1"]
        units.append(unit)
    return units


def record_from_lines(
    resp: Response, lines: dict[str, list[dict]], highlights: list[dict], session_id: str,
    expert_id: str, role: str | None, framing: str, population: str,
) -> dict:  # fmt: skip
    """Steps 6-7 from answers whose lines were already linked (the proofread check): each line is
    cut into sentences, and each sentence takes its line's targets. Nothing is linked again.
    `lines` holds, per question, [{text, targets, assigned_by}]; `resp.answers` says which
    questions are filed."""
    sentences: list[dict[str, Any]] = []
    for qid in sorted(resp.answers):
        offset, idx = 0, 0
        for line in lines.get(qid, []):
            text = line["text"]
            for a, b in split_sentences(text):
                idx += 1
                sentences.append(
                    dict(id=f"{qid}.{idx}", question_id=qid, idx=idx,
                         span=[offset + a, offset + b], text=text[a:b],
                         targets=list(line["targets"]), assigned_by=line["assigned_by"])
                )  # fmt: skip
            offset += len(text) + 1
    rec: dict[str, Any] = dict(
        version=FINDINGS_VERSION, session_id=session_id, expert_id=expert_id,
        vignette_id=resp.vignette_id, vignette_version=resp.vignette_version,
        meta=dict(role=role, framing=framing, population=population, rating=resp.rating,
                  insufficient=resp.insufficient_information),
        highlights=[dict(h) for h in highlights], sentences=sentences, fallback=[],
    )  # fmt: skip
    rec["flags"] = check(rec["highlights"], sentences)
    rec["units"] = build_units(rec)
    return rec
