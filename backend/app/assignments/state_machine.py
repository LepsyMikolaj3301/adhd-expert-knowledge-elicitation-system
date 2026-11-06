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
    (State.IN_PROGRESS, Action.SUBMIT): _rule(State.PROCESSING, Actor.ASSIGNEE),
    (State.PROCESSING, Action.PROCESSING_SUCCEEDED): _rule(State.EXPERT_CHECK, Actor.SYSTEM),
    (State.PROCESSING, Action.PROCESSING_FAILED): _rule(State.PROCESSING_FAILED, Actor.SYSTEM),
    (State.EXPERT_CHECK, Action.COMPLETE_EXPERT_CHECK): _rule(State.BUILDING_UNITS, Actor.ASSIGNEE),
    (State.EXPERT_CHECK, Action.SKIP_EXPERT_CHECK): _rule(
        State.BUILDING_UNITS, Actor.ASSIGNEE, Actor.ADMIN
    ),
    # Every colleague who may read it can see the units at once; see reviews/access.py.
    (State.BUILDING_UNITS, Action.UNITS_BUILT): _rule(State.PEER_REVIEW, Actor.SYSTEM),
    (State.BUILDING_UNITS, Action.UNITS_FAILED): _rule(State.PROCESSING_FAILED, Actor.SYSTEM),
    (State.PROCESSING_FAILED, Action.RETRY_PROCESSING): _rule(State.PROCESSING, Actor.ADMIN),
    (State.PROCESSING_FAILED, Action.RETRY_UNITS): _rule(State.BUILDING_UNITS, Actor.ADMIN),
    # Peers discuss and vote, but only the admin closes a review. Only the admin sends units back
    # to the author, who corrects the filing for a new round.
    (State.PEER_REVIEW, Action.APPROVE_UNITS): _rule(State.INGESTING, Actor.ADMIN),
    (State.PEER_REVIEW, Action.REJECT_ALL_UNITS): _rule(State.REJECTED, Actor.ADMIN),
    (State.PEER_REVIEW, Action.REQUEST_CHANGES): _rule(State.EXPERT_CHECK, Actor.ADMIN),
    (State.INGESTING, Action.INGESTION_SUCCEEDED): _rule(State.INGESTED, Actor.SYSTEM),
    (State.INGESTING, Action.INGESTION_FAILED): _rule(State.INGESTION_FAILED, Actor.SYSTEM),
    (State.INGESTION_FAILED, Action.RETRY_INGESTION): _rule(State.INGESTING, Actor.ADMIN),
}

JOB_ON_ENTRY: dict[State, JobKind] = {
    State.PROCESSING: JobKind.PROCESS,
    State.BUILDING_UNITS: JobKind.BUILD_UNITS,
    State.INGESTING: JobKind.INGEST,
}

# The name each workflow action has in `allowed_actions`.
USER_ACTION_NAMES: dict[Action, str] = {
    Action.START: "start",
    Action.CANCEL: "cancel",
    Action.SUBMIT: "submit",
    Action.COMPLETE_EXPERT_CHECK: "complete_expert_check",
    Action.SKIP_EXPERT_CHECK: "skip_expert_check",
    Action.RETRY_PROCESSING: "retry",
    Action.RETRY_UNITS: "retry",
    Action.RETRY_INGESTION: "retry",
    Action.APPROVE_UNITS: "decide_units",
    Action.REJECT_ALL_UNITS: "decide_units",
    Action.REQUEST_CHANGES: "decide_units",
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
    job_kind = JOB_ON_ENTRY.get(rule.to)
    if job_kind is not None:
        db.add(Job(kind=job_kind, assignment_id=assignment.id))
