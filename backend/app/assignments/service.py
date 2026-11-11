from uuid import UUID

from sqlalchemy import String, cast, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.answers import (
    PAYLOAD_FORMAT,
    AnswerPayload,
    check_draft,
    clean_submission,
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
from app.reviews import access
from app.reviews.models import ReviewParticipant
from app.users.models import Role, User
from app.vignettes.models import VersionStatus, Vignette, VignetteVersion
from app.vignettes.questions import Q4_WORDING, QUESTIONS, render_question
from app.vignettes.service import opening_words

# Events of the discussion, which the author's timeline leaves out: it is for the workflow.
REVIEW_CHATTER = ("review_opened", "comment_added", "vote_cast")
# What peers' decisions were called before reviews were open. Old events keep these names.
LEGACY_PEER_ACTIONS = frozenset({"peers_approved", "peer_rejected"})


def allowed_actions(state: State, actor: Actor) -> list[str]:
    names = user_actions(state, actor)
    if state == State.IN_PROGRESS and actor == Actor.ASSIGNEE:
        names.add("save_draft")
    if state == State.PROOFREAD_CHECK and actor == Actor.ASSIGNEE:
        names.add("edit_proofread")
    if state == State.PEER_REVIEW:
        names.add("comment")  # the author, the reviewers and the admin all talk
        if actor == Actor.REVIEWER:
            names.add("vote")
    return sorted(names)


# --- access ---------------------------------------------------------------------------------


async def actor_for(db: AsyncSession, assignment: Assignment, viewer: User) -> Actor:
    """How the viewer relates to the assignment. Unrelated viewers get a 404, not a 403."""
    if viewer.role == Role.ADMIN:
        return Actor.ADMIN
    if assignment.expert_id == viewer.id:
        return Actor.ASSIGNEE
    if await access.may_review(db, assignment, viewer):
        return Actor.REVIEWER
    raise not_found("Assignment")


async def _require_opened(
    db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User
) -> None:
    """A reviewer reads nothing before agreeing to: reading is what rules them out of the vignette
    later, and `GET`s must not do that on their own."""
    if actor == Actor.REVIEWER and not await access.has_opened(db, assignment.id, viewer.id):
        raise DomainError(
            "review_not_opened",
            "Open the review first. Reading it means you can't be assigned this vignette later.",
        )


async def load(
    db: AsyncSession, assignment_id: UUID, viewer: User, *, allow_unopened: bool = False
) -> tuple[Assignment, Actor]:
    assignment = await db.get(Assignment, assignment_id)
    if assignment is None:
        raise not_found("Assignment")
    actor = await actor_for(db, assignment, viewer)
    if not allow_unopened:
        await _require_opened(db, assignment, actor, viewer)
    return assignment, actor


async def lock(
    db: AsyncSession, assignment_id: UUID, viewer: User, *, allow_unopened: bool = False
) -> tuple[Assignment, Actor]:
    assignment = await lock_assignment(db, assignment_id)
    actor = await actor_for(db, assignment, viewer)
    if not allow_unopened:
        await _require_opened(db, assignment, actor, viewer)
    return assignment, actor


# --- views ----------------------------------------------------------------------------------


def _visible_questions(version: VignetteVersion) -> list[QuestionView]:
    views = []
    for question_id in version.question_ids:
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


async def build_view(
    db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User
) -> ExpertAssignment | AdminAssignment | PeerAssignment:
    version, code = await _version_and_code(db, assignment.vignette_version_id)
    actions = allowed_actions(assignment.state, actor)
    words = len(version.text.split())
    if actor == Actor.ASSIGNEE:
        draft = await db.get(AnswerDraft, assignment.id)
        return ExpertAssignment(
            id=assignment.id,
            state=assignment.state,
            review_round=assignment.review_round,
            allowed_actions=actions,
            updated_at=assignment.updated_at,
            vignette=ExpertVignette(
                code=code,
                version=version.version,
                text=version.text,
                framing=version.framing,  # ty: ignore[invalid-argument-type]
                patient_summary=version.patient_summary,
                word_count=words,
                content_hash=version.content_hash,
                questions=_visible_questions(version),
            ),
            draft=DraftView(
                version=draft.version,
                payload=AnswerPayload.model_validate(draft.payload),
                updated_at=draft.updated_at,
            )
            if draft
            else None,
            started_at=assignment.started_at,
            submitted_at=assignment.submitted_at,
        )
    if actor == Actor.REVIEWER:
        return PeerAssignment(
            id=assignment.id,
            state=assignment.state,
            review_round=assignment.review_round,
            allowed_actions=actions,
            updated_at=assignment.updated_at,
            vignette=PeerVignette(
                code=code,
                version=version.version,
                text=version.text,
                framing=version.framing,  # ty: ignore[invalid-argument-type]
                patient_summary=version.patient_summary,
                word_count=words,
            ),
        )
    expert = await db.get(User, assignment.expert_id)
    assert expert is not None
    return AdminAssignment(
        id=assignment.id,
        state=assignment.state,
        review_round=assignment.review_round,
        allowed_actions=actions,
        updated_at=assignment.updated_at,
        expert_id=assignment.expert_id,
        expert_pseudonym=expert.pseudonym,
        vignette_code=code,
        vignette_version=version.version,
        vignette_version_id=version.id,
        vignette=PeerVignette(
            code=code,
            version=version.version,
            text=version.text,
            framing=version.framing,  # ty: ignore[invalid-argument-type]
            patient_summary=version.patient_summary,
            word_count=words,
        ),
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
    actor = Actor.ADMIN if is_admin else Actor.ASSIGNEE
    return [
        AssignmentSummary(
            id=assignment.id,
            state=assignment.state,
            allowed_actions=allowed_actions(assignment.state, actor),
            job_running=assignment.state in JOB_STATES,
            vignette_code=code,
            vignette_version=version.version,
            vignette_version_id=version.id,
            expert_id=assignment.expert_id,
            expert_pseudonym=pseudonym,
            patient_summary=version.patient_summary,
            framing=version.framing,  # ty: ignore[invalid-argument-type]
            word_count=len(version.text.split()),
            opening=opening_words(version.text),
            updated_at=assignment.updated_at,
        )
        for assignment, version, code, pseudonym in rows
    ]


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
        select(ReviewParticipant.expert_id)
        .join(Assignment, Assignment.id == ReviewParticipant.assignment_id)
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .where(
            ReviewParticipant.expert_id.in_(unique_ids),
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
    check_draft(payload, version.question_ids, version.text)
    draft.payload = payload.model_dump(mode="json")
    draft.version += 1
    draft.updated_at = utcnow()
    return DraftSaved(version=draft.version, updated_at=draft.updated_at)


async def submit(db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User) -> None:
    check_transition(assignment.state, Action.SUBMIT, actor)
    draft = await _draft(db, assignment)
    version, code = await _version_and_code(db, assignment.vignette_version_id)
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
                "submitted_at": now.isoformat(),
            },
        )
    )
    await transition(db, assignment, Action.SUBMIT, actor, viewer.id)


async def get_submission(db: AsyncSession, assignment: Assignment, actor: Actor) -> Submission:
    """The raw answers are for their author and the admin. Peers read the edited answers."""
    if actor == Actor.REVIEWER:
        raise not_found("Submission")
    submission = await db.get(Submission, assignment.id)
    if submission is None:
        raise not_found("Submission")
    return submission


# --- retry ----------------------------------------------------------------------------------


RETRY_BY_JOB = {
    JobKind.PROOFREAD: Action.RETRY_PROOFREAD,
    JobKind.PROCESS: Action.RETRY_PROCESSING,
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
    query = select(AuditEvent).where(
        AuditEvent.entity_type == "assignment", AuditEvent.entity_id == assignment.id
    )
    if actor != Actor.ADMIN:
        query = query.where(AuditEvent.action.not_in(REVIEW_CHATTER))
    rows = await db.scalars(query.order_by(AuditEvent.at, AuditEvent.id))
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
    if event.action in LEGACY_PEER_ACTIONS:
        return "reviewer"
    return "admin"
