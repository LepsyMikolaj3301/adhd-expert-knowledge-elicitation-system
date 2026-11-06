from fastapi import APIRouter, status

from app.auth.dependencies import CurrentUser
from app.core.db import DbSession
from app.home import service
from app.home.schemas import ActivitySeen, HomeView

router = APIRouter(tags=["home"])


@router.get("/me/home")
async def home(db: DbSession, user: CurrentUser) -> HomeView:
    return await service.home(db, user)


@router.post("/me/activity/seen", status_code=status.HTTP_204_NO_CONTENT)
async def activity_seen(db: DbSession, user: CurrentUser, body: ActivitySeen | None = None) -> None:
    service.mark_seen(user, body.until if body else None)
    await db.commit()
