from typing import Annotated

from fastapi import APIRouter, Query

from app.auth.dependencies import AdminUser
from app.core.db import DbSession
from app.knowledge import search as knowledge_search
from app.knowledge.models import KnowledgeUnit, UnitStatus
from app.knowledge.schemas import (
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeUnitListItem,
)
from app.knowledge.service import unit_items

router = APIRouter(tags=["knowledge"])


@router.get("/knowledge-units")
async def list_knowledge_units(
    db: DbSession,
    _: AdminUser,
    unit_status: Annotated[UnitStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KnowledgeUnitListItem]:
    conditions = [KnowledgeUnit.status == unit_status] if unit_status is not None else []
    return await unit_items(db, *conditions, limit=limit, offset=offset)


@router.post("/knowledge-units/search")
async def search_knowledge_units(
    request: KnowledgeSearchRequest, db: DbSession, _: AdminUser
) -> KnowledgeSearchResponse:
    """Runs the platform's retrievers over the ingested units, for the admin to see what a
    question or a patient's text finds. A POST, so that typed text stays out of URLs and logs."""
    return await knowledge_search.search(db, request)
