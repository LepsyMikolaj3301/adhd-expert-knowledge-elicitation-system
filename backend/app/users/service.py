from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_event
from app.auth.service import end_all_sessions
from app.core.errors import DomainError, not_found
from app.core.security import hash_password
from app.users.models import PSEUDONYM_SEQUENCE, SYNTHETIC_PREFIX, Role, User


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    display_name: str,
    role: Role,
    is_synthetic: bool = False,
    password: str | None = None,
    actor_id: UUID | None = None,
) -> User:
    number = await db.scalar(PSEUDONYM_SEQUENCE.next_value())
    letter = "A" if role == Role.ADMIN else "E"
    prefix = SYNTHETIC_PREFIX if is_synthetic else ""
    user = User(
        email=email.lower(),
        display_name=display_name,
        role=role,
        pseudonym=f"{prefix}{letter}{number:02d}",
        is_synthetic=is_synthetic,
        password_hash=hash_password(password) if password else None,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise DomainError(
            "email_taken", "A user with this email already exists.", status.HTTP_409_CONFLICT
        ) from exc
    record_event(
        db,
        actor_id=actor_id,
        entity_type="user",
        entity_id=user.id,
        action="user_created",
        meta={"role": role.value},
    )
    return user


async def get_user(db: AsyncSession, user_id: UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise not_found("User")
    return user


async def list_users(db: AsyncSession) -> list[User]:
    return list(await db.scalars(select(User).order_by(User.created_at)))


async def update_user(
    db: AsyncSession, user: User, actor: User, *, display_name: str | None, is_active: bool | None
) -> User:
    if display_name is not None:
        user.display_name = display_name
    if is_active is not None and is_active != user.is_active:
        if not is_active and user.id == actor.id:
            # Keeps at least one admin able to log in.
            raise DomainError("cannot_deactivate_self", "You can't deactivate your own account.")
        user.is_active = is_active
        if not is_active:
            await end_all_sessions(db, user)
        record_event(
            db,
            actor_id=actor.id,
            entity_type="user",
            entity_id=user.id,
            action="user_activated" if is_active else "user_deactivated",
        )
    return user
