"""Notes: what the generator reads, cut from a findings record (notes/new-chips-knowledge.md, steps 2
and 9). Pure functions over plain dicts (`records.Record`), no models, no database.

Moved here from app.knowledge.findings so that the web application's ingestion and the retrieval
package use one copy: the text that was embedded and the text that is packed must stay in step.
"""

import re
from collections.abc import Mapping
from typing import Any

from expert_knowledge_core.records import CASE

CHIP_RE = re.compile(r"⟦h(\d+)⟧")  # a citation chip inside an answer

FRAMING_LABEL = {"email": "email", "forum_post": "forum post", "personal_journal": "journal entry"}

MIN_SENTENCE_WORDS = 4  # shorter sentences ("Hard to say.") join the previous one
RENDER_WORDS = 8  # a chip is rendered as «its first 8 words…»

_DQUOTE = re.compile(r'"([^"]+)"|“([^”]+)”')
_SQUOTE = re.compile(r"(?<!\w)'([^'\n]{4,80})'(?!\w)")
_END = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"”’]))\s+")
_ABBREV = ("e.g.", "i.e.", "vs.", "etc.", "approx.", "hx.", "dr.", "r/o.")
_LIST_NUMBER = re.compile(r"(?:^|\s)\(?\d{1,2}[.)]$")

__all__ = [
    "CASE",
    "CHIP_RE",
    "FRAMING_LABEL",
    "MIN_SENTENCE_WORDS",
    "RENDER_WORDS",
    "by_question",
    "case_label",
    "header",
    "merge_groups",
    "overall",
    "pack_block",
    "quote_pieces",
    "quote_spans",
    "render_sentence",
    "short_quote",
    "split_sentences",
]


# --- sentences ---------------------------------------------------------------------------------


def _words(text: str) -> int:
    return len(text.split())


def quote_spans(text: str) -> list[tuple[int, int, str]]:
    found = [(m.start(), m.end(), m.group(1) or m.group(2)) for m in _DQUOTE.finditer(text)]
    found += [(m.start(), m.end(), m.group(1)) for m in _SQUOTE.finditer(text)]
    return sorted(found)


def quote_pieces(sentence: str) -> list[str]:
    pieces = []
    for *_, quote in quote_spans(sentence):
        pieces += [p for p in re.split(r"\.\.\.|…", quote) if p.strip()]
    return pieces


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans of an answer. A line break always ends a sentence (the proofread answers
    have one sentence per line). Within a line, never splits inside a quotation, after an
    abbreviation or after a list number; sentences under MIN_SENTENCE_WORDS words join their
    neighbour on the same line."""
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in text.split("\n"):
        spans += [(offset + a, offset + b) for a, b in _split_line(line)]
        offset += len(line) + 1
    return spans


def _split_line(text: str) -> list[tuple[int, int]]:
    inside = [(s, e) for s, e, _ in quote_spans(text)]
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


# --- rendering ---------------------------------------------------------------------------------


def short_quote(text: str, words: int = RENDER_WORDS) -> str:
    parts = text.split()
    return "«" + " ".join(parts[:words]) + ("…" if len(parts) > words else "") + "»"


def render_sentence(text: str, highlights: list[dict]) -> str:
    """Chips as «first 8 words…», so the sentence reads on its own."""
    by_chip = {h["chip"]: h for h in highlights if h["chip"]}
    return CHIP_RE.sub(lambda m: short_quote(by_chip[int(m.group(1))]["text"]), text).strip()


def by_question(sentences: list[dict], highlights: list[dict]) -> list[str]:
    """One line per run of sentences of the same question: `Q2: first second`."""
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


# --- step 9: packing ---------------------------------------------------------------------------


def merge_groups(
    units_by_id: Mapping[str, Mapping[str, Any]], unit_ids: list[str]
) -> list[list[str]]:
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


def pack_block(rec: Mapping[str, Any], unit_ids: list[str]) -> str:
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
    return "\n".join([*lines, "Clinician's own words:", *by_question(sents, hls)])
