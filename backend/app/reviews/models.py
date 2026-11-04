from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_column, utcnow


class ReviewStage(StrEnum):
    ADMIN = "admin"
    PEER = "peer"


class DecisionValue(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ReviewRequest(Base):
    __tablename__ = "review_requests"
    __table_args__ = (UniqueConstraint("assignment_id", "reviewer_id", "stage"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("app.assignments.id"))
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), index=True)
    stage: Mapped[ReviewStage] = mapped_column(enum_column(ReviewStage, "stage"))
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
