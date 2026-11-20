"""What the home page shows. Computed when read from the workflow's own records, so nothing is
stored per user (only when they last looked) and new experts see their feed at once."""

import time
from datetime import datetime, timedelta

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app import compute
from app.assignments.models import Assignment
from app.assignments.states import Actor, State
from app.audit.models import AuditEvent
from app.core.db import utcnow
from app.home.schemas import (
    ActivityItem,
    ActivityKind,
    ComputeStatus,
    HomeView,
    NextAction,
    NextUpItem,
    Outcome,
    SystemStatus,
)
from app.jobs.models import Job, JobStatus
from app.reviews import access
from app.reviews import service as reviews
from app.reviews.models import AnswerComment, ReviewParticipant
from app.users.models import Role, User
from app.vignettes.models import Vignette, VignetteVersion

NEXT_UP = 5
WAITING = 5
RECENT = 10
ACTIVITY = 30
EXCERPT = 140
# A job that could run and has waited this long means the worker isn't taking jobs.
STUCK_MINUTES = 5

EXPERT_ACTIONS: dict[State, NextAction] = {
    State.ASSIGNED: "start",
    State.IN_PROGRESS: "continue",
    State.PROOFREAD_CHECK: "check",
}
ADMIN_ACTIONS: dict[State, NextAction] = {
    State.PROCESSING_FAILED: "retry",
    State.INGESTION_FAILED: "retry",
}

# What each audit event means to the people it reaches. Older events keep their old names.
REVIEW_OPENED = ("submit_for_review", "units_built", "units_built_for_peers")
REVIEW_CLOSED: dict[str, Outcome] = {
    "approve_answers": "accepted",
    "reject_all_answers": "rejected",
    "approve_units": "accepted",
    "reject_all_units": "rejected",
    "request_changes": "sent_back",
}
JOB_FAILED = ("proofread_failed", "processing_failed", "units_failed", "ingestion_failed")
# The author's answers are ready to check (`processing_succeeded` before proofreading existed).
CHECK_READY = ("proofread_succeeded",)


async def _next_up(db: AsyncSession, viewer: User) -> tuple[list[NextUpItem], int]:
    is_admin = viewer.role == Role.ADMIN
    actions = ADMIN_ACTIONS if is_admin else EXPERT_ACTIONS
    where = [Assignment.state.in_(list(actions))]
    if not is_admin:
        where.append(Assignment.expert_id == viewer.id)
    total = await db.scalar(select(func.count()).select_from(Assignment).where(*where))
    rows = await db.execute(
        select(Assignment, VignetteVersion.version, Vignette.code, User.pseudonym)
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
        .join(User, User.id == Assignment.expert_id)
        .where(*where)
        .order_by(Assignment.updated_at.desc(), Assignment.id)
        .limit(NEXT_UP)
    )
    items = [
        NextUpItem(
            assignment_id=assignment.id,
            vignette_code=code,
            vignette_version=version,
            state=assignment.state,
            action=actions[assignment.state],
            expert_pseudonym=pseudonym if is_admin else None,
            updated_at=assignment.updated_at,
        )
        for assignment, version, code, pseudonym in rows
    ]
    return items, total or 0


async def _workflow_activity(db: AsyncSession, viewer: User) -> list[tuple[datetime, ActivityItem]]:
    """Events of the workflow that concern the viewer. Their own actions are left out."""
    own = Assignment.expert_id == viewer.id
    if viewer.role == Role.ADMIN:
        wanted = or_(
            AuditEvent.action.in_(REVIEW_OPENED),
            AuditEvent.action.in_(list(REVIEW_CLOSED)),
            AuditEvent.action.in_(JOB_FAILED),
        )
    else:
        blocked = await access.blocked_vignettes(db, viewer.id)
        took_part = exists().where(
            ReviewParticipant.assignment_id == Assignment.id,
            ReviewParticipant.expert_id == viewer.id,
        )
        wanted = or_(
            and_(own, AuditEvent.action.in_(("assigned", *CHECK_READY))),
            and_(
                AuditEvent.action.in_(REVIEW_OPENED),
                or_(own, VignetteVersion.vignette_id.not_in(blocked)),
            ),
            and_(AuditEvent.action.in_(list(REVIEW_CLOSED)), or_(own, took_part)),
        )
    rows = await db.execute(
        select(AuditEvent, Vignette.code, Assignment.id)
        .join(Assignment, Assignment.id == AuditEvent.entity_id)
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
        .where(
            AuditEvent.entity_type == "assignment",
            or_(AuditEvent.actor_id.is_(None), AuditEvent.actor_id != viewer.id),
            wanted,
        )
        .order_by(AuditEvent.at.desc())
        .limit(ACTIVITY)
    )
    items = []
    for event, code, assignment_id in rows:
        kind: ActivityKind
        outcome: Outcome | None = None
        if event.action in REVIEW_CLOSED:
            kind, outcome = "review_closed", REVIEW_CLOSED[event.action]
        elif event.action in REVIEW_OPENED:
            kind = "review_opened"
        elif event.action in JOB_FAILED:
            kind = "job_failed"
        else:
            kind = "case_assigned" if event.action == "assigned" else "check_ready"
        items.append(
            (
                event.at,
                ActivityItem(
                    kind=kind,
                    assignment_id=assignment_id,
                    vignette_code=code,
                    at=event.at,
                    unread=False,
                    outcome=outcome,
                ),
            )
        )
    return items


