"""Grammar, spelling and punctuation fixes from a self-hosted LanguageTool server.

LanguageTool is rule-based, so the same text and server version always give the same corrections.
Only some kinds of rules are applied, and each one only with its first suggestion:

- grammar, punctuation, casing, confused words, compounds: always;
- spelling: only when the suggestion is a much more common word than the one written (wordfreq), so
  "teh" and "recieve" are fixed but British spellings are not; never for words in the vignette
  (the patient's own words) or for the clinical terms in CLINICAL_TERMS;
- style, redundancy, typography (curly quotes would hide the expert's quotations): never.

Chips (`⟦hN⟧`) are sent as markup that LanguageTool reads as the quoted words of the citation, so
it checks the sentence as it reads, and a chip is never edited or moved.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from wordfreq import zipf_frequency

from app.assignments.answers import CHIP_RE
from app.settings import settings

APPLIED_CATEGORIES = frozenset(
    {"GRAMMAR", "PUNCTUATION", "CASING", "CONFUSED_WORDS", "COMPOUNDING", "TYPOS"}
)
SPELLING_CATEGORY = "TYPOS"
# A spelling fix must be at least this much more common than the word written (zipf scale: one
# step is ten times as common). "teh" -> "the" is 4.7, "behaviour" -> "behavior" only 0.3.
SPELLING_GAP = 1.4
# Rare in general English, so a spelling checker "corrects" them, but right in this field.
CLINICAL_TERMS = frozenset(
    {
        "adhd", "add", "asd", "ocd", "ptsd", "bpd", "dsm", "icd", "hyperfocus", "hyperfocused",
        "hyperfocusing", "stimming", "stim", "stims", "dysregulation", "dysregulated",
        "neurodivergent", "neurodivergence", "neurotypical", "comorbid", "comorbidity",
        "comorbidities", "anhedonia", "anhedonic", "dysthymia", "hypomania", "hypomanic",
        "psychoeducation", "inattentive", "hyperactivity", "impulsivity", "executive",
        "methylphenidate", "lisdexamfetamine", "atomoxetine", "guanfacine", "ritalin", "adderall",
        "elvanse", "concerta", "rumination", "ruminating", "masking", "rsd", "dopamine",
    }
)  # fmt: skip
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")


@dataclass
class Checked:
    text: str
    edits: int = 0
    version: str | None = None
    skipped: list[str] = field(default_factory=list)  # rule ids seen but not applied


def vocabulary(text: str) -> set[str]:
    return {word.lower() for word in _WORD.findall(text)}


def annotate(text: str, quotes: dict[int, str]) -> dict[str, Any]:
    """LanguageTool's annotated text: chips become markup read as their quoted words."""
    parts: list[dict[str, str]] = []
    last = 0
    for match in CHIP_RE.finditer(text):
        if match.start() > last:
            parts.append({"text": text[last : match.start()]})
        quote = quotes.get(int(match.group(1)), "this")
        parts.append({"markup": match.group(), "interpretAs": f'"{quote}"'})
        last = match.end()
    if last < len(text):
        parts.append({"text": text[last:]})
    return {"annotation": parts}


def _code_points(text: str, utf16_offset: int) -> int:
    """LanguageTool (Java) counts UTF-16 units; Python counts code points."""
    units = 0
    for index, char in enumerate(text):
        if units >= utf16_offset:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
    return len(text)


async def ask(text: str, quotes: dict[int, str]) -> dict[str, Any]:
    """One /v2/check call. Tests replace this function."""
    async with httpx.AsyncClient(
        base_url=settings.languagetool_url, timeout=settings.languagetool_timeout
    ) as client:
        response = await client.post(
            "/v2/check",
            data={
                "language": settings.languagetool_language,
                "data": json.dumps(annotate(text, quotes)),
            },
        )
        response.raise_for_status()
        return response.json()


def spelling_fix_wanted(word: str, replacement: str, protected: set[str]) -> bool:
    bare = word.strip().lower()
    if not bare or bare in protected or bare in CLINICAL_TERMS:
        return False
    written = zipf_frequency(bare, "en")
    return written == 0 or zipf_frequency(replacement, "en") - written >= SPELLING_GAP


def _wanted(match: dict[str, Any], word: str, protected: set[str]) -> bool:
    category = match.get("rule", {}).get("category", {}).get("id", "")
    if category not in APPLIED_CATEGORIES or not match.get("replacements"):
        return False
    if category == SPELLING_CATEGORY:
        return spelling_fix_wanted(word, match["replacements"][0]["value"], protected)
    return True


def apply(text: str, reply: dict[str, Any], protected: set[str]) -> Checked:
    """The reply's corrections applied to `text`, from the end backwards so that earlier offsets
    stay right. Corrections that overlap each other or touch a chip are left out."""
    chips = [(m.start(), m.end()) for m in CHIP_RE.finditer(text)]
    checked = Checked(text=text, version=reply.get("software", {}).get("version"))
    spans = []
    for match in reply.get("matches", []):
        start = _code_points(text, match["offset"])
        end = _code_points(text, match["offset"] + match["length"])
        spans.append((start, end, match))
    result, edge = text, len(text) + 1
    for start, end, match in sorted(spans, key=lambda item: item[0], reverse=True):
        if end > edge or any(start < b and a < end for a, b in chips):
            continue
        if not _wanted(match, text[start:end], protected):
            checked.skipped.append(match.get("rule", {}).get("id", "?"))
            continue
        result = result[:start] + match["replacements"][0]["value"] + result[end:]
        checked.edits += 1
        edge = start
    checked.text = result
    return checked


async def check(text: str, quotes: dict[int, str], protected: set[str]) -> Checked:
    if not text.strip():
        return Checked(text=text)
    return apply(text, await ask(text, quotes), protected)
