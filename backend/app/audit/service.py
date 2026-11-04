from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent


def record_event(
    db: AsyncSession,
    *,
    actor_id: UUID | None,
    entity_type: str,
    entity_id: UUID,
    action: str,
    from_state: str | None = None,
    to_state: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Add an event to the current transaction. `meta` must hold ids and counts, never text."""
    db.add(
        AuditEvent(
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            from_state=from_state,
            to_state=to_state,
            meta=meta or {},
        )
    )
