"""One view of a unit per audience, told apart by `audience`; the discussion under it is the same
for all three."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.assignments.states import State
from app.knowledge.models import UnitStatus
from app.reviews.models import DecisionValue, ReviewStage, Stance, Vote


class Speaker(BaseModel):
    """Who said it. A reviewer is told by pseudonym; the author and the admin are only a role,
    unless the viewer is the admin, who sees every pseudonym."""

    kind: Literal["author", "reviewer", "admin"]
    pseudonym: str | None


class CommentView(BaseModel):
    id: UUID
    unit_id: UUID
    # Replies are one level deep: this is a top-level comment of the same unit, or None.
    parent_id: UUID | None
    stance: Stance | None
    body: str
    created_at: datetime
    speaker: Speaker
    is_mine: bool


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
    review_round: int
    text: str
    # Cut by citation: a fragment unit is everything said about one passage of the vignette, the
    # case unit everything said about the text as a whole.
    kind: str | None
    direction: str | None
    patient_words: str | None
    comments: list[CommentView]


class UnitAdminView(_UnitBase):
    audience: Literal["admin"] = "admin"
    status: UnitStatus
    content_hash: str
    decisions: list[DecisionView]


class UnitPeerView(_UnitBase):
    audience: Literal["peer"] = "peer"


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


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5_000)]
    stance: Stance | None = None
    parent_id: UUID | None = None


class VoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vote: Vote
    # The round the reviewer was looking at: a vote on units that have since been cut again is
    # refused instead of landing on text nobody read.
    review_round: int = Field(ge=1)


class VoteEntry(BaseModel):
    speaker: Speaker
    vote: Vote
    at: datetime


class VotesView(BaseModel):
    review_round: int
    accepts: int
    declines: int
    my_vote: Vote | None
    votes: list[VoteEntry]


Relation = Literal["reviewer", "author", "admin"]


class ReviewItem(BaseModel):
    assignment_id: UUID
    vignette_code: str
    vignette_version: int
    review_round: int
    state: State
    relation: Relation
    # A reviewer has agreed to read it. Always true for the author and the admin.
    opened: bool
    unit_count: int
    accepts: int
    declines: int
    comment_count: int
    my_vote: Vote | None
    updated_at: datetime
    # Only the admin knows who wrote it.
    author_pseudonym: str | None
