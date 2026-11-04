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
    question_id: str | None
    text: str
    status: UnitStatus
    created_at: datetime
