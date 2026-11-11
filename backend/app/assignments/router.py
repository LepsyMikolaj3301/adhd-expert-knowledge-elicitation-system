from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.assignments import check, service
from app.assignments.schemas import (
    AssignmentSummary,
    AssignmentView,
    AssignRequest,
    DraftSave,
    DraftSaved,
    EventView,
    FindingsView,
    SubmissionView,
)
from app.assignments.state_machine import transition
from app.assignments.states import Action, State
from app.auth.dependencies import AdminUser, CurrentUser
from app.core.db import DbSession
from app.proofread import service as proofread
from app.proofread.schemas import ProofreadSave, ProofreadView

router = APIRouter(tags=["assignments"])


@router.post("/vignette-versions/{version_id}/assignments", status_code=status.HTTP_201_CREATED)
async def assign(
    version_id: UUID, body: AssignRequest, db: DbSession, admin: AdminUser
) -> list[AssignmentView]:
    assignments = await service.assign(db, version_id, body.expert_ids, admin)
    await db.commit()
    return [
        await service.build_view(db, assignment, service.Actor.ADMIN, admin)
        for assignment in assignments
    ]


@router.get("/assignments")
async def list_assignments(
    db: DbSession,
    user: CurrentUser,
    state: State | None = None,
    vignette_version_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AssignmentSummary]:
    return await service.list_assignments(
        db, user, state=state, vignette_version_id=vignette_version_id, limit=limit, offset=offset
    )


@router.get("/assignments/{assignment_id}")
async def get_assignment(assignment_id: UUID, db: DbSession, user: CurrentUser) -> AssignmentView:
    assignment, actor = await service.load(db, assignment_id, user)
    return await service.build_view(db, assignment, actor, user)


@router.get("/assignments/{assignment_id}/events")
async def get_events(assignment_id: UUID, db: DbSession, user: CurrentUser) -> list[EventView]:
    assignment, actor = await service.load(db, assignment_id, user)
    return await service.events(db, assignment, actor, user)


@router.get("/assignments/{assignment_id}/submission")
async def get_submission(assignment_id: UUID, db: DbSession, user: CurrentUser) -> SubmissionView:
    assignment, actor = await service.load(db, assignment_id, user)
    submission = await service.get_submission(db, assignment, actor)
    return SubmissionView.model_validate(submission)


@router.post("/assignments/{assignment_id}/start")
async def start(assignment_id: UUID, db: DbSession, user: CurrentUser) -> AssignmentView:
    assignment, actor = await service.lock(db, assignment_id, user)
    await service.start(db, assignment, actor, user)
    await db.commit()
    return await service.build_view(db, assignment, actor, user)


@router.post("/assignments/{assignment_id}/cancel")
async def cancel(assignment_id: UUID, db: DbSession, user: CurrentUser) -> AssignmentView:
    assignment, actor = await service.lock(db, assignment_id, user)
    await transition(db, assignment, Action.CANCEL, actor, user.id)
    await db.commit()
    return await service.build_view(db, assignment, actor, user)


@router.put("/assignments/{assignment_id}/draft")
async def save_draft(
    assignment_id: UUID, body: DraftSave, db: DbSession, user: CurrentUser
) -> DraftSaved:
    assignment, actor = await service.lock(db, assignment_id, user)
    saved = await service.save_draft(db, assignment, actor, body.version, body.payload)
    await db.commit()
    return saved


@router.post("/assignments/{assignment_id}/submit")
async def submit(assignment_id: UUID, db: DbSession, user: CurrentUser) -> AssignmentView:
    assignment, actor = await service.lock(db, assignment_id, user)
    await service.submit(db, assignment, actor, user)
    await db.commit()
    return await service.build_view(db, assignment, actor, user)


@router.get("/assignments/{assignment_id}/findings")
async def get_findings(assignment_id: UUID, db: DbSession, user: CurrentUser) -> FindingsView:
    assignment, actor = await service.load(db, assignment_id, user)
    return await check.get(db, assignment, actor)


@router.get("/assignments/{assignment_id}/proofread")
async def get_proofread(
    assignment_id: UUID, db: DbSession, user: CurrentUser, review_round: int | None = None
) -> ProofreadView:
    """The proofread answers of the current round (the admin and the author: any round)."""
    assignment, actor = await service.load(db, assignment_id, user)
    return await proofread.view(db, assignment, actor, review_round)


@router.put("/assignments/{assignment_id}/proofread")
async def save_proofread(
    assignment_id: UUID, body: ProofreadSave, db: DbSession, user: CurrentUser
) -> ProofreadView:
    assignment, actor = await service.lock(db, assignment_id, user)
    saved = await proofread.save(db, assignment, actor, body)
    await db.commit()
    return saved


@router.post("/assignments/{assignment_id}/submit-for-review")
async def submit_for_review(
    assignment_id: UUID, db: DbSession, user: CurrentUser
) -> AssignmentView:
    assignment, actor = await service.lock(db, assignment_id, user)
    await proofread.submit_for_review(db, assignment, actor, user)
    await db.commit()
    return await service.build_view(db, assignment, actor, user)


@router.post("/assignments/{assignment_id}/retry")
async def retry(assignment_id: UUID, db: DbSession, admin: AdminUser) -> AssignmentView:
    assignment, actor = await service.lock(db, assignment_id, admin)
    await service.retry(db, assignment, actor, admin)
    await db.commit()
    return await service.build_view(db, assignment, actor, admin)
