from uuid import UUID

from fastapi import APIRouter

from app.assignments import service as assignments
from app.assignments.schemas import AssignmentView
from app.auth.dependencies import AdminUser, CurrentUser
from app.core.db import DbSession
from app.reviews import service
from app.reviews.schemas import RequestPeersBody, ReviewQueueItem, UnitDecisionsRequest, UnitView

router = APIRouter(tags=["reviews"])


@router.get("/review-requests")
async def review_queue(db: DbSession, user: CurrentUser) -> list[ReviewQueueItem]:
    return await service.review_queue(db, user)


@router.get("/assignments/{assignment_id}/units")
async def list_units(
    assignment_id: UUID, db: DbSession, user: CurrentUser, review_round: int | None = None
) -> list[UnitView]:
    """The current round's units; the admin can ask for an earlier round with `review_round`."""
    assignment, actor = await assignments.load(db, assignment_id, user)
    return await service.list_units(db, assignment, actor, user, review_round)


@router.post("/assignments/{assignment_id}/unit-decisions")
async def submit_decisions(
    assignment_id: UUID, body: UnitDecisionsRequest, db: DbSession, user: CurrentUser
) -> AssignmentView:
    assignment, actor = await assignments.lock(db, assignment_id, user)
    await service.submit_decisions(db, assignment, actor, user, body.decisions)
    await db.commit()
    return await assignments.build_view(db, assignment, actor, user)


@router.post("/assignments/{assignment_id}/reviewers")
async def request_peers(
    assignment_id: UUID, body: RequestPeersBody, db: DbSession, admin: AdminUser
) -> AssignmentView:
    assignment, actor = await assignments.lock(db, assignment_id, admin)
    await service.request_peers(
        db, assignment, actor, admin, body.reviewer_ids, body.required_approvals
    )
    await db.commit()
    return await assignments.build_view(db, assignment, actor, admin)


@router.post("/assignments/{assignment_id}/recall-review")
async def recall_review(assignment_id: UUID, db: DbSession, admin: AdminUser) -> AssignmentView:
    assignment, actor = await assignments.lock(db, assignment_id, admin)
    await service.recall_review(db, assignment, actor, admin)
    await db.commit()
    return await assignments.build_view(db, assignment, actor, admin)
