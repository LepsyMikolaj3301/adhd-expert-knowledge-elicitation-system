from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_column, utcnow


class DecisionValue(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    # The answer could be right with another wording: the author is asked to edit it.
    REQUEST_CHANGES = "request_changes"


class Stance(StrEnum):
    """How a reviewer's comment sits with the answer it is under."""

    SUPPORT = "support"
    CHALLENGE = "challenge"
    QUESTION = "question"


class AnswerVoteValue(StrEnum):
    APPROVE = "approve"
    DISAPPROVE = "disapprove"


class ReviewParticipant(Base):
    """An expert who opened a review and so read a colleague's answers to this vignette.

    The row is what keeps them from being assigned the vignette afterwards: what they read would
    colour their own answer. Authors and the admin never get one.
    """

    __tablename__ = "review_participants"

    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("app.assignments.id"), primary_key=True)
    expert_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.users.id"), primary_key=True, index=True
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class AnswerComment(Base):
    """One line of the discussion under an answer of one round. Never edited: decisions rest on
    what was said."""

    __tablename__ = "answer_comments"
    __table_args__ = (Index("ix_answer_comments_answer", "assignment_id", "review_round"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("app.assignments.id"))
    review_round: Mapped[int] = mapped_column(Integer)
    question_id: Mapped[str] = mapped_column(String(8))
    author_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), index=True)
    # Replies are one level deep: this is always a top-level comment of the same answer.
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("app.answer_comments.id"))
    # Only reviewers take a side; the author and the admin comment without one.
    stance: Mapped[Stance | None] = mapped_column(enum_column(Stance, "stance"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class AnswerVote(Base):
    """A reviewer's approval or disapproval of one answer. Advisory: only the admin closes a
    review. One per reviewer, answer and round, changeable until the review closes."""

    __tablename__ = "answer_votes"

    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("app.assignments.id"), primary_key=True)
    review_round: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    voter_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), primary_key=True)
    vote: Mapped[AnswerVoteValue] = mapped_column(enum_column(AnswerVoteValue, "vote"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class AnswerDecision(Base):
    """The admin's decision on one answer of one round."""

    __tablename__ = "answer_decisions"

    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("app.assignments.id"), primary_key=True)
    review_round: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    decision: Mapped[DecisionValue] = mapped_column(enum_column(DecisionValue, "decision"))
    comment: Mapped[str | None] = mapped_column(Text)
    # An approval only counts for the exact text (and links) that were reviewed.
    content_hash: Mapped[str] = mapped_column(String(64))
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
