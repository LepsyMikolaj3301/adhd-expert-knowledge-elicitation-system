"""What reviewers, the author and the admin read of a submission under review: its answers, one
by one, with the discussion and the votes under each."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.assignments.states import State
from app.proofread.schemas import AnswerLine, LinkedHighlight
from app.reviews.models import AnswerVoteValue, DecisionValue, Stance
from app.vignettes.questions import QuestionId


class Speaker(BaseModel):
    """Who said it. A reviewer is told by pseudonym; the author and the admin are only a role,
    unless the viewer is the admin, who sees every pseudonym."""

    kind: Literal["author", "reviewer", "admin"]
    pseudonym: str | None


class CommentView(BaseModel):
    id: UUID
    question_id: str
    # Replies are one level deep: this is a top-level comment of the same answer, or None.
    parent_id: UUID | None
    stance: Stance | None
    body: str
    created_at: datetime
    speaker: Speaker
    is_mine: bool


class VoteEntry(BaseModel):
    speaker: Speaker
    vote: AnswerVoteValue
    at: datetime


class DecisionView(BaseModel):
    decision: DecisionValue
    comment: str | None
    decided_at: datetime


class ReviewAnswer(BaseModel):
    question_id: str
    question: str
    # The author's edited answer, one sentence per line.
    text: str
    # Each line with the citations it is about. Empty for Q4's why, which is not linked.
    lines: list[AnswerLine]
    comments: list[CommentView]
    approvals: int
    disapprovals: int
    my_vote: AnswerVoteValue | None
    votes: list[VoteEntry]
    # The admin's, once the review is closed.
    decision: DecisionView | None


class ReviewAnswersView(BaseModel):
    review_round: int
    # The rounds that were submitted for review: the admin and the author can read each.
    rounds: list[int]
    state: State
    highlights: list[LinkedHighlight]
    answers: list[ReviewAnswer]


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5_000)]
    stance: Stance | None = None
    parent_id: UUID | None = None


class VoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vote: AnswerVoteValue
    # The round the reviewer was looking at: a vote on an answer that has since been edited is
    # refused instead of landing on text nobody read.
    review_round: int = Field(ge=1)


class AnswerDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: QuestionId
    decision: DecisionValue
    comment: str | None = Field(default=None, max_length=5_000)


class AnswerDecisionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[AnswerDecisionInput] = Field(max_length=20)


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
    answer_count: int
    approvals: int
    disapprovals: int
    comment_count: int
    # How many of this round's answers the viewer has voted on.
    my_votes: int
    updated_at: datetime
    # Only the admin knows who wrote it.
    author_pseudonym: str | None
