"""Chip answers -> fragment units (steps 2, 4, 6, 7, 9 of docs/new-chips-knowledge.md). No models.

Records are plain dicts (JSON in, JSON out). One record per response:
  highlights  [{id h1|i1, origin expert|implicit, chip, span, text, direction}]
  sentences   [{id Q1.3, question_id, idx, span, text, targets [h1.. | i1.. | case], assigned_by}]
  units       [{id, kind fragment|case, highlight, direction, sentences, context, body, i1, i3}]
  flags       checks that only flag (coverage, direction vs text)
Step 3 (the classifier, ids only) happens outside this module; `apply_classification` takes its
output. Sentence splitting and quote matching are written here because the B1 helpers in
app.elicitation.units are tuned to other inputs (sentence starts, a fixed 0.8 ratio).

This is the one copy of the logic: the web application's worker uses it, and so do the scripts
(scripts/elicitation/chip_findings.py re-exports it). `assign` and `build_record` take anything
shaped like `Response`, so the scripts' own ChipResponse works too.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.assignments.answers import CHIP_RE
from app.vignettes.questions import QUESTIONS

FRAMING_LABEL = {"email": "email", "forum_post": "forum post", "personal_journal": "journal entry"}

FINDINGS_VERSION = 1
MIN_SENTENCE_WORDS = 4  # shorter sentences ("Hard to say.") join the previous one
MIN_QUOTE_WORDS, QUOTE_RATIO = 2, 0.6  # the doc's example matches a 2-word quote at 0.67
RENDER_WORDS = 8  # a chip is rendered as «its first 8 words…»
CASE = "case"

_DQUOTE = re.compile(r'"([^"]+)"|“([^”]+)”')
_SQUOTE = re.compile(r"(?<!\w)'([^'\n]{4,80})'(?!\w)")
_END = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"”’]))\s+")
_ABBREV = ("e.g.", "i.e.", "vs.", "etc.", "approx.", "hx.", "dr.", "r/o.")
_LIST_NUMBER = re.compile(r"(?:^|\s)\(?\d{1,2}[.)]$")
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
            if QUESTIONS[question_id].kind == "open" and question_id != "Q4"
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


def _quote_spans(text: str) -> list[tuple[int, int, str]]:
    found = [(m.start(), m.end(), m.group(1) or m.group(2)) for m in _DQUOTE.finditer(text)]
    found += [(m.start(), m.end(), m.group(1)) for m in _SQUOTE.finditer(text)]
    return sorted(found)


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans of an answer. Never splits inside a quotation, after an abbreviation or after
    a list number; sentences under MIN_SENTENCE_WORDS words join their neighbour."""
    inside = [(s, e) for s, e, _ in _quote_spans(text)]
    cuts, start = [], 0
    for m in _END.finditer(text):
        head = text[start : m.start()]
        if any(s < m.start() < e for s, e in inside):
            continue
        if head.lower().endswith(_ABBREV) or _LIST_NUMBER.search(head):
            continue
        cuts.append((start, m.start()))
        start = m.end()
    cuts.append((start, len(text)))
    spans = [(a, b) for a, b in cuts if text[a:b].strip()]
    merged: list[tuple[int, int]] = []
    for a, b in spans:
        if merged and _words(text[a:b]) < MIN_SENTENCE_WORDS:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    if len(merged) > 1 and _words(text[slice(*merged[0])]) < MIN_SENTENCE_WORDS:
        merged[1] = (merged[0][0], merged[1][1])
        merged.pop(0)
    return merged


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


