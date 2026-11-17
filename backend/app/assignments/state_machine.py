"""The workflow: which action moves an assignment where, and who may do it.

`transition` is the only place that changes `Assignment.state`. In one transaction, it updates the
state, records the audit event and queues the job of the new state. The caller holds the row lock
(`lock_assignment`) and commits.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment
from app.assignments.states import Action, Actor, State
from app.audit.service import record_event
from app.compute import require_compute
from app.core.errors import DomainError, forbidden, not_found
from app.jobs.models import Job, JobKind


@dataclass(frozen=True)
class Rule:
    to: State
    actors: frozenset[Actor]


def _rule(to: State, *actors: Actor) -> Rule:
    return Rule(to, frozenset(actors))


TRANSITIONS: dict[tuple[State, Action], Rule] = {
    (State.ASSIGNED, Action.START): _rule(State.IN_PROGRESS, Actor.ASSIGNEE),
    (State.ASSIGNED, Action.CANCEL): _rule(State.CANCELLED, Actor.ADMIN),
    (State.IN_PROGRESS, Action.CANCEL): _rule(State.CANCELLED, Actor.ADMIN),
    (State.IN_PROGRESS, Action.SUBMIT): _rule(State.PROOFREADING, Actor.ASSIGNEE),
    (State.PROOFREADING, Action.PROOFREAD_SUCCEEDED): _rule(State.PROOFREAD_CHECK, Actor.SYSTEM),
    (State.PROOFREADING, Action.PROOFREAD_FAILED): _rule(State.PROCESSING_FAILED, Actor.SYSTEM),
    # Every colleague who may read it can see the answers at once; see reviews/access.py.
    (State.PROOFREAD_CHECK, Action.CANCEL): _rule(State.CANCELLED, Actor.ADMIN),
    (State.PROOFREAD_CHECK, Action.SUBMIT_FOR_REVIEW): _rule(State.PEER_REVIEW, Actor.ASSIGNEE),
    # Peers discuss and vote, but only the admin closes a review. Only the admin sends answers
    # back to the author, who edits them for a new round.
    (State.PEER_REVIEW, Action.CANCEL): _rule(State.CANCELLED, Actor.ADMIN),
    (State.PEER_REVIEW, Action.APPROVE_ANSWERS): _rule(State.PROCESSING, Actor.ADMIN),
    (State.PEER_REVIEW, Action.REJECT_ALL_ANSWERS): _rule(State.REJECTED, Actor.ADMIN),
    (State.PEER_REVIEW, Action.REQUEST_CHANGES): _rule(State.PROOFREAD_CHECK, Actor.ADMIN),
    (State.PROCESSING, Action.PROCESSING_SUCCEEDED): _rule(State.INGESTING, Actor.SYSTEM),
    (State.PROCESSING, Action.PROCESSING_FAILED): _rule(State.PROCESSING_FAILED, Actor.SYSTEM),
    # `processing_failed` is shared by two jobs: `retry` runs the one that failed again.
    (State.PROCESSING_FAILED, Action.RETRY_PROOFREAD): _rule(State.PROOFREADING, Actor.ADMIN),
    (State.PROCESSING_FAILED, Action.RETRY_PROCESSING): _rule(State.PROCESSING, Actor.ADMIN),
    (State.INGESTING, Action.INGESTION_SUCCEEDED): _rule(State.INGESTED, Actor.SYSTEM),
    (State.INGESTING, Action.INGESTION_FAILED): _rule(State.INGESTION_FAILED, Actor.SYSTEM),
    (State.INGESTION_FAILED, Action.RETRY_INGESTION): _rule(State.INGESTING, Actor.ADMIN),
}

JOB_ON_ENTRY: dict[State, JobKind] = {
    State.PROOFREADING: JobKind.PROOFREAD,
    State.PROCESSING: JobKind.PROCESS,
    State.INGESTING: JobKind.INGEST,
}

# The name each workflow action has in `allowed_actions`.
USER_ACTION_NAMES: dict[Action, str] = {
    Action.START: "start",
    Action.CANCEL: "cancel",
    Action.SUBMIT: "submit",
    Action.SUBMIT_FOR_REVIEW: "submit_for_review",
    Action.RETRY_PROOFREAD: "retry",
    Action.RETRY_PROCESSING: "retry",
    Action.RETRY_INGESTION: "retry",
    Action.APPROVE_ANSWERS: "decide_answers",
    Action.REJECT_ALL_ANSWERS: "decide_answers",
    Action.REQUEST_CHANGES: "decide_answers",
}


def check_transition(state: State, action: Action, actor: Actor) -> Rule:
    rule = TRANSITIONS.get((state, action))
    if rule is None:
        raise DomainError(
            "illegal_transition",
            f"{action.value} isn't possible while the assignment is {state.value}.",
            details={"state": state.value, "action": action.value},
        )
    if actor not in rule.actors:
        raise forbidden()
    return rule


def user_actions(state: State, actor: Actor) -> set[str]:
    return {
        USER_ACTION_NAMES[action]
        for (from_state, action), rule in TRANSITIONS.items()
        if from_state == state and actor in rule.actors and action in USER_ACTION_NAMES
    }


async def lock_assignment(db: AsyncSession, assignment_id: UUID) -> Assignment:
    assignment = await db.scalar(
        select(Assignment)
        .where(Assignment.id == assignment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if assignment is None:
        raise not_found("Assignment")
    return assignment


async def transition(
    db: AsyncSession,
    assignment: Assignment,
    action: Action,
    actor: Actor,
    actor_id: UUID | None,
    meta: dict[str, Any] | None = None,
) -> None:
    rule = check_transition(assignment.state, action, actor)
    job_kind = JOB_ON_ENTRY.get(rule.to)
    if job_kind is not None and actor != Actor.SYSTEM:
        # Before anything changes: a 503 leaves the assignment where it was. It reads the last
        # probe, no network wait under the row lock. The worker's own moves are not checked here:
        # the worker holds back a job whose machine is down (app/jobs/worker.py).
        await require_compute(job_kind)
    previous = assignment.state
    assignment.state = rule.to
    record_event(
        db,
        actor_id=actor_id,
        entity_type="assignment",
        entity_id=assignment.id,
        action=action.value,
        from_state=previous.value,
        to_state=rule.to.value,
        meta=meta,
    )
    if job_kind is not None:
        db.add(Job(kind=job_kind, assignment_id=assignment.id))
