from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.assignments.states import State
from app.core.db import Base, enum_column, utcnow


class Assignment(Base):
    """One expert on one vignette version. Holds the workflow state."""

    __tablename__ = "assignments"
    __table_args__ = (
        # A cancelled assignment must not stop the expert being assigned the vignette again.
        Index(
            "uq_assignments_active",
            "vignette_version_id",
            "expert_id",
            unique=True,
            postgresql_where=text("state <> 'cancelled'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    vignette_version_id: Mapped[UUID] = mapped_column(ForeignKey("app.vignette_versions.id"))
    expert_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), index=True)
    assigned_by: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    state: Mapped[State] = mapped_column(
        enum_column(State, "state"), default=State.ASSIGNED, index=True
    )
    # 1 until a reviewer's change request sends the units back to the author: then 2, and so on.
    review_round: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    gate_passed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How many citations existed at the gate. These are fixed; later ones stay editable.
    locked_highlights: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class AnswerDraft(Base):
    """Overwritten by autosave, so it lives apart from the assignment row."""

    __tablename__ = "answer_drafts"

    assignment_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.assignments.id", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class Submission(Base):
    """The frozen answers. A database trigger rejects UPDATE (see the initial migration)."""

    __tablename__ = "submissions"

    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("app.assignments.id"), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_format: Mapped[int] = mapped_column(Integer)
    vignette_hash: Mapped[str] = mapped_column(String(64))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
