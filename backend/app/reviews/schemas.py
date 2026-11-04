"""One view of a unit per audience, told apart by `audience`."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.models import UnitStatus
from app.reviews.models import DecisionValue, ReviewStage


class DecisionView(BaseModel):
    reviewer_id: UUID
    reviewer_pseudonym: str
    stage: ReviewStage
    decision: DecisionValue
    comment: str | None
    decided_at: datetime


class _UnitBase(BaseModel):
    id: UUID
    ordinal: int
    question_id: str | None
    text: str


class UnitAdminView(_UnitBase):
    audience: Literal["admin"] = "admin"
    status: UnitStatus
    content_hash: str
    decisions: list[DecisionView]


class UnitPeerView(_UnitBase):
    """Only the reviewer's own decision: peers judge independently."""

    audience: Literal["peer"] = "peer"
    my_decision: DecisionValue | None


class UnitAuthorView(_UnitBase):
    audience: Literal["author"] = "author"
    status: UnitStatus


UnitView = Annotated[UnitAdminView | UnitPeerView | UnitAuthorView, Field(discriminator="audience")]


class UnitDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: UUID
    decision: DecisionValue
    comment: str | None = Field(default=None, max_length=5_000)


class UnitDecisionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[UnitDecisionInput] = Field(max_length=1_000)


class RequestPeersBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_ids: list[UUID] = Field(min_length=1, max_length=50)
    required_approvals: int = Field(default=1, ge=1)


class ReviewQueueItem(BaseModel):
    assignment_id: UUID
    stage: ReviewStage
    vignette_code: str
    vignette_version: int
    unit_count: int
    requested_at: datetime
