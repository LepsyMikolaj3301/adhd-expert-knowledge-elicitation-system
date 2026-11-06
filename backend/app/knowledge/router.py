from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.assignments.models import Assignment
from app.auth.dependencies import AdminUser
from app.core.db import DbSession
from app.knowledge.models import KnowledgeUnit, UnitStatus
from app.knowledge.schemas import KnowledgeUnitListItem
from app.users.models import User
from app.vignettes.models import Vignette, VignetteVersion

router = APIRouter(tags=["knowledge"])


@router.get("/knowledge-units")
async def list_knowledge_units(
    db: DbSession,
    _: AdminUser,
    unit_status: Annotated[UnitStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KnowledgeUnitListItem]:
    query = (
        select(KnowledgeUnit, Vignette.code, VignetteVersion.version, User.pseudonym)
        .join(Assignment, Assignment.id == KnowledgeUnit.assignment_id)
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
        .join(User, User.id == Assignment.expert_id)
        .order_by(KnowledgeUnit.created_at.desc(), KnowledgeUnit.id)
        .limit(limit)
        .offset(offset)
    )
    if unit_status is not None:
        query = query.where(KnowledgeUnit.status == unit_status)
    rows = (await db.execute(query)).all()
    return [
        KnowledgeUnitListItem(
            id=unit.id,
            assignment_id=unit.assignment_id,
            vignette_code=code,
            vignette_version=version,
            expert_pseudonym=pseudonym,
            ordinal=unit.ordinal,
            review_round=unit.review_round,
            text=unit.text,
            status=unit.status,
            created_at=unit.created_at,
        )
        for unit, code, version, pseudonym in rows
    ]