def _quote_pieces(sentence: str) -> list[str]:
    pieces = []
    for *_, quote in _quote_spans(sentence):
        pieces += [p for p in re.split(r"\.\.\.|…", quote) if p.strip()]
    return pieces


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True if the overlap is at least half of the shorter span."""
    common = min(a[1], b[1]) - max(a[0], b[0])
    return common > 0 and common * 2 >= min(a[1] - a[0], b[1] - b[0])


def assign(resp: Response, vignette: str) -> tuple[list[dict], list[dict]]:
    """Rules 1-3 of the doc: chips, then quotes matching a highlight, then quotes matching only the
    vignette (an implicit highlight). Sentences left over have no targets and `assigned_by` None."""
    highlights: list[dict[str, Any]] = [
        dict(id=f"h{h.chip}", origin="expert", chip=h.chip, span=list(h.span), text=h.text,
             direction=h.direction)
        for h in resp.highlights
    ]  # fmt: skip
    sentences: list[dict[str, Any]] = []
    for qid in sorted(resp.answers):
        answer = resp.answers[qid]
        for idx, (a, b) in enumerate(split_sentences(answer), 1):
            text = answer[a:b]
            targets: list[str] = [f"h{n}" for n in dict.fromkeys(map(int, CHIP_RE.findall(text)))]
            by = "chip" if targets else None
            if not targets:
                for piece in _quote_pieces(text):
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
                by = "quote" if targets else None
            sentences.append(
                dict(id=f"{qid}.{idx}", question_id=qid, idx=idx, span=[a, b], text=text,
                     targets=targets, assigned_by=by)
            )  # fmt: skip
    return highlights, sentences


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


def short_quote(text: str, words: int = RENDER_WORDS) -> str:
    parts = text.split()
    return "«" + " ".join(parts[:words]) + ("…" if len(parts) > words else "") + "»"


def render_sentence(text: str, highlights: list[dict]) -> str:
    """Chips as «first 8 words…», so the sentence reads on its own."""
    by_chip = {h["chip"]: h for h in highlights if h["chip"]}
    return CHIP_RE.sub(lambda m: short_quote(by_chip[int(m.group(1))]["text"]), text).strip()


def _by_question(sentences: list[dict], highlights: list[dict]) -> list[str]:
    lines: list[tuple[str, list[str]]] = []
    for s in sentences:
        if not lines or lines[-1][0] != s["question_id"]:
            lines.append((s["question_id"], []))
        lines[-1][1].append(render_sentence(s["text"], highlights))
    return [f"{q}: {' '.join(parts)}" for q, parts in lines]


def overall(meta: dict) -> str:
    if meta["insufficient"]:
        return "overall: insufficient information"
    return f"overall {meta['rating']}/5" if meta["rating"] is not None else "no overall rating"


def case_label(meta: dict) -> str:
    article = "an" if meta["population"][0] in "aeiou" else "a"
    return f"{article} {meta['population']}'s {FRAMING_LABEL[meta['framing']]}"


def header(meta: dict, unit: dict) -> str:
    who = f"Clinician ({meta['role']})" if meta.get("role") else "Clinician"
    parts = [f"{who} on {case_label(meta)}"]
    if unit["kind"] == "case":
        parts.append("case-level points")
    elif unit["direction"]:
        parts.append(f"fragment marked: {unit['direction']}")
    return " · ".join([*parts, overall(meta)])


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
        lines = _by_question(targeted[t], rec["highlights"])
        head = header(meta, unit)
        # What a reviewer reads, and the tail of what is embedded: the same sentences either way.
        unit["body"] = "\n".join(lines)
        unit["i1"] = "\n".join([head, *lines])
        unit["i3"] = "\n".join([head, f'Patient: "{h["text"]}"', *lines]) if h else unit["i1"]
        units.append(unit)
    return units


def build_record(
    resp: Response, vignette: str, session_id: str, expert_id: str, role: str | None,
    framing: str, population: str, labels: dict[str, list[str]] | None = None,
) -> dict:  # fmt: skip
    """Steps 2-7 for one response. `labels` is the classifier's output (None: none needed)."""
    highlights, sentences = assign(resp, vignette)
    left = unresolved(sentences)
    if left and labels is None:
        raise ValueError(f"{len(left)} sentences need the classifier: {left}")
    fallback = apply_classification(sentences, labels or {})
    rec = dict(
        version=FINDINGS_VERSION, session_id=session_id, expert_id=expert_id,
        vignette_id=resp.vignette_id, vignette_version=resp.vignette_version,
        meta=dict(role=role, framing=framing, population=population, rating=resp.rating,
                  insufficient=resp.insufficient_information),
        highlights=highlights, sentences=sentences, fallback=fallback,
    )  # fmt: skip
    rec["flags"] = check(highlights, sentences)
    rec["units"] = build_units(rec)
    return rec


