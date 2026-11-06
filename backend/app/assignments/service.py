from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import String, cast, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.answers import (
    PAYLOAD_FORMAT,
    AnswerPayload,
    check_draft,
    check_gate_answers,
    clean_submission,
    gate_questions,
)
from app.assignments.models import AnswerDraft, Assignment, Submission
from app.assignments.schemas import (
    AdminAssignment,
    AssignmentSummary,
    DraftSaved,
    DraftView,
    EventAdminView,
    EventAuthorView,
    ExpertAssignment,
    ExpertVignette,
    PeerAssignment,
    PeerVignette,
    QuestionView,
)
from app.assignments.state_machine import (
    check_transition,
    lock_assignment,
    transition,
    user_actions,
)
from app.assignments.states import JOB_STATES, Action, Actor, State
from app.audit.models import AuditEvent
from app.audit.service import record_event
from app.core.db import utcnow
from app.core.errors import DomainError, invalid, not_found
from app.jobs.models import Job, JobKind, JobStatus
from app.reviews.models import ReviewRequest, ReviewStage
from app.users.models import Role, User
from app.vignettes.models import VersionStatus, Vignette, VignetteVersion
from app.vignettes.questions import GATE, Q4_WORDING, QUESTIONS, render_question


def gate_open(assignment: Assignment, version: VignetteVersion) -> bool:
    return assignment.gate_passed_at is not None or not gate_questions(version.question_ids)


def allowed_actions(
    state: State,
    actor: Actor,
    *,
    gate_is_open: bool,
    has_open_request: bool,
    peers_used: bool,
) -> list[str]:
    names = user_actions(state, actor)
    if state == State.IN_PROGRESS and actor == Actor.ASSIGNEE:
        names.add("save_draft")
        if not gate_is_open:
            names.add("pass_gate")
            names.discard("submit")
    if actor == Actor.REVIEWER and not has_open_request:
        names.discard("decide_units")
    if peers_used:
        names.discard("request_peers")
    return sorted(names)


# --- access ---------------------------------------------------------------------------------


async def actor_for(db: AsyncSession, assignment: Assignment, viewer: User) -> Actor:
    """How the viewer relates to the assignment. Unrelated viewers get a 404, not a 403."""
    if viewer.role == Role.ADMIN:
        return Actor.ADMIN
    if assignment.expert_id == viewer.id:
        return Actor.ASSIGNEE
    request = await db.scalar(
        select(ReviewRequest.id).where(
            ReviewRequest.assignment_id == assignment.id,
            ReviewRequest.reviewer_id == viewer.id,
            ReviewRequest.stage == ReviewStage.PEER,
        )
    )
    if request is not None:
        return Actor.REVIEWER
    raise not_found("Assignment")


async def load(db: AsyncSession, assignment_id: UUID, viewer: User) -> tuple[Assignment, Actor]:
    assignment = await db.get(Assignment, assignment_id)
    if assignment is None:
        raise not_found("Assignment")
    return assignment, await actor_for(db, assignment, viewer)


async def lock(db: AsyncSession, assignment_id: UUID, viewer: User) -> tuple[Assignment, Actor]:
    assignment = await lock_assignment(db, assignment_id)
    return assignment, await actor_for(db, assignment, viewer)


# --- views ----------------------------------------------------------------------------------


def _visible_questions(version: VignetteVersion, is_open: bool) -> list[QuestionView]:
    views = []
    for question_id in version.question_ids:
        if not is_open and question_id not in GATE:
            continue
        question = QUESTIONS[question_id]
        views.append(
            QuestionView(
                id=question.id,
                kind=question.kind,
                text=render_question(question, version.q4_whatif),
                wording=Q4_WORDING if question.id == "Q4" else None,
            )
        )
    return views


async def _version_and_code(db: AsyncSession, version_id: UUID) -> tuple[VignetteVersion, str]:
    row = (
        await db.execute(
            select(VignetteVersion, Vignette.code)
            .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
            .where(VignetteVersion.id == version_id)
        )
    ).one()
    return row[0], row[1]


async def _peers_used(db: AsyncSession, assignment_id: UUID) -> bool:
    found = await db.scalar(
        select(ReviewRequest.id)
        .where(
            ReviewRequest.assignment_id == assignment_id,
            ReviewRequest.stage == ReviewStage.PEER,
        )
        .limit(1)
    )
    return found is not None


