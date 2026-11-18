from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.assignments.answers import Direction
from app.knowledge.models import UnitStatus


class UnitSentence(BaseModel):
    id: str  # Q2.3
    question_id: str
    # How the sentence got into this unit: chip (the expert cited it), quote (it quotes the
    # patient's words), llm (the classifier filed it) or expert (moved on the check screen).
    assigned_by: str | None


class CitedTogether(BaseModel):
    """A quote cited together with the unit's own, shown beside the unit's text."""

    id: str
    text: str


class KnowledgeUnitListItem(BaseModel):
    id: UUID
    assignment_id: UUID
    vignette_code: str
    vignette_version: int
    expert_id: UUID
    expert_pseudonym: str
    ordinal: int
    review_round: int
    text: str
    # fragment (everything said about one citation) or case (about the text as a whole).
    kind: str | None
    highlight_id: str | None
    direction: Direction | None
    # The citation's words, from the vignette; None for the case unit.
    patient_words: str | None
    status: UnitStatus
    created_at: datetime
    # What is embedded: I1 (the reviewed text with its header) and I3 (I1 plus the patient's words).
    embed_text: str | None
    embed_text_combined: str | None
    sentences: list[UnitSentence]
    context: list[CitedTogether]
    framing: str | None
    # How the answer was cut. classifier is None when no sentence needed the model.
    classifier: str | None
    prompt: str | None
    findings_version: int | None


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    # question: a clinician's question, matched against the clinicians' reviewed text.
    # patient_text: a patient's text, matched against the patient words experts highlighted.
    mode: Literal["question", "patient_text"] = "question"
    k: int = Field(default=8, ge=1, le=20)


class KnowledgeHit(BaseModel):
    rank: int
    # The platform's own ranking score (reciprocal rank fusion): only good for ordering hits.
    score: float
    # Cosine between the embeddings, 0 to 1 for related texts: the number to read.
    similarity: float | None
    # Patient mode: the typed sentence that matched this unit's highlight best.
    matched_sentence: str | None
    unit: KnowledgeUnitListItem


class KnowledgeSearchResponse(BaseModel):
    hits: list[KnowledgeHit]


class UnitsRemoved(BaseModel):
    removed: int


class IndexStatus(BaseModel):
    """The BM25 refit after a removal. up_to_date also when no refit ever ran."""

    state: Literal["up_to_date", "queued", "running", "failed"]
    last_error: str | None = None  # the exception class only