async def _comment_activity(db: AsyncSession, viewer: User) -> list[tuple[datetime, ActivityItem]]:
    """Comments on the viewer's own answers, and replies in threads they took part in."""
    other = aliased(AnswerComment)
    in_my_thread = and_(
        AnswerComment.parent_id.is_not(None),
        exists().where(
            or_(other.id == AnswerComment.parent_id, other.parent_id == AnswerComment.parent_id),
            other.author_id == viewer.id,
            other.id != AnswerComment.id,
        ),
    )
    rows = await db.execute(
        select(
            AnswerComment,
            Assignment,
            Vignette.code,
            User.role,
            User.pseudonym,
            in_my_thread,
        )
        .join(Assignment, Assignment.id == AnswerComment.assignment_id)
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
        .join(User, User.id == AnswerComment.author_id)
        .where(
            AnswerComment.author_id != viewer.id,
            or_(Assignment.expert_id == viewer.id, in_my_thread),
        )
        .order_by(AnswerComment.created_at.desc())
        .limit(ACTIVITY)
    )
    as_actor = Actor.ADMIN if viewer.role == Role.ADMIN else Actor.REVIEWER
    items = []
    for comment, assignment, code, role, pseudonym, in_thread in rows:
        body = comment.body.strip()
        items.append(
            (
                comment.created_at,
                ActivityItem(
                    kind="reply" if in_thread else "comment_on_mine",
                    assignment_id=assignment.id,
                    vignette_code=code,
                    at=comment.created_at,
                    unread=False,
                    question_id=comment.question_id,
                    comment_id=comment.id,
                    speaker=reviews.speaker_for(
                        assignment,
                        as_actor,
                        user_id=comment.author_id,
                        role=role,
                        pseudonym=pseudonym,
                    ),
                    excerpt=body if len(body) <= EXCERPT else body[: EXCERPT - 1] + "…",
                ),
            )
        )
    return items


async def _activity(db: AsyncSession, viewer: User) -> list[ActivityItem]:
    merged = await _workflow_activity(db, viewer) + await _comment_activity(db, viewer)
    merged.sort(key=lambda pair: pair[0], reverse=True)
    seen = viewer.activity_seen_at
    return [
        item.model_copy(update={"unread": seen is None or item.at > seen})
        for _, item in merged[:ACTIVITY]
    ]


async def system_status(db: AsyncSession) -> SystemStatus:
    seen = await compute.latest()
    now = utcnow()
    rows = (
        await db.execute(
            select(Job.kind, Job.created_at).where(
                or_(
                    Job.status == JobStatus.QUEUED,
                    (Job.status == JobStatus.RUNNING) & (Job.locked_until < now),
                )
            )
        )
    ).all()
    for_pc = [seen is not None and compute.blocked(seen, kind) for kind, _ in rows]
    stuck = timedelta(minutes=STUCK_MINUTES)
    failed = await db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.status == JobStatus.FAILED, Job.created_at > now - timedelta(days=1))
    )
    return SystemStatus(
        compute=None
        if seen is None
        else ComputeStatus(
            missing=compute.missing_now(seen),
            checked_seconds_ago=round(time.monotonic() - seen.at),
        ),
        waiting=len(rows),
        waiting_for_pc=sum(for_pc),
        oldest_waiting_minutes=(
            int((now - min(at for _, at in rows)).total_seconds() // 60) if rows else None
        ),
        stuck=any(
            now - at > stuck for (_, at), blocked in zip(rows, for_pc, strict=True) if not blocked
        ),
        failed_last_day=failed or 0,
    )


async def home(db: AsyncSession, viewer: User) -> HomeView:
    next_up, total = await _next_up(db, viewer)
    open_reviews = await reviews.list_reviews(db, viewer, status="open")
    waiting = [
        item
        for item in open_reviews
        if viewer.role == Role.ADMIN
        or (item.relation == "reviewer" and item.my_votes < item.answer_count)
    ]
    activity = await _activity(db, viewer)
    return HomeView(
        next_up=next_up,
        next_up_total=total,
        reviews_waiting=waiting[:WAITING],
        reviews_waiting_total=len(waiting),
        recent_reviews=await reviews.list_reviews(db, viewer, limit=RECENT),
        activity=activity,
        unread_activity=sum(item.unread for item in activity),
        system=await system_status(db) if viewer.role == Role.ADMIN else None,
    )


def mark_seen(viewer: User, until: datetime | None) -> None:
    """Never moves backwards, and never into the future."""
    now = utcnow()
    stamp = now if until is None else min(until, now)
    if viewer.activity_seen_at is None or stamp > viewer.activity_seen_at:
        viewer.activity_seen_at = stamp


__all__ = ["home", "mark_seen"]