async def _has_open_request(db: AsyncSession, assignment_id: UUID, viewer_id: UUID) -> bool:
    found = await db.scalar(
        select(ReviewRequest.id).where(
            ReviewRequest.assignment_id == assignment_id,
            ReviewRequest.reviewer_id == viewer_id,
            ReviewRequest.stage == ReviewStage.PEER,
            ReviewRequest.completed_at.is_(None),
        )
    )
    return found is not None


async def build_view(
    db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User
) -> ExpertAssignment | AdminAssignment | PeerAssignment:
    version, code = await _version_and_code(db, assignment.vignette_version_id)
    is_open = gate_open(assignment, version)
    actions = allowed_actions(
        assignment.state,
        actor,
        gate_is_open=is_open,
        has_open_request=actor == Actor.REVIEWER
        and await _has_open_request(db, assignment.id, viewer.id),
        peers_used=actor == Actor.ADMIN and await _peers_used(db, assignment.id),
    )
    words = len(version.text.split())
    if actor == Actor.ASSIGNEE:
        draft = await db.get(AnswerDraft, assignment.id)
        return ExpertAssignment(
            id=assignment.id,
            state=assignment.state,
            allowed_actions=actions,
            updated_at=assignment.updated_at,
            vignette=ExpertVignette(
                code=code,
                version=version.version,
                text=version.text,
                framing=version.framing,  # ty: ignore[invalid-argument-type]
                word_count=words,
                content_hash=version.content_hash,
                questions=_visible_questions(version, is_open),
            ),
            draft=DraftView(
                version=draft.version,
                payload=AnswerPayload.model_validate(draft.payload),
                updated_at=draft.updated_at,
            )
            if draft
            else None,
            gate_passed_at=assignment.gate_passed_at,
            locked_highlights=assignment.locked_highlights,
            started_at=assignment.started_at,
            submitted_at=assignment.submitted_at,
        )
    if actor == Actor.REVIEWER:
        return PeerAssignment(
            id=assignment.id,
            state=assignment.state,
            allowed_actions=actions,
            updated_at=assignment.updated_at,
            vignette=PeerVignette(
                code=code,
                version=version.version,
                text=version.text,
                framing=version.framing,  # ty: ignore[invalid-argument-type]
                word_count=words,
            ),
        )
    expert = await db.get(User, assignment.expert_id)
    assert expert is not None
    return AdminAssignment(
        id=assignment.id,
        state=assignment.state,
        allowed_actions=actions,
        updated_at=assignment.updated_at,
        expert_id=assignment.expert_id,
        expert_pseudonym=expert.pseudonym,
        vignette_code=code,
        vignette_version=version.version,
        vignette_version_id=version.id,
        required_approvals=assignment.required_approvals,
        gate_passed_at=assignment.gate_passed_at,
        started_at=assignment.started_at,
        submitted_at=assignment.submitted_at,
    )


async def list_assignments(
    db: AsyncSession,
    viewer: User,
    *,
    state: State | None,
    vignette_version_id: UUID | None = None,
    limit: int,
    offset: int,
) -> list[AssignmentSummary]:
    """An expert's own list has a stable pseudo-random order, so a resumed session looks the same.
    The admin sees everything, most recently changed first."""
    query = (
        select(Assignment, VignetteVersion, Vignette.code, User.pseudonym)
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
        .join(User, User.id == Assignment.expert_id)
    )
    is_admin = viewer.role == Role.ADMIN
    if is_admin:
        query = query.order_by(Assignment.updated_at.desc(), Assignment.id)
    else:
        query = query.where(Assignment.expert_id == viewer.id).order_by(
            func.md5(cast(Assignment.expert_id, String) + cast(Vignette.id, String)),
            VignetteVersion.version,
        )
    if state is not None:
        query = query.where(Assignment.state == state)
    if vignette_version_id is not None:
        query = query.where(Assignment.vignette_version_id == vignette_version_id)
    rows = (await db.execute(query.limit(limit).offset(offset))).all()
    used = await _assignments_with_peers(db, [row[0].id for row in rows]) if is_admin else set()
    actor = Actor.ADMIN if is_admin else Actor.ASSIGNEE
    return [
        AssignmentSummary(
            id=assignment.id,
            state=assignment.state,
            allowed_actions=allowed_actions(
                assignment.state,
                actor,
                gate_is_open=gate_open(assignment, version),
                has_open_request=False,
                peers_used=assignment.id in used,
            ),
            job_running=assignment.state in JOB_STATES,
            vignette_code=code,
            vignette_version=version.version,
            vignette_version_id=version.id,
            expert_pseudonym=pseudonym,
            updated_at=assignment.updated_at,
        )
        for assignment, version, code, pseudonym in rows
    ]


