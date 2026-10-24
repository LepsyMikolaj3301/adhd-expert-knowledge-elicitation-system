"""Semantic chunking: split where the embedding distance between neighbouring units spikes."""

import numpy as np

from app.chunking.base import (
    Chunk,
    TokenCounter,
    Unit,
    build_chunk,
    document_units,
    split_oversized,
)
from app.chunking.config import CHUNKER_VERSION, BreakpointConfig, SemanticConfig
from app.embeddings import Embedder


def breakpoint_mask(distances: np.ndarray, cfg: BreakpointConfig) -> np.ndarray:
    """True where a distance is a topic shift."""
    if len(distances) == 0:
        return np.zeros(0, dtype=bool)
    if cfg.type == "percentile":
        return distances > np.percentile(distances, cfg.amount)
    if cfg.type == "std_dev":
        return distances > distances.mean() + cfg.amount * distances.std()
    if cfg.type == "interquartile":
        q1, q3 = np.percentile(distances, [25, 75])
        return distances > distances.mean() + cfg.amount * (q3 - q1)
    gradient = np.gradient(distances)  # gradient: sharp rises, good for homogeneous text
    return gradient > np.percentile(gradient, cfg.amount)


class SemanticChunker:
    name = "semantic"
    version = CHUNKER_VERSION

    def __init__(self, cfg: SemanticConfig, embedder: Embedder, count: TokenCounter) -> None:
        self.cfg = cfg
        self.embedder = embedder
        self.count = count

    def chunk(self, document: dict) -> list[Chunk]:
        cfg = self.cfg
        units: list[Unit] = []
        for unit in document_units(document, cfg.sentence_split):
            units += split_oversized(unit, cfg.max_tokens, self.count)
        if not units:
            return []
        tokens = [self.count(u.text) for u in units]

        # after[i]: distance between unit i and i+1; hard[i]: a section boundary sits there.
        after = self._distances(units)
        hard = np.array(
            [
                cfg.respect_sections and a.section_id != b.section_id
                for a, b in zip(units, units[1:], strict=False)
            ],
            dtype=bool,
        )
        soft = ~hard
        shift = np.zeros(len(after), dtype=bool)
        shift[soft] = breakpoint_mask(after[soft], cfg.breakpoint)

        chunks: list[tuple[int, int]] = []  # [start, end) unit ranges
        start = 0
        for i in range(len(after)):
            if hard[i] or shift[i]:
                chunks.append((start, i + 1))
                start = i + 1
        chunks.append((start, len(units)))

        chunks = [piece for span in chunks for piece in self._split_large(span, after, tokens)]
        chunks = self._merge_small(chunks, units, after, tokens)

        result = []
        for n, (a, b) in enumerate(chunks):
            gap = float(after[a - 1]) if a > 0 else None
            result.append(build_chunk(n, units[a:b], self.count, cfg.contextual_header, gap))
        return result

    def _distances(self, units: list[Unit]) -> np.ndarray:
        """Cosine distance of each unit to the next, on buffered texts (neighbours within the
        same section, so context never leaks over a heading)."""
        buffer = self.cfg.buffer_size
        texts = []
        for i, unit in enumerate(units):
            lo, hi = max(0, i - buffer), min(len(units), i + buffer + 1)
            near = [
                u.text
                for u in units[lo:hi]
                if not self.cfg.respect_sections or u.section_id == unit.section_id
            ]
            texts.append(" ".join(near))
        vectors = self.embedder.embed(texts)
        return 1.0 - np.einsum("ij,ij->i", vectors[:-1], vectors[1:])

    def _split_large(
        self, span: tuple[int, int], after: np.ndarray, tokens: list[int]
    ) -> list[tuple[int, int]]:
        """Recursively cut an over-long chunk at its largest internal distance."""
        a, b = span
        if sum(tokens[a:b]) <= self.cfg.max_tokens or b - a < 2:
            return [span]
        cut = a + int(np.argmax(after[a : b - 1])) + 1
        return self._split_large((a, cut), after, tokens) + self._split_large(
            (cut, b), after, tokens
        )

    def _merge_small(
        self,
        chunks: list[tuple[int, int]],
        units: list[Unit],
        after: np.ndarray,
        tokens: list[int],
    ) -> list[tuple[int, int]]:
        cfg = self.cfg

        def size(span: tuple[int, int]) -> int:
            return sum(tokens[span[0] : span[1]])

        def same_scope(x: tuple[int, int], y: tuple[int, int]) -> bool:
            n = cfg.merge_scope_level
            return units[x[0]].path[:n] == units[y[0]].path[:n]

        while True:
            small = sorted(
                (i for i, span in enumerate(chunks) if size(span) < cfg.min_tokens),
                key=lambda i: size(chunks[i]),
            )
            for i in small:
                options = []  # (distance of the boundary, index of the left chunk of the pair)
                if i > 0:
                    options.append((float(after[chunks[i][0] - 1]), i - 1))
                if i + 1 < len(chunks):
                    options.append((float(after[chunks[i][1] - 1]), i))
                options = [
                    (d, left)
                    for d, left in options
                    if same_scope(chunks[left], chunks[left + 1])
                    and size(chunks[left]) + size(chunks[left + 1]) <= cfg.max_tokens
                ]
                if options:
                    _, left = min(options)
                    chunks[left : left + 2] = [(chunks[left][0], chunks[left + 1][1])]
                    break
            else:
                return chunks
