from fastapi import APIRouter, Request, Response, status

from app.auth import service
from app.auth.dependencies import CurrentUser
from app.auth.schemas import AcceptInviteRequest, CheckInviteRequest, LoginRequest
from app.core.db import DbSession
from app.users.schemas import UserView

router = APIRouter(tags=["auth"])


@router.post("/auth/login")
async def login(body: LoginRequest, response: Response, db: DbSession) -> UserView:
    user, token = await service.login(db, body.email, body.password)
    service.set_session_cookie(response, token)
    return UserView.model_validate(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: DbSession) -> None:
    await service.logout(db, request.cookies.get(service.SESSION_COOKIE))
    response.delete_cookie(service.SESSION_COOKIE, path="/")


@router.post("/auth/check-invite", status_code=status.HTTP_204_NO_CONTENT)
async def check_invite(body: CheckInviteRequest, db: DbSession) -> None:
    """A POST, so that the token stays out of access logs."""
    await service.check_invite(db, body.token)


@router.post("/auth/accept-invite")
async def accept_invite(body: AcceptInviteRequest, response: Response, db: DbSession) -> UserView:
    user, token = await service.accept_invite(db, body.token, body.password)
    await db.commit()
    service.set_session_cookie(response, token)
    return UserView.model_validate(user)


@router.get("/me")
async def me(user: CurrentUser) -> UserView:
    return UserView.model_validate(user)