async def _assignments_with_peers(db: AsyncSession, ids: Iterable[UUID]) -> set[UUID]:
    rows = await db.scalars(
        select(ReviewRequest.assignment_id)
        .where(ReviewRequest.assignment_id.in_(list(ids)), ReviewRequest.stage == ReviewStage.PEER)
        .distinct()
    )
    return set(rows)


# --- assigning ------------------------------------------------------------------------------


async def assign(
    db: AsyncSession, version_id: UUID, expert_ids: list[UUID], admin: User
) -> list[Assignment]:
    version = await db.scalar(
        select(VignetteVersion).where(VignetteVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise not_found("Vignette version")
    if version.status != VersionStatus.PUBLISHED:
        raise DomainError("version_not_published", "Only a published version can be assigned.")

    unique_ids = list(dict.fromkeys(expert_ids))
    experts = list(await db.scalars(select(User).where(User.id.in_(unique_ids))))
    usable = {e.id for e in experts if e.role == Role.EXPERT and e.is_active}
    if missing := [str(i) for i in unique_ids if i not in usable]:
        raise invalid(
            "invalid_assignee", "Only active experts can be assigned.", {"expert_ids": missing}
        )
    # Reading a colleague's answers first would contaminate the expert's own reading.
    reviewed = await db.scalars(
        select(ReviewRequest.reviewer_id)
        .join(Assignment, Assignment.id == ReviewRequest.assignment_id)
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .where(
            ReviewRequest.reviewer_id.in_(unique_ids),
            ReviewRequest.stage == ReviewStage.PEER,
            VignetteVersion.vignette_id == version.vignette_id,
        )
        .distinct()
    )
    if contaminated := [str(i) for i in reviewed]:
        raise DomainError(
            "reviewer_contaminated",
            "These experts have already reviewed answers to this vignette.",
            details={"expert_ids": contaminated},
        )

    assignments = [
        Assignment(vignette_version_id=version.id, expert_id=expert_id, assigned_by=admin.id)
        for expert_id in unique_ids
    ]
    db.add_all(assignments)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise DomainError(
            "already_assigned", "An expert already has this vignette version."
        ) from exc
    for assignment in assignments:
        record_event(
            db,
            actor_id=admin.id,
            entity_type="assignment",
            entity_id=assignment.id,
            action="assigned",
            to_state=State.ASSIGNED.value,
        )
    return assignments


# --- answering ------------------------------------------------------------------------------


async def start(db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User) -> None:
    await transition(db, assignment, Action.START, actor, viewer.id)
    assignment.started_at = utcnow()
    db.add(
        AnswerDraft(assignment_id=assignment.id, payload=AnswerPayload().model_dump(mode="json"))
    )


def _require_own_in_progress(assignment: Assignment, actor: Actor) -> None:
    if actor != Actor.ASSIGNEE:
        raise DomainError("forbidden", "Only the assigned expert can answer.", 403)
    if assignment.state != State.IN_PROGRESS:
        raise DomainError(
            "not_editable",
            "The answers can only be changed while the assignment is in progress.",
            details={"state": assignment.state.value},
        )


async def _draft(db: AsyncSession, assignment: Assignment) -> AnswerDraft:
    draft = await db.get(AnswerDraft, assignment.id)
    assert draft is not None, "an in-progress assignment always has a draft"
    return draft


async def save_draft(
    db: AsyncSession, assignment: Assignment, actor: Actor, based_on: int, payload: AnswerPayload
) -> DraftSaved:
    _require_own_in_progress(assignment, actor)
    draft = await _draft(db, assignment)
    if draft.version != based_on:
        raise DomainError(
            "draft_conflict",
            "This draft was saved elsewhere. Reload it before continuing.",
            details={"current_version": draft.version},
        )
    version, _ = await _version_and_code(db, assignment.vignette_version_id)
    check_draft(
        payload,
        AnswerPayload.model_validate(draft.payload),
        version.question_ids,
        assignment.gate_passed_at is not None,
        version.text,
        assignment.locked_highlights,
    )
    draft.payload = payload.model_dump(mode="json")
    draft.version += 1
    draft.updated_at = utcnow()
    return DraftSaved(version=draft.version, updated_at=draft.updated_at)


async def pass_gate(db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User) -> None:
    """Idempotent: a double click must not fail, and the first time recorded stands."""
    _require_own_in_progress(assignment, actor)
    if assignment.gate_passed_at is not None:
        return
    draft = await _draft(db, assignment)
    version, _ = await _version_and_code(db, assignment.vignette_version_id)
    payload = AnswerPayload.model_validate(draft.payload)
    check_gate_answers(payload, version.question_ids)
    assignment.gate_passed_at = utcnow()
    assignment.locked_highlights = len(payload.highlights)
    record_event(
        db,
        actor_id=viewer.id,
        entity_type="assignment",
        entity_id=assignment.id,
        action="gate_passed",
    )


async def submit(db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User) -> None:
    check_transition(assignment.state, Action.SUBMIT, actor)
    draft = await _draft(db, assignment)
    version, code = await _version_and_code(db, assignment.vignette_version_id)
    if not gate_open(assignment, version):
        raise invalid("gate_not_passed", "Q1-Q3 need answers first.")
    clean = clean_submission(
        AnswerPayload.model_validate(draft.payload), version.question_ids, version.text
    )
    now = utcnow()
    assignment.submitted_at = now
    db.add(
        Submission(
            assignment_id=assignment.id,
            payload_format=PAYLOAD_FORMAT,
            vignette_hash=version.content_hash,
            submitted_at=now,
            payload={
                **clean.model_dump(mode="json"),
                "vignette_code": code,
                "vignette_version": version.version,
                "expert_pseudonym": viewer.pseudonym,
                "is_synthetic": viewer.is_synthetic,
                "started_at": assignment.started_at.isoformat() if assignment.started_at else None,
                "gate_passed_at": (
                    assignment.gate_passed_at.isoformat() if assignment.gate_passed_at else None
                ),
                # Tells the citations made before the what-if was seen from those made after it.
                "locked_highlights": assignment.locked_highlights,
                "submitted_at": now.isoformat(),
            },
        )
    )
    await transition(db, assignment, Action.SUBMIT, actor, viewer.id)


async def get_submission(db: AsyncSession, assignment: Assignment, actor: Actor) -> Submission:
    """The raw answers are for their author and the admin. Peers review units only."""
    if actor == Actor.REVIEWER:
        raise not_found("Submission")
    submission = await db.get(Submission, assignment.id)
    if submission is None:
        raise not_found("Submission")
    return submission


# --- retry ----------------------------------------------------------------------------------


RETRY_BY_JOB = {
    JobKind.PROCESS: Action.RETRY_PROCESSING,
    JobKind.BUILD_UNITS: Action.RETRY_UNITS,
    JobKind.INGEST: Action.RETRY_INGESTION,
}


async def retry(db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User) -> None:
    """Run the job that failed again. `processing_failed` is shared by two jobs."""
    kind = await db.scalar(
        select(Job.kind)
        .where(Job.assignment_id == assignment.id, Job.status == JobStatus.FAILED)
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if kind is None:
        raise DomainError(
            "illegal_transition",
            f"Nothing to retry while the assignment is {assignment.state.value}.",
            details={"state": assignment.state.value, "action": "retry"},
        )
    await transition(db, assignment, RETRY_BY_JOB[kind], actor, viewer.id)


# --- timeline -------------------------------------------------------------------------------


async def events(
    db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User
) -> list[EventAdminView | EventAuthorView]:
    if actor == Actor.REVIEWER:
        raise not_found("Assignment")
    rows = await db.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_type == "assignment", AuditEvent.entity_id == assignment.id)
        .order_by(AuditEvent.at, AuditEvent.id)
    )
    if actor == Actor.ADMIN:
        return [
            EventAdminView(
                action=event.action,
                from_state=event.from_state,
                to_state=event.to_state,
                at=event.at,
                actor_id=event.actor_id,
                meta=event.meta,
            )
            for event in rows
        ]
    views: list[EventAdminView | EventAuthorView] = []
    for event in rows:
        views.append(
            EventAuthorView(
                action=event.action,
                from_state=event.from_state,
                to_state=event.to_state,
                at=event.at,
                actor=_author_sees_actor(event, viewer),
            )
        )
    return views


def _author_sees_actor(event: AuditEvent, viewer: User):
    if event.actor_id is None:
        return "system"
    if event.actor_id == viewer.id:
        return "you"
    if event.action in {Action.PEERS_APPROVED.value, Action.PEER_REJECTED.value}:
        return "reviewer"
    return "admin"
