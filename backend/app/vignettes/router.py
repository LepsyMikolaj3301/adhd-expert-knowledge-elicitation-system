from uuid import UUID

from fastapi import APIRouter, status

from app.auth.dependencies import AdminUser
from app.core.db import DbSession
from app.vignettes import service
from app.vignettes.schemas import (
    VersionAdminView,
    VersionContent,
    VersionUpdate,
    VignetteAdminView,
    VignetteCreate,
)

router = APIRouter(tags=["vignettes"])


@router.get("/vignettes")
async def list_vignettes(db: DbSession, _: AdminUser) -> list[VignetteAdminView]:
    return await service.list_vignettes(db)


@router.post("/vignettes", status_code=status.HTTP_201_CREATED)
async def create_vignette(
    body: VignetteCreate, db: DbSession, admin: AdminUser
) -> VignetteAdminView:
    content = VersionContent(**body.model_dump(exclude={"code"}))
    vignette, version = await service.create_vignette(db, body.code, content, admin)
    await db.commit()
    return VignetteAdminView(
        id=vignette.id,
        code=vignette.code,
        created_at=vignette.created_at,
        versions=[VersionAdminView.model_validate(version)],
    )


@router.post("/vignettes/{vignette_id}/versions", status_code=status.HTTP_201_CREATED)
async def add_version(
    vignette_id: UUID, body: VersionContent, db: DbSession, admin: AdminUser
) -> VersionAdminView:
    version = await service.add_version(db, vignette_id, body, admin)
    await db.commit()
    return VersionAdminView.model_validate(version)


@router.patch("/vignette-versions/{version_id}")
async def update_version(
    version_id: UUID, body: VersionUpdate, db: DbSession, _: AdminUser
) -> VersionAdminView:
    version = await service.update_version(db, version_id, body)
    await db.commit()
    return VersionAdminView.model_validate(version)


@router.post("/vignette-versions/{version_id}/publish")
async def publish_version(version_id: UUID, db: DbSession, admin: AdminUser) -> VersionAdminView:
    version = await service.publish_version(db, version_id, admin)
    await db.commit()
    return VersionAdminView.model_validate(version)


@router.post("/vignette-versions/{version_id}/retire")
async def retire_version(version_id: UUID, db: DbSession, admin: AdminUser) -> VersionAdminView:
    version = await service.retire_version(db, version_id, admin)
    await db.commit()
    return VersionAdminView.model_validate(version)
