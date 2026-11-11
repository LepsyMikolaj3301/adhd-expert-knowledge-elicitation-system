"""Dropping text nobody can read ("afdoafgja qwrtz"). Deterministic: a word list, no model.

A word is unknown when it has at least MIN_LETTERS letters, wordfreq has never seen it in English,
it is not in the vignette, and it is not a short all-caps acronym. A sentence is dropped when at
least half of its words are unknown. Chips, numbers and short words never count either way.
"""

import re

from wordfreq import zipf_frequency

from app.assignments.answers import CHIP_RE

MIN_LETTERS = 3
UNKNOWN_SHARE = 0.5
ACRONYM_LETTERS = 5
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
# Finer than findings.split_sentences on purpose: a short garbage sentence must not hide inside
# the sentence before it.
_PIECE = re.compile(r"(?<=[.!?])[ \t]+")


def unknown(word: str, vignette_words: set[str]) -> bool:
    if len(word) < MIN_LETTERS or word.lower() in vignette_words:
        return False
    if word.isupper() and len(word) <= ACRONYM_LETTERS:
        return False
    return zipf_frequency(word, "en") == 0


def is_garbage(sentence: str, vignette_words: set[str]) -> bool:
    words = [w for w in _WORD.findall(CHIP_RE.sub(" ", sentence)) if len(w) >= MIN_LETTERS]
    if not words:
        return False
    bad = sum(unknown(word, vignette_words) for word in words)
    return bad / len(words) >= UNKNOWN_SHARE


def drop_garbage(text: str, vignette_words: set[str]) -> tuple[str, list[str]]:
    """(the text without its garbage sentences, the sentences dropped). Line breaks are kept;
    a line left empty goes."""
    lines, dropped = [], []
    for line in text.split("\n"):
        kept = []
        for piece in _PIECE.split(line):
            piece = piece.strip()
            if piece:
                (dropped if is_garbage(piece, vignette_words) else kept).append(piece)
        if kept:
            lines.append(" ".join(kept))
    return "\n".join(lines), dropped
