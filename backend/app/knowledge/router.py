from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.assignments.models import Assignment
from app.audit.service import record_event
from app.auth.dependencies import AdminUser
from app.core.db import DbSession
from app.core.errors import not_found
from app.jobs.models import Job, JobKind, JobStatus
from app.knowledge import search as knowledge_search
from app.knowledge.models import KnowledgeUnit, UnitStatus
from app.knowledge.removal import enqueue_refit, remove_units
from app.knowledge.schemas import (
    IndexStatus,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeUnitListItem,
    UnitsRemoved,
)
from app.knowledge.service import unit_items
from app.users.models import User

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


@router.get("/knowledge-units/index")
async def index_status(db: DbSession, _: AdminUser) -> IndexStatus:
    """Whether the search index has caught up with the last removal (the BM25 refit job)."""
    job = await db.scalar(
        select(Job).where(Job.kind == JobKind.REFIT).order_by(Job.created_at.desc()).limit(1)
    )
    if job is None or job.status == JobStatus.DONE:
        return IndexStatus(state="up_to_date")
    return IndexStatus(state=job.status.value, last_error=job.last_error)


@router.post("/knowledge-units/index/refit", status_code=status.HTTP_202_ACCEPTED)
async def refit_index(db: DbSession, _: AdminUser) -> IndexStatus:
    """Queues a BM25 refit by hand, e.g. after one failed."""
    await enqueue_refit(db)
    await db.commit()
    return IndexStatus(state="queued")


@router.delete("/knowledge-units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_knowledge_unit(unit_id: UUID, db: DbSession, admin: AdminUser) -> None:
    """Takes one ingested unit out of the knowledge base. Retrieval stops finding it at once;
    the BM25 weights are refit by the worker."""
    unit = await db.scalar(
        select(KnowledgeUnit).where(KnowledgeUnit.id == unit_id).with_for_update()
    )
    if unit is None or unit.status != UnitStatus.INGESTED:
        raise not_found("Knowledge unit")
    await remove_units(db, [unit], admin.id)
    await db.commit()


@router.delete("/knowledge-units/by-expert/{expert_id}")
async def remove_expert_knowledge(expert_id: UUID, db: DbSession, admin: AdminUser) -> UnitsRemoved:
    """Takes everything an expert gave out of the knowledge base, in every case: for an expert
    who no longer wants their knowledge used."""
    expert = await db.get(User, expert_id)
    if expert is None:
        raise not_found("Expert")
    units = list(
        await db.scalars(
            select(KnowledgeUnit)
            .join(Assignment, Assignment.id == KnowledgeUnit.assignment_id)
            .where(Assignment.expert_id == expert_id, KnowledgeUnit.status == UnitStatus.INGESTED)
            .order_by(KnowledgeUnit.assignment_id, KnowledgeUnit.ordinal)
            .with_for_update(of=KnowledgeUnit)
        )
    )
    removed = await remove_units(db, units, admin.id)
    if removed:
        record_event(
            db,
            actor_id=admin.id,
            entity_type="user",
            entity_id=expert_id,
            action="knowledge_withdrawn",
            meta={"units": removed},
        )
    await db.commit()
    return UnitsRemoved(removed=removed)
