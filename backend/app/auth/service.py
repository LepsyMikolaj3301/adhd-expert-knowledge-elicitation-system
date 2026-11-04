from datetime import datetime, timedelta

from fastapi import Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_event
from app.auth.models import AuthSession, Invite
from app.core.db import utcnow
from app.core.errors import DomainError
from app.core.security import (
    hash_password,
    hash_token,
    needs_rehash,
    new_token,
    run_hash,
    verify_password,
)
from app.settings import settings
from app.users.models import User

SESSION_COOKIE = "session"
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
INVITE_TTL = timedelta(days=7)


def _invalid_credentials() -> DomainError:
    # The same answer for an unknown email, a wrong password and a locked account.
    return DomainError(
        "invalid_credentials",
        "Wrong email or password, or the account is temporarily locked.",
        status.HTTP_401_UNAUTHORIZED,
    )


async def create_session(db: AsyncSession, user: User) -> str:
    token = new_token()
    expires_at = utcnow() + timedelta(hours=settings.session_ttl_hours)
    db.add(AuthSession(token_hash=hash_token(token), user_id=user.id, expires_at=expires_at))
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure or settings.environment == "production",
    )


def _is_locked(locked_until: datetime | None) -> bool:
    return locked_until is not None and locked_until > utcnow()


async def login(db: AsyncSession, email: str, password: str) -> tuple[User, str]:
    """Commits itself, because a failed attempt has to be counted even though the call raises.

    Holds no database connection or lock during the slow hash, so that a flood of logins can't use
    up the connections that autosaves need.
    """
    seen = (
        await db.execute(
            select(User.id, User.password_hash, User.is_active, User.locked_until).where(
                User.email == email.lower()
            )
        )
    ).first()
    await db.rollback()
    if (
        seen is None
        or not seen.is_active
        or seen.password_hash is None
        or _is_locked(seen.locked_until)
    ):
        await run_hash(verify_password, None, password)
        raise _invalid_credentials()
    matches = await run_hash(verify_password, seen.password_hash, password)
    new_hash = (
        await run_hash(hash_password, password)
        if matches and needs_rehash(seen.password_hash)
        else None
    )

    # Many tries can be in flight at once, so the account's state is decided again under a lock:
    # a right guess must fail if the wrong ones before it have locked the account in the meantime.
    user = await db.scalar(select(User).where(User.id == seen.id).with_for_update())
    if (
        user is None
        or not user.is_active
        or user.password_hash != seen.password_hash
        or _is_locked(user.locked_until)
    ):
        raise _invalid_credentials()
    now = utcnow()
    if not matches:
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.failed_logins = 0
            user.locked_until = now + LOCKOUT
        await db.commit()
        raise _invalid_credentials()

    user.failed_logins = 0
    user.locked_until = None
    if new_hash is not None:
        user.password_hash = new_hash
    await db.execute(
        delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at <= now)
    )
    token = await create_session(db, user)
    await db.commit()
    return user, token


async def logout(db: AsyncSession, token: str | None) -> None:
    if token:
        await db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        await db.commit()


async def end_all_sessions(db: AsyncSession, user: User) -> None:
    await db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))


async def issue_invite(db: AsyncSession, user: User, actor_id) -> str:
    """Replace any earlier unused invite. Returns the path the admin passes on to the user."""
    await db.execute(delete(Invite).where(Invite.user_id == user.id, Invite.used_at.is_(None)))
    token = new_token()
    db.add(Invite(user_id=user.id, token_hash=hash_token(token), expires_at=utcnow() + INVITE_TTL))
    record_event(
        db, actor_id=actor_id, entity_type="user", entity_id=user.id, action="invite_issued"
    )
    return f"/invite/{token}"


async def accept_invite(db: AsyncSession, token: str, password: str) -> tuple[User, str]:
    # Before touching the database, so that no connection or lock is held during the slow hash.
    password_hash = await run_hash(hash_password, password)
    invite = await db.scalar(
        select(Invite).where(Invite.token_hash == hash_token(token)).with_for_update()
    )
    now = utcnow()
    user = await db.get(User, invite.user_id) if invite else None
    if (
        invite is None
        or user is None
        or not user.is_active
        or invite.used_at
        or invite.expires_at <= now
    ):
        raise DomainError(
            "invalid_invite", "This invite is not valid.", status.HTTP_400_BAD_REQUEST
        )
    invite.used_at = now
    user.password_hash = password_hash
    user.failed_logins = 0
    user.locked_until = None
    await end_all_sessions(db, user)
    session_token = await create_session(db, user)
    record_event(
        db, actor_id=user.id, entity_type="user", entity_id=user.id, action="invite_accepted"
    )
    return user, session_token
