from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.assignments import service as assignments
from app.assignments.schemas import AssignmentView
from app.auth.dependencies import CurrentUser
from app.core.db import DbSession
from app.reviews import service
from app.reviews.schemas import (
    AnswerDecisionsRequest,
    CommentCreate,
    CommentView,
    ReviewAnswersView,
    ReviewItem,
    VoteInput,
)
from app.vignettes.questions import QuestionId

router = APIRouter(tags=["reviews"])


@router.get("/reviews")
async def list_reviews(
    db: DbSession,
    user: CurrentUser,
    status: Literal["open", "closed"] | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ReviewItem]:
    """The submissions the viewer can follow: open ones wait for the admin's decision."""
    return await service.list_reviews(db, user, status=status, limit=limit)


@router.post("/assignments/{assignment_id}/review/open", status_code=status.HTTP_204_NO_CONTENT)
async def open_review(assignment_id: UUID, db: DbSession, user: CurrentUser) -> None:
    """A reviewer agrees to read the submission. From then on they can't be assigned the
    vignette, because what they read would colour their own answer."""
    assignment, actor = await assignments.lock(db, assignment_id, user, allow_unopened=True)
    await service.open_review(db, assignment, actor, user)
    await db.commit()


@router.get("/assignments/{assignment_id}/answers")
async def list_answers(
    assignment_id: UUID, db: DbSession, user: CurrentUser, review_round: int | None = None
) -> ReviewAnswersView:
    """The answers under review. The admin and the author can ask for an earlier round."""
    assignment, actor = await assignments.load(db, assignment_id, user)
    return await service.list_answers(db, assignment, actor, user, review_round)


@router.post(
    "/assignments/{assignment_id}/answers/{question_id}/comments",
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    assignment_id: UUID,
    question_id: QuestionId,
    body: CommentCreate,
    db: DbSession,
    user: CurrentUser,
) -> CommentView:
    assignment, actor = await assignments.lock(db, assignment_id, user)
    comment = await service.add_comment(db, assignment, actor, user, question_id, body)
    await db.commit()
    return comment


@router.put("/assignments/{assignment_id}/answers/{question_id}/vote")
async def cast_vote(
    assignment_id: UUID,
    question_id: QuestionId,
    body: VoteInput,
    db: DbSession,
    user: CurrentUser,
) -> ReviewAnswersView:
    assignment, actor = await assignments.lock(db, assignment_id, user)
    answers = await service.cast_vote(db, assignment, actor, user, question_id, body)
    await db.commit()
    return answers


@router.post("/assignments/{assignment_id}/answer-decisions")
async def submit_decisions(
    assignment_id: UUID, body: AnswerDecisionsRequest, db: DbSession, user: CurrentUser
) -> AssignmentView:
    """The admin's decision on each answer; it closes the review."""
    assignment, actor = await assignments.lock(db, assignment_id, user)
    await service.submit_decisions(db, assignment, actor, user, body.decisions)
    await db.commit()
    return await assignments.build_view(db, assignment, actor, user)
