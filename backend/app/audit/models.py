from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow


class AuditEvent(Base):
    """Append-only (a database trigger rejects UPDATE). Must never hold answer or unit text."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id", "at"),
        # The home page reads the trail by what happened, across assignments.
        Index("ix_audit_events_action_at", "action", "at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # NULL for the system (background jobs).
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("app.users.id"))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[UUID] = mapped_column()
    action: Mapped[str] = mapped_column(String(64))
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str | None] = mapped_column(String(32))
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
