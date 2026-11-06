"""Chip answers -> fragment units (steps 2, 4, 6, 7, 9 of docs/new-chips-knowledge.md). No models.

The logic lives in backend/app/knowledge/findings.py, which the web application's worker also uses;
this module only keeps the scripts' import (`import chip_findings as cf`) working.
"""

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
    assign,
    build_record,
    build_units,
    case_label,
    check,
    header,
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
