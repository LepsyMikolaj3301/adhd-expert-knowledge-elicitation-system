from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.knowledge.models import UnitStatus


class KnowledgeUnitListItem(BaseModel):
    id: UUID
    assignment_id: UUID
    vignette_code: str
    vignette_version: int
    expert_pseudonym: str
    ordinal: int
    review_round: int
    text: str
    # fragment (everything said about one citation) or case (about the text as a whole).
    kind: str | None
    direction: str | None
    # The citation's words, from the vignette; None for the case unit.
    patient_words: str | None
    status: UnitStatus
    created_at: datetime
