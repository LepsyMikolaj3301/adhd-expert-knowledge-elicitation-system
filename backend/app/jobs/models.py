from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_column, utcnow


class JobKind(StrEnum):
    PROOFREAD = "proofread"
    PROCESS = "process"
    INGEST = "ingest"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # At most one live job of each kind per assignment.
        Index(
            "uq_jobs_active",
            "assignment_id",
            "kind",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index("ix_jobs_claim", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[JobKind] = mapped_column(enum_column(JobKind, "kind"))
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("app.assignments.id"))
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus, "status"), default=JobStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The exception class only: messages could quote an expert's text.
    last_error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
