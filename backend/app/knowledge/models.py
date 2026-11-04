from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_column, utcnow


class UnitStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INGESTED = "ingested"


class KnowledgeUnit(Base):
    """A reviewable unit of an expert's text. Retrieval must only ever read `ingested` units."""

    __tablename__ = "knowledge_units"
    __table_args__ = (UniqueConstraint("assignment_id", "ordinal"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("app.assignments.id"))
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("app.submissions.assignment_id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    question_id: Mapped[str | None] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[UnitStatus] = mapped_column(
        enum_column(UnitStatus, "status"), default=UnitStatus.PENDING, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
