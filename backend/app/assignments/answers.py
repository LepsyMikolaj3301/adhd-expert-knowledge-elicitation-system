"""What an expert's answers look like, and the rules for saving and submitting them.

Saving a draft is lenient about completeness: the questions can be answered in any order and
changed until the answers are submitted. Submitting checks everything: every question asked must be
answered.
"""

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import invalid
from app.vignettes.questions import QUESTIONS, QuestionId

# CHIP_RE: a citation inside an answer, as stored (`⟦h3⟧`); the number is the citation's `chip`.
from expert_knowledge_core.notes import CHIP_RE  # noqa: F401  (also imported from here)

# 2: citations (`highlights`, `⟦hN⟧` chips) replace `quoted_fragments`, and Q1 has its new wording.
PAYLOAD_FORMAT = 2
AnswerText = Annotated[str, Field(max_length=20_000)]
ShortText = Annotated[str, Field(max_length=2_000)]
Direction = Literal["toward", "away", "neutral", "unclear"]

# How much of a citation a chip shows when it is rendered as text.
CHIP_QUOTE_WORDS = 8


class Highlight(BaseModel):
    """A passage the expert cited. Same shape as the chip fixtures (scripts/.../chips_schema.py)."""

    model_config = ConfigDict(extra="forbid")

    chip: int = Field(ge=1)
    text: ShortText = Field(min_length=1)
    # [start, end) in characters of the vignette text (code points, not the browser's UTF-16 units).
    span: tuple[int, int]
    # None only while drafting: the gate and submit require it.
    direction: Direction | None = None


class Q4Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis: ShortText | None = None
    # No default on purpose: "no answer yet" must not look like 0.
    shift: int | None = Field(default=None, ge=-2, le=2)
    toward: Literal["more_adhd", "less_adhd", "other"] | None = None
    other_explanation: ShortText | None = None


class AnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: dict[QuestionId, AnswerText] = {}
    highlights: list[Highlight] = Field(default=[], max_length=200)
    q4: Q4Answer | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    insufficient_information: bool = False


def _check_asked(payload: AnswerPayload, question_ids: list[str]) -> None:
    for question_id in payload.answers:
        if question_id not in question_ids:
            raise invalid("question_not_asked", f"{question_id} wasn't asked for this vignette.")
        if QUESTIONS[question_id].kind == "rating_1_5":
            raise invalid("answer_to_rating_question", f"{question_id} is answered with a rating.")
    if payload.q4 is not None and "Q4" not in question_ids:
        raise invalid("question_not_asked", "Q4 wasn't asked for this vignette.")
    if (payload.rating is not None or payload.insufficient_information) and (
        "Q6" not in question_ids
    ):
        raise invalid("question_not_asked", "Q6 wasn't asked for this vignette.")


def _check_highlights(highlights: list[Highlight], text: str) -> None:
    numbers = [highlight.chip for highlight in highlights]
    if numbers != list(range(1, len(numbers) + 1)):
        raise invalid("chip_numbers", "Citations must be numbered from 1.", {"chips": numbers})
    for highlight in highlights:
        start, end = highlight.span
        if not 0 <= start < end <= len(text) or text[start:end] != highlight.text:
            raise invalid(
                "highlight_not_in_vignette",
                "A citation doesn't match the vignette text.",
                {"chip": highlight.chip},
            )


def _check_citations_complete(payload: AnswerPayload) -> None:
    """Every chip points at a citation, and every citation has a direction."""
    numbers = {highlight.chip for highlight in payload.highlights}
    for question_id, answer in payload.answers.items():
        for chip in map(int, CHIP_RE.findall(answer)):
            if chip not in numbers:
                raise invalid(
                    "unknown_chip",
                    f"{question_id} cites [{chip}], which is not in your citations.",
                    {"question_id": question_id, "chip": chip},
                )
    if undirected := [h.chip for h in payload.highlights if h.direction is None]:
        raise invalid(
            "highlight_no_direction",
            "Choose a direction for each citation.",
            {"chips": undirected},
        )


def check_draft(payload: AnswerPayload, question_ids: list[str], text: str) -> None:
    _check_asked(payload, question_ids)
    _check_highlights(payload.highlights, text)


def count_words(text: str) -> int:
    """Different words, so that "test test test" counts as one. A chip is not a word."""
    return len(set(re.findall(r"\w+", CHIP_RE.sub(" ", text).lower())))


def render_chips(answer: str, highlights: list[dict[str, Any]]) -> str:
    """An answer as plain text: each chip becomes «the first words of its citation…»."""
    by_chip = {highlight["chip"]: highlight["text"] for highlight in highlights}

    def quote(match: re.Match[str]) -> str:
        words = by_chip[int(match.group(1))].split()
        cut = len(words) > CHIP_QUOTE_WORDS
        return f"«{' '.join(words[:CHIP_QUOTE_WORDS])}{'…' if cut else ''}»"

    return CHIP_RE.sub(quote, answer)


def _incomplete(message: str) -> Exception:
    return invalid("submission_incomplete", message)


def _clean_q4(payload: AnswerPayload, question_ids: list[str]) -> Q4Answer | None:
    why = payload.answers.get("Q4", "").strip()
    q4 = payload.q4
    if "Q4" not in question_ids:
        return None
    if q4 is None or q4.shift is None:
        raise _incomplete("Q4: pick a point on the scale.")
    hypothesis = (q4.hypothesis or "").strip()
    other = (q4.other_explanation or "").strip()
    if not hypothesis:
        raise _incomplete("Q4: write your working hypothesis.")
    if why and q4.shift == 0:
        raise invalid("q4_why_without_shift", "A Q4 why needs a non-zero shift.")
    if q4.toward is not None and q4.shift <= 0:
        raise invalid("toward_without_change", "A direction needs a shift of +1 or +2.")
    if (q4.toward == "other") != bool(other):
        raise invalid("other_without_name", '"Another explanation" needs a name, and only it.')
    if q4.shift > 0 and q4.toward is None:
        raise _incomplete("Q4: choose a direction.")
    if q4.shift != 0 and not why:
        raise _incomplete("Q4: explain why.")
    return Q4Answer(
        hypothesis=hypothesis, shift=q4.shift, toward=q4.toward, other_explanation=other or None
    )


def clean_submission(payload: AnswerPayload, question_ids: list[str], text: str) -> AnswerPayload:
    """Check a draft for submission and return it trimmed, or raise the first problem found."""
    _check_asked(payload, question_ids)

    answers: dict[QuestionId, str] = {}
    for question_id, answer in payload.answers.items():
        if answer.strip():
            answers[question_id] = answer.strip()

    # Every open question must have an answer. How long it is, is the expert's call.
    for question_id in question_ids:
        if QUESTIONS[question_id].kind == "open" and question_id not in answers:
            raise invalid("empty_answer", f"{question_id} needs an answer.")

    _check_highlights(payload.highlights, text)
    _check_citations_complete(payload)

    if payload.rating is not None and payload.insufficient_information:
        raise invalid("rating_conflict", 'Choose either a rating or "insufficient information".')
    if "Q6" in question_ids and payload.rating is None and not payload.insufficient_information:
        raise _incomplete("Q6 needs an answer.")

    return AnswerPayload(
        answers=answers,
        highlights=payload.highlights,
        q4=_clean_q4(payload, question_ids),
        rating=payload.rating,
        insufficient_information=payload.insufficient_information,
    )
