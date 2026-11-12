"""Chip answers -> fragment units (steps 2, 4, 6, 7, 9 of docs/new-chips-knowledge.md). No models.

The logic the web application's worker uses lives in backend/app/knowledge/findings.py. This
module re-exports it for the scripts (`import chip_findings as cf`) and adds what only they need:
filing a whole response in one go (`assign`, `build_record`), without the proofread check's lines.
`assign` and `build_record` take anything shaped like `Response`, so the scripts' own ChipResponse
works too.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from app.knowledge.findings import (  # noqa: F401
    CASE,
    FINDINGS_VERSION,
    LOWERING,
    MIN_QUOTE_WORDS,
    MIN_SENTENCE_WORDS,
    QUOTE_RATIO,
    RAISING,
    RENDER_WORDS,
    Highlight,
    Response,
    apply_classification,
    build_units,
    case_label,
    check,
    expert_highlights,
    header,
    link_text,
    match_in_text,
    merge_groups,
    overall,
    pack_block,
    render_sentence,
    response_from_submission,
    short_quote,
    split_sentences,
    unresolved,
)


class ResponseLike(Protocol):
    """What `assign` and `build_record` read from a response: `Response`, or a pydantic response
    of the elicitation schema (chips_schema.py)."""

    @property
    def vignette_id(self) -> str: ...
    @property
    def vignette_version(self) -> int: ...
    @property
    def answers(self) -> Mapping[Any, str]: ...
    @property
    def highlights(self) -> Sequence[Any]: ...
    @property
    def rating(self) -> int | None: ...
    @property
    def insufficient_information(self) -> bool: ...


def assign(resp: ResponseLike, vignette: str) -> tuple[list[dict], list[dict]]:
    """Rules 1-3 of the doc: chips, then quotes matching a highlight, then quotes matching only the
    vignette (an implicit highlight). Sentences left over have no targets and `assigned_by` None."""
    highlights = expert_highlights(resp.highlights)
    sentences: list[dict[str, Any]] = []
    for qid in sorted(resp.answers):
        answer = resp.answers[qid]
        for idx, (a, b) in enumerate(split_sentences(answer), 1):
            text = answer[a:b]
            targets, by = link_text(text, highlights, vignette)
            sentences.append(
                dict(id=f"{qid}.{idx}", question_id=qid, idx=idx, span=[a, b], text=text,
                     targets=targets, assigned_by=by)
            )  # fmt: skip
    return highlights, sentences


def build_record(
    resp: ResponseLike, vignette: str, session_id: str, expert_id: str, role: str | None,
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
