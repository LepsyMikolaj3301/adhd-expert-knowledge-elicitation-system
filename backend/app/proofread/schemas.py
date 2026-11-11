from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.assignments.answers import AnswerText
from app.vignettes.questions import QuestionId

LineText = Annotated[str, StringConstraints(max_length=5_000)]
TargetId = Annotated[str, StringConstraints(pattern=r"^(h\d+|i\d+|case)$")]


class AnswerLine(BaseModel):
    text: str
    # Highlight ids (h1, i1) and `case`; empty while the line still needs one.
    targets: list[str]
    # chip | quote | llm | expert, or None while unlinked.
    assigned_by: str | None


class LinkedHighlight(BaseModel):
    id: str
    # None for an implicit highlight: words the answers quote that were not cited.
    chip: int | None
    text: str
    span: tuple[int, int]
    origin: str
    direction: str | None


class ProofreadFlag(BaseModel):
    kind: str
    highlight: str
    message: str


class ProofreadFeedback(BaseModel):
    question_id: str
    comment: str


class ProofreadItem(BaseModel):
    question_id: str
    question: str
    # What the expert submitted, what proofreading proposed, and the author's current text.
    original: str
    proposed: str
    final: str
    # Whether the lines are linked to citations (every answer but Q4's why).
    linked: bool
    lines: list[AnswerLine]
    dropped: list[str]


class ProofreadView(BaseModel):
    review_round: int
    version: int
    editable: bool
    submitted_at: datetime | None
    feedback: list[ProofreadFeedback]
    highlights: list[LinkedHighlight]
    flags: list[ProofreadFlag]
    passes: dict[str, Any]
    items: list[ProofreadItem]


class ProofreadSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    # The author's text of each answer, as typed.
    answers: dict[QuestionId, AnswerText]
    # Lines the author linked by hand: per question, line text -> targets.
    overrides: dict[QuestionId, dict[LineText, list[TargetId]]] = Field(default={})
