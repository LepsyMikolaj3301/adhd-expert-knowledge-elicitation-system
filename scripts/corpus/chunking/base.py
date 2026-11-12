"""Chunker interface and the pieces every chunking method shares."""

import re
from dataclasses import dataclass, field
from typing import Protocol

from tokenizers import Tokenizer


@dataclass
class Unit:
    """Smallest piece a chunker moves around: a sentence, list item or table."""

    text: str
    section_id: str
    path: list[str]
    block: int  # running block number in the document, equal for sentences of one paragraph
    block_type: str
    page: int | None


@dataclass
class Chunk:
    index: int
    text: str
    contextual_text: str
    heading_path: list[str]
    section_ids: list[str]
    block_types: list[str]
    pages: list[int]
    n_tokens: int
    n_units: int
    # Embedding distance to the previous chunk (None for the first chunk).
    breakpoint_distance: float | None = None
    extra: dict = field(default_factory=dict)


class Chunker(Protocol):
    name: str
    version: str

    def chunk(self, document: dict) -> list[Chunk]:
        """Chunk one parsed document (the JSON written by parse_raw_documents.py)."""
        ...


# --------------------------------------------------------------------------- tokens


class TokenCounter:
    """Token count with a Hugging Face tokenizer, or a word count if none is given/available."""

    def __init__(self, tokenizer: str | None) -> None:
        self.tokenizer = None
        self.name = "words"
        if tokenizer:
            try:
                self.tokenizer = Tokenizer.from_pretrained(tokenizer)
                self.name = tokenizer
            except Exception as e:
                print(f"warning: tokenizer {tokenizer!r} unavailable ({e}); counting words")

    def __call__(self, text: str) -> int:
        if self.tokenizer is None:
            return len(text.split())
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)


# --------------------------------------------------------------------------- units

# Periods that do not end a sentence; masked before splitting and restored after.
_ABBREVIATIONS = re.compile(
    r"\b(e\.g|i\.e|et al|vs|cf|Fig|Figs|Tab|Dr|Mr|Mrs|Ms|Prof|approx|no|ca)\.", re.IGNORECASE
)
_DECIMAL = re.compile(r"(?<=\d)\.(?=\d)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_MASK = "\u0000"


def split_sentences(text: str) -> list[str]:
    masked = _DECIMAL.sub(_MASK, _ABBREVIATIONS.sub(lambda m: m[0][:-1] + _MASK, text))
    parts = _SENTENCE_END.split(masked)
    return [p.replace(_MASK, ".").strip() for p in parts if p.strip()]


def document_units(document: dict, split: bool = True) -> list[Unit]:
    """Flatten the sections/blocks of a parsed document. Only paragraphs are split into
    sentences; list items and tables stay whole."""
    units: list[Unit] = []
    block_no = 0
    for section in document["sections"]:
        for block in section["blocks"]:
            text = block["text"].strip()
            if not text:
                continue
            block_no += 1
            kind = block["type"]
            pieces = split_sentences(text) if split and kind == "paragraph" else [text]
            for piece in pieces:
                units.append(
                    Unit(piece, section["id"], section["path"], block_no, kind, block.get("page"))
                )
    return units


def split_oversized(unit: Unit, max_tokens: int, count: TokenCounter) -> list[Unit]:
    """Cut a unit longer than max_tokens into word windows (tables are cut by line first)."""
    if count(unit.text) <= max_tokens:
        return [unit]
    words = unit.text.split(" ") if "\n" not in unit.text else unit.text.split("\n")
    sep = " " if "\n" not in unit.text else "\n"
    pieces: list[str] = []
    current: list[str] = []
    for word in words:
        if current and count(sep.join([*current, word])) > max_tokens:
            pieces.append(sep.join(current))
            current = []
        current.append(word)
    if current:
        pieces.append(sep.join(current))
    return [
        Unit(p, unit.section_id, unit.path, unit.block, unit.block_type, unit.page) for p in pieces
    ]


def join_units(units: list[Unit]) -> str:
    out = units[0].text
    for prev, unit in zip(units, units[1:], strict=False):
        if unit.section_id != prev.section_id:
            out += "\n\n"
        elif unit.block != prev.block:
            out += "\n"
        else:
            out += " "
        out += unit.text
    return out


def common_prefix(paths: list[list[str]]) -> list[str]:
    prefix = paths[0]
    for path in paths[1:]:
        n = 0
        while n < min(len(prefix), len(path)) and prefix[n] == path[n]:
            n += 1
        prefix = prefix[:n]
    return list(prefix)


def build_chunk(
    index: int,
    units: list[Unit],
    count: TokenCounter,
    contextual_header: bool,
    breakpoint_distance: float | None,
) -> Chunk:
    text = join_units(units)
    path = common_prefix([u.path for u in units])
    contextual = f"{' > '.join(path)}\n\n{text}" if contextual_header and path else text
    return Chunk(
        index=index,
        text=text,
        contextual_text=contextual,
        heading_path=path,
        section_ids=list(dict.fromkeys(u.section_id for u in units)),
        block_types=list(dict.fromkeys(u.block_type for u in units)),
        pages=sorted({u.page for u in units if u.page is not None}),
        n_tokens=count(text),
        n_units=len(units),
        breakpoint_distance=breakpoint_distance,
    )
