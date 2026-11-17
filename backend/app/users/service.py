from uuid import UUID

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment
from app.assignments.states import State
from app.audit.service import record_event
from app.auth.service import end_all_sessions
from app.core.errors import DomainError, not_found
from app.core.security import hash_password
from app.users.models import PSEUDONYM_SEQUENCE, Role, User
from app.users.schemas import CaseCounts, PersonAdminCard, PersonCard, PersonView


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    display_name: str,
    role: Role,
    password: str | None = None,
    actor_id: UUID | None = None,
) -> User:
    number = await db.scalar(PSEUDONYM_SEQUENCE.next_value())
    letter = "A" if role == Role.ADMIN else "E"
    user = User(
        email=email.lower(),
        display_name=display_name,
        role=role,
        pseudonym=f"{letter}{number:02d}",
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


_DONE = {
    State.PROCESSING,
    State.PROCESSING_FAILED,
    State.INGESTING,
    State.INGESTION_FAILED,
    State.INGESTED,
}
_STOPPED = {State.CANCELLED, State.REJECTED}


async def person_card(db: AsyncSession, pseudonym: str, viewer: User) -> PersonView:
    user = await db.scalar(select(User).where(User.pseudonym == pseudonym))
    if user is None:
        raise not_found("Person")
    if viewer.role != Role.ADMIN:
        return PersonCard(pseudonym=user.pseudonym, role=user.role)
    rows = (
        await db.execute(
            select(Assignment.state, func.count())
            .where(Assignment.expert_id == user.id)
            .group_by(Assignment.state)
        )
    ).all()
    count = lambda states: sum(n for state, n in rows if state in states)  # noqa: E731
    return PersonAdminCard(
        pseudonym=user.pseudonym,
        role=user.role,
        display_name=user.display_name,
        email=user.email,
        is_active=user.is_active,
        cases=CaseCounts(
            open=count(
                {State.ASSIGNED, State.IN_PROGRESS, State.PROOFREADING, State.PROOFREAD_CHECK}
            ),
            in_review=count({State.PEER_REVIEW}),
            done=count(_DONE),
            stopped=count(_STOPPED),
        ),
    )
