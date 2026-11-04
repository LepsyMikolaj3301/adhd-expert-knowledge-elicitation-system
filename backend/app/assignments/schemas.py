"""One view per audience, told apart by `audience`, so hidden data has no field to leak through."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.assignments.answers import AnswerPayload
from app.assignments.states import State
from app.vignettes.questions import QuestionKind
from app.vignettes.schemas import Framing


class QuestionView(BaseModel):
    id: str
    kind: QuestionKind
    text: str
    # Different words needed to be accepted, so the screen can show a counter. For Q4: its "why".
    min_words: int | None = None
    # Q4 only: the exact wording of its parts.
    wording: dict[str, Any] | None = None


class ExpertVignette(BaseModel):
    code: str
    version: int
    text: str
    framing: Framing
    word_count: int
    content_hash: str
    # Only the questions the expert may see now: Q4-Q6 are absent until the gate is passed.
    questions: list[QuestionView]


class PeerVignette(BaseModel):
    code: str
    version: int
    text: str
    framing: Framing
    word_count: int


class DraftView(BaseModel):
    version: int
    payload: AnswerPayload
    updated_at: datetime


class _AssignmentBase(BaseModel):
    id: UUID
    state: State
    allowed_actions: list[str]
    updated_at: datetime


class ExpertAssignment(_AssignmentBase):
    audience: Literal["expert"] = "expert"
    vignette: ExpertVignette
    draft: DraftView | None
    gate_passed_at: datetime | None
    started_at: datetime | None
    submitted_at: datetime | None


class AdminAssignment(_AssignmentBase):
    audience: Literal["admin"] = "admin"
    expert_id: UUID
    expert_pseudonym: str
    vignette_code: str
    vignette_version: int
    vignette_version_id: UUID
    required_approvals: int
    gate_passed_at: datetime | None
    started_at: datetime | None
    submitted_at: datetime | None


class PeerAssignment(_AssignmentBase):
    audience: Literal["peer"] = "peer"
    vignette: PeerVignette


AssignmentView = Annotated[
    ExpertAssignment | AdminAssignment | PeerAssignment, Field(discriminator="audience")
]


class AssignmentSummary(BaseModel):
    id: UUID
    state: State
    allowed_actions: list[str]
    # A background job is working on it, so the state is about to change: worth polling.
    job_running: bool
    vignette_code: str
    vignette_version: int
    expert_pseudonym: str
    updated_at: datetime


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expert_ids: list[UUID] = Field(min_length=1, max_length=500)


class DraftSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The version this save is based on. If it's stale, another tab has saved since.
    version: int
    payload: AnswerPayload


class DraftSaved(BaseModel):
    version: int
    updated_at: datetime


class SubmissionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assignment_id: UUID
    payload_format: int
    vignette_hash: str
    submitted_at: datetime
    payload: dict[str, Any]


class EventAdminView(BaseModel):
    audience: Literal["admin"] = "admin"
    action: str
    from_state: str | None
    to_state: str | None
    at: datetime
    actor_id: UUID | None
    meta: dict[str, Any]


class EventAuthorView(BaseModel):
    """Who did it is reduced to a role, so reviewers stay anonymous to the author."""

    audience: Literal["author"] = "author"
    action: str
    from_state: str | None
    to_state: str | None
    at: datetime
    actor: Literal["you", "admin", "reviewer", "system"]


EventView = Annotated[EventAdminView | EventAuthorView, Field(discriminator="audience")]
