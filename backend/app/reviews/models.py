from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_column, utcnow


class ReviewStage(StrEnum):
    ADMIN = "admin"
    PEER = "peer"


class DecisionValue(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    # The unit could be right with another filing: the author is asked to correct it.
    REQUEST_CHANGES = "request_changes"


class Stance(StrEnum):
    """How a reviewer's comment sits with the unit it is under."""

    SUPPORT = "support"
    CHALLENGE = "challenge"
    QUESTION = "question"


class Vote(StrEnum):
    ACCEPT = "accept"
    DECLINE = "decline"


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


class UnitComment(Base):
    """One line of the discussion under a unit. Never edited: decisions rest on what was said."""

    __tablename__ = "unit_comments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    unit_id: Mapped[UUID] = mapped_column(ForeignKey("app.knowledge_units.id"), index=True)
    author_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), index=True)
    # Replies are one level deep: this is always a top-level comment of the same unit.
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("app.unit_comments.id"))
    # Only reviewers take a side; the author and the admin comment without one.
    stance: Mapped[Stance | None] = mapped_column(enum_column(Stance, "stance"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class SubmissionVote(Base):
    """A reviewer's accept or decline of a whole submission. Advisory: only the admin closes a
    review. One per reviewer and review round, changeable until the review closes."""

    __tablename__ = "submission_votes"

    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("app.assignments.id"), primary_key=True)
    review_round: Mapped[int] = mapped_column(Integer, primary_key=True)
    voter_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), primary_key=True)
    vote: Mapped[Vote] = mapped_column(enum_column(Vote, "vote"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class UnitDecision(Base):
    __tablename__ = "unit_decisions"
    __table_args__ = (UniqueConstraint("unit_id", "reviewer_id", "stage"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    unit_id: Mapped[UUID] = mapped_column(ForeignKey("app.knowledge_units.id"))
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    stage: Mapped[ReviewStage] = mapped_column(enum_column(ReviewStage, "stage"))
    decision: Mapped[DecisionValue] = mapped_column(enum_column(DecisionValue, "decision"))
    comment: Mapped[str | None] = mapped_column(Text)
    # An approval only counts for the exact text that was reviewed.
    unit_content_hash: Mapped[str] = mapped_column(String(64))
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
