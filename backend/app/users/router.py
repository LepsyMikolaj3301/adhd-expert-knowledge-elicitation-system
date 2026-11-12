from uuid import UUID

from fastapi import APIRouter, status

from app.auth.dependencies import AdminUser, CurrentUser
from app.auth.service import issue_invite
from app.core.db import DbSession
from app.users import service
from app.users.schemas import (
    InvitedUser,
    InviteIssued,
    PersonView,
    UserAdminView,
    UserCreate,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
async def list_users(db: DbSession, _: AdminUser) -> list[UserAdminView]:
    return [UserAdminView.model_validate(user) for user in await service.list_users(db)]


@router.get("/by-pseudonym/{pseudonym}")
async def person(pseudonym: str, db: DbSession, viewer: CurrentUser) -> PersonView:
    return await service.person_card(db, pseudonym, viewer)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, db: DbSession, admin: AdminUser) -> InvitedUser:
    user = await service.create_user(
        db,
        email=body.email,
        display_name=body.display_name,
        role=body.role,
        actor_id=admin.id,
    )
    invite_path = await issue_invite(db, user, admin.id)
    await db.commit()
    return InvitedUser(user=UserAdminView.model_validate(user), invite_path=invite_path)


@router.patch("/{user_id}")
async def update_user(
    user_id: UUID, body: UserUpdate, db: DbSession, admin: AdminUser
) -> UserAdminView:
    user = await service.get_user(db, user_id)
    await service.update_user(
        db, user, admin, display_name=body.display_name, is_active=body.is_active
    )
    await db.commit()
    return UserAdminView.model_validate(user)


@router.post("/{user_id}/invite")
async def reissue_invite(user_id: UUID, db: DbSession, admin: AdminUser) -> InviteIssued:
    """Also the way to reset a forgotten password: accepting the invite sets a new one."""
    user = await service.get_user(db, user_id)
    invite_path = await issue_invite(db, user, admin.id)
    await db.commit()
    return InviteIssued(invite_path=invite_path)
