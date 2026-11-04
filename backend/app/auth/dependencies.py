from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy import select

from app.auth.models import AuthSession
from app.auth.service import SESSION_COOKIE
from app.core.db import DbSession, utcnow
from app.core.errors import DomainError, forbidden
from app.core.security import hash_token
from app.users.models import Role, User


async def current_user(request: Request, db: DbSession) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    user = None
    if token:
        user = await db.scalar(
            select(User)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                AuthSession.token_hash == hash_token(token),
                AuthSession.expires_at > utcnow(),
                User.is_active,
            )
        )
    if user is None:
        raise DomainError("not_authenticated", "Please log in.", status.HTTP_401_UNAUTHORIZED)
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(role: Role):
    async def dependency(user: CurrentUser) -> User:
        if user.role != role:
            raise forbidden()
        return user

    return dependency


AdminUser = Annotated[User, Depends(require_role(Role.ADMIN))]