# --- step 9: packing ---------------------------------------------------------------------------


def merge_groups(units_by_id: dict[str, dict], unit_ids: list[str]) -> list[list[str]]:
    """Group unit ids (one session and vignette each) that share a sentence, transitively. Groups
    and members keep the order of first appearance in `unit_ids`."""
    groups: list[list[str]] = []
    for uid in unit_ids:
        mine = set(units_by_id[uid]["sentences"])
        hit = [g for g in groups if any(mine & set(units_by_id[m]["sentences"]) for m in g)]
        if not hit:
            groups.append([uid])
            continue
        hit[0].append(uid)
        for g in hit[1:]:
            hit[0].extend(g)
            groups.remove(g)
    return groups


def pack_block(rec: dict, unit_ids: list[str]) -> str:
    """The note the generator reads: case line, the patient's words with the expert's toggles, the
    expert's sentences verbatim in question order (each once), chips rendered as short quotes."""
    units = [u for u in rec["units"] if u["id"] in unit_ids]
    meta, hls = rec["meta"], rec["highlights"]
    by_id = {h["id"]: h for h in hls}
    wanted = {sid for u in units for sid in u["sentences"]}
    sents = [s for s in rec["sentences"] if s["id"] in wanted]
    words = []
    for u in units:
        h = by_id.get(u["highlight"] or "")
        if h:
            mark = f" (marked: {h['direction']})" if h["direction"] else ""
            words.append(f'"{h["text"]}"{mark}')
    who = f"clinician: {meta['role']}" if meta.get("role") else "clinician"
    lines = [f"Teaching case {rec['vignette_id']}: {case_label(meta)}; {who}; {overall(meta)}"]
    if words:
        lines.append("Patient's words: " + " · ".join(words))
    return "\n".join([*lines, "Clinician's own words:", *_by_question(sents, hls)])


# --- step 5: the expert's corrections ----------------------------------------------------------


def apply_corrections(
    rec: dict, sentences: dict[str, list[str]], directions: dict[str, str], at: str
) -> tuple[int, int]:
    """Re-files sentences and changes directions in `rec` (already validated by the caller).
    Returns (sentences moved, directions changed); changes that change nothing don't count.

    What happened is appended to `rec["corrections"]` as ids and kinds, never as text: it feeds
    the audit trail and the evaluation events. Then the flags and the units are recomputed, so the
    record is always consistent with what the expert sees.
    """
    by_sentence = {s["id"]: s for s in rec["sentences"]}
    by_highlight = {h["id"]: h for h in rec["highlights"]}
    moved = changed = 0
    for sid, targets in sentences.items():
        new = list(dict.fromkeys(targets))
        sentence = by_sentence[sid]
        if new == sentence["targets"]:
            continue
        rec["corrections"].append(
            dict(kind="sentence_moved", sentence=sid, before=sentence["targets"], after=new, at=at)
        )
        sentence["targets"], sentence["assigned_by"] = new, "expert"
        moved += 1
    for hid, direction in directions.items():
        highlight = by_highlight[hid]
        if direction == highlight["direction"]:
            continue
        flagged = any(f["kind"] == "direction" and f["highlight"] == hid for f in rec["flags"])
        rec["corrections"].append(
            dict(kind="toggle_changed", highlight=hid, before=highlight["direction"],
                 after=direction, after_flag=flagged, at=at)
        )  # fmt: skip
        highlight["direction"] = direction
        highlight["direction_changed_after_flag"] = flagged or highlight.get(
            "direction_changed_after_flag", False
        )
        changed += 1
    rec["flags"] = check(rec["highlights"], rec["sentences"])
    rec["units"] = build_units(rec)
    return moved, changed
