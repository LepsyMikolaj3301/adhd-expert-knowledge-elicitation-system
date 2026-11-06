from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment, Submission
from app.assignments.state_machine import check_transition, transition
from app.assignments.states import Action, Actor, State
from app.core.db import utcnow
from app.core.errors import DomainError, invalid
from app.knowledge.models import AnswerFindings, KnowledgeUnit, UnitStatus
from app.reviews.models import DecisionValue, ReviewRequest, ReviewStage, UnitDecision
from app.reviews.schemas import (
    DecisionView,
    ReviewQueueItem,
    UnitAdminView,
    UnitAuthorView,
    UnitDecisionInput,
    UnitPeerView,
)
from app.users.models import Role, User
from app.vignettes.models import Vignette, VignetteVersion

PRE_SUBMISSION_STATES = (State.ASSIGNED, State.IN_PROGRESS)


async def _units(
    db: AsyncSession, assignment: Assignment, review_round: int | None = None
) -> list[KnowledgeUnit]:
    """The units of the assignment's current round, or of another one (the admin's history)."""
    wanted = assignment.review_round if review_round is None else review_round
    return list(
        await db.scalars(
            select(KnowledgeUnit)
            .where(
                KnowledgeUnit.assignment_id == assignment.id,
                KnowledgeUnit.review_round == wanted,
            )
            .order_by(KnowledgeUnit.ordinal)
        )
    )


async def list_units(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    review_round: int | None = None,
) -> list[UnitAdminView | UnitPeerView | UnitAuthorView]:
    """The current round's units. Only the admin can ask for an earlier round."""
    units = await _units(db, assignment, review_round if actor == Actor.ADMIN else None)
    unit_ids = [unit.id for unit in units]
    if actor == Actor.ASSIGNEE:
        return [
            UnitAuthorView(
                id=unit.id,
                ordinal=unit.ordinal,
                review_round=unit.review_round,
                text=unit.text,
                kind=unit.kind,
                direction=unit.direction,
                patient_words=unit.patient_words,
                status=unit.status,
            )
            for unit in units
        ]
    if actor == Actor.REVIEWER:
        rows = await db.execute(
            select(UnitDecision.unit_id, UnitDecision.decision).where(
                UnitDecision.unit_id.in_(unit_ids),
                UnitDecision.reviewer_id == viewer.id,
                UnitDecision.stage == ReviewStage.PEER,
            )
        )
        mine = {unit_id: decision for unit_id, decision in rows}
        return [
            UnitPeerView(
                id=unit.id,
                ordinal=unit.ordinal,
                review_round=unit.review_round,
                text=unit.text,
                kind=unit.kind,
                direction=unit.direction,
                patient_words=unit.patient_words,
                my_decision=mine.get(unit.id),
            )
            for unit in units
        ]
    decisions: dict[UUID, list[DecisionView]] = defaultdict(list)
    rows = await db.execute(
        select(UnitDecision, User.pseudonym)
        .join(User, User.id == UnitDecision.reviewer_id)
        .where(UnitDecision.unit_id.in_(unit_ids))
        .order_by(UnitDecision.decided_at, UnitDecision.id)
    )
    for decision, pseudonym in rows:
        decisions[decision.unit_id].append(
            DecisionView(
                reviewer_id=decision.reviewer_id,
                reviewer_pseudonym=pseudonym,
                stage=decision.stage,
                decision=decision.decision,
                comment=decision.comment,
                decided_at=decision.decided_at,
            )
        )
    return [
        UnitAdminView(
            id=unit.id,
            ordinal=unit.ordinal,
            review_round=unit.review_round,
            text=unit.text,
            kind=unit.kind,
            direction=unit.direction,
            patient_words=unit.patient_words,
            status=unit.status,
            content_hash=unit.content_hash,
            decisions=decisions[unit.id],
        )
        for unit in units
    ]


async def review_queue(db: AsyncSession, viewer: User) -> list[ReviewQueueItem]:
    unit_counts = (
        select(
            KnowledgeUnit.assignment_id,
            KnowledgeUnit.review_round,
            func.count().label("unit_count"),
        )
        .group_by(KnowledgeUnit.assignment_id, KnowledgeUnit.review_round)
        .subquery()
    )
    base = (
        select(
            Assignment.id,
            Vignette.code,
            VignetteVersion.version,
            func.coalesce(unit_counts.c.unit_count, 0),
        )
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
        .outerjoin(
            unit_counts,
            (unit_counts.c.assignment_id == Assignment.id)
            & (unit_counts.c.review_round == Assignment.review_round),
        )
    )
    if viewer.role == Role.ADMIN:
        stage = ReviewStage.ADMIN
        requested_at = Assignment.updated_at
        query = base.where(Assignment.state.in_([State.ADMIN_REVIEW, State.PEER_REVIEW]))
    else:
        stage = ReviewStage.PEER
        requested_at = ReviewRequest.requested_at
        query = base.join(ReviewRequest, ReviewRequest.assignment_id == Assignment.id).where(
            ReviewRequest.reviewer_id == viewer.id,
            ReviewRequest.stage == ReviewStage.PEER,
            ReviewRequest.completed_at.is_(None),
        )
    rows = await db.execute(query.add_columns(requested_at).order_by(requested_at))
    return [
        ReviewQueueItem(
            assignment_id=assignment_id,
            stage=stage,
            vignette_code=code,
            vignette_version=version,
            unit_count=count,
            requested_at=at,
        )
        for assignment_id, code, version, count, at in rows
    ]


# --- requesting peers -----------------------------------------------------------------------


async def _check_reviewers(
    db: AsyncSession, assignment: Assignment, reviewer_ids: list[UUID]
) -> None:
    if assignment.expert_id in reviewer_ids:
        raise invalid("reviewer_is_author", "Authors can't review their own units.")
    reviewers = await db.scalars(select(User).where(User.id.in_(reviewer_ids)))
    usable = {r.id for r in reviewers if r.role == Role.EXPERT and r.is_active}
    if unusable := [str(i) for i in reviewer_ids if i not in usable]:
        raise invalid(
            "invalid_reviewer", "Only active experts can review.", {"reviewer_ids": unusable}
        )
    vignette_id = await db.scalar(
        select(VignetteVersion.vignette_id).where(
            VignetteVersion.id == assignment.vignette_version_id
        )
    )
    # Someone still to answer this vignette mustn't read a colleague's answers to it first.
    still_answering = await db.scalars(
        select(Assignment.expert_id)
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .where(
            Assignment.expert_id.in_(reviewer_ids),
            Assignment.state.in_(PRE_SUBMISSION_STATES),
            VignetteVersion.vignette_id == vignette_id,
        )
        .distinct()
    )
    if contaminated := [str(i) for i in still_answering]:
        raise DomainError(
            "reviewer_contaminated",
            "These experts still have to answer this vignette themselves.",
            details={"reviewer_ids": contaminated},
        )
    # Reviewers judge from their own reading of the case, so they must have formed one first.
    answered = set(
        await db.scalars(
            select(Assignment.expert_id)
            .join(Submission, Submission.assignment_id == Assignment.id)
            .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
            .where(
                Assignment.expert_id.in_(reviewer_ids),
                VignetteVersion.vignette_id == vignette_id,
            )
        )
    )
    if not_answered := [str(i) for i in reviewer_ids if i not in answered]:
        raise DomainError(
            "reviewer_has_not_answered",
            "Reviewers must have submitted their own answers to this vignette first.",
            details={"reviewer_ids": not_answered},
        )


async def eligible_peers(db: AsyncSession, assignment: Assignment) -> list[UUID]:
    """Colleagues who may review this assignment's units, by the rules of `_check_reviewers`: an
    active expert, not the author, who has submitted their own answers to the vignette (any
    version) and has none still to give."""
    vignette_id = await db.scalar(
        select(VignetteVersion.vignette_id).where(
            VignetteVersion.id == assignment.vignette_version_id
        )
    )
    answered = (
        select(Assignment.expert_id)
        .join(Submission, Submission.assignment_id == Assignment.id)
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .where(VignetteVersion.vignette_id == vignette_id)
    )
    still_answering = (
        select(Assignment.expert_id)
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .where(
            Assignment.state.in_(PRE_SUBMISSION_STATES),
            VignetteVersion.vignette_id == vignette_id,
        )
    )
    return list(
        await db.scalars(
            select(User.id)
            .where(
                User.role == Role.EXPERT,
                User.is_active,
                User.id != assignment.expert_id,
                User.id.in_(answered),
                User.id.not_in(still_answering),
            )
            .order_by(User.id)
        )
    )


async def request_peers(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    reviewer_ids: list[UUID],
    required_approvals: int,
) -> None:
    check_transition(assignment.state, Action.REQUEST_PEERS, actor)
    previous = await db.scalar(
        select(ReviewRequest.id)
        .where(
            ReviewRequest.assignment_id == assignment.id,
            ReviewRequest.stage == ReviewStage.PEER,
        )
        .limit(1)
    )
    if previous is not None:
        raise DomainError(
            "peers_already_requested",
            "Peers have already seen this assignment, so the admin decides now.",
        )
    if not await _units(db, assignment):
        raise DomainError("no_units", "This assignment has no units to review.")
    unique_ids = list(dict.fromkeys(reviewer_ids))
    if required_approvals > len(unique_ids):
        raise invalid(
            "not_enough_reviewers",
            f"{required_approvals} approvals need at least that many reviewers.",
        )
    await _check_reviewers(db, assignment, unique_ids)
    assignment.required_approvals = required_approvals
    db.add_all(
        ReviewRequest(
            assignment_id=assignment.id,
            reviewer_id=reviewer_id,
            stage=ReviewStage.PEER,
            requested_by=viewer.id,
        )
        for reviewer_id in unique_ids
    )
    await transition(
        db,
        assignment,
        Action.REQUEST_PEERS,
        actor,
        viewer.id,
        {"reviewer_ids": [str(i) for i in unique_ids], "required_approvals": required_approvals},
    )


async def _close_open_requests(db: AsyncSession, assignment_id: UUID) -> None:
    await db.execute(
        update(ReviewRequest)
        .where(ReviewRequest.assignment_id == assignment_id, ReviewRequest.completed_at.is_(None))
        .values(completed_at=utcnow())
    )


async def recall_review(
    db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User
) -> None:
    await transition(db, assignment, Action.RECALL_REVIEW, actor, viewer.id)
    await _close_open_requests(db, assignment.id)


# --- decisions ------------------------------------------------------------------------------


def _check_complete(units: list[KnowledgeUnit], decisions: list[UnitDecisionInput]) -> None:
    """Every unit exactly once: partial reviews would make stage completion ambiguous."""
    given = [decision.unit_id for decision in decisions]
    if len(set(given)) != len(given) or set(given) != {unit.id for unit in units}:
        raise invalid("decisions_incomplete", "Decide every unit of this assignment exactly once.")


def _record_decisions(
    db: AsyncSession,
    units: list[KnowledgeUnit],
    decisions: list[UnitDecisionInput],
    reviewer: User,
    stage: ReviewStage,
) -> None:
    hashes = {unit.id: unit.content_hash for unit in units}
    db.add_all(
        UnitDecision(
            unit_id=decision.unit_id,
            reviewer_id=reviewer.id,
            stage=stage,
            decision=decision.decision,
            comment=decision.comment,
            unit_content_hash=hashes[decision.unit_id],
        )
        for decision in decisions
    )


async def _send_back(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    units: list[KnowledgeUnit],
    by_unit: dict[UUID, DecisionValue],
    changes: int,
) -> None:
    """The admin asked for changes: these units become history, the author corrects the filing, and
    a new round of units is cut and reviewed. Nothing from this round is ingested."""
    for unit in units:
        unit.status = UnitStatus.SUPERSEDED
    assignment.review_round += 1
    approved = sum(d == DecisionValue.APPROVE for d in by_unit.values())
    await transition(
        db,
        assignment,
        Action.REQUEST_CHANGES,
        actor,
        viewer.id,
        {
            "approved": approved,
            "rejected": len(units) - approved - changes,
            "changes": changes,
            "review_round": assignment.review_round,
        },
    )
    await _close_open_requests(db, assignment.id)
    findings = await db.get(AnswerFindings, assignment.id)
    if findings is not None:
        findings.check_outcome = None  # the author approves the (corrected) filing again


async def _admin_decides(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    units: list[KnowledgeUnit],
    decisions: list[UnitDecisionInput],
) -> None:
    check_transition(assignment.state, Action.APPROVE_UNITS, actor)
    _check_complete(units, decisions)
    _record_decisions(db, units, decisions, viewer, ReviewStage.ADMIN)
    by_unit = {decision.unit_id: decision.decision for decision in decisions}
    if changes := sum(d == DecisionValue.REQUEST_CHANGES for d in by_unit.values()):
        await _send_back(db, assignment, actor, viewer, units, by_unit, changes)
        return
    for unit in units:
        approved = by_unit[unit.id] == DecisionValue.APPROVE
        unit.status = UnitStatus.APPROVED if approved else UnitStatus.REJECTED
    approved_count = sum(unit.status == UnitStatus.APPROVED for unit in units)
    action = Action.APPROVE_UNITS if approved_count else Action.REJECT_ALL_UNITS
    await transition(
        db,
        assignment,
        action,
        actor,
        viewer.id,
        {"approved": approved_count, "rejected": len(units) - approved_count},
    )
    await _close_open_requests(db, assignment.id)  # an admin deciding in peer review ends it


async def _peer_decides(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    units: list[KnowledgeUnit],
    decisions: list[UnitDecisionInput],
) -> None:
    check_transition(assignment.state, Action.PEERS_APPROVED, actor)
    request = await db.scalar(
        select(ReviewRequest).where(
            ReviewRequest.assignment_id == assignment.id,
            ReviewRequest.reviewer_id == viewer.id,
            ReviewRequest.stage == ReviewStage.PEER,
        )
    )
    if request is None or request.completed_at is not None:
        raise DomainError("already_decided", "This review request is already closed.")
    _check_complete(units, decisions)
    _record_decisions(db, units, decisions, viewer, ReviewStage.PEER)
    request.completed_at = utcnow()
    await db.flush()

    # Counted over all reviewers. An approval only counts for the text that was reviewed.
    hashes = {unit.id: unit.content_hash for unit in units}
    recorded = await db.scalars(
        select(UnitDecision).where(
            UnitDecision.unit_id.in_(list(hashes)), UnitDecision.stage == ReviewStage.PEER
        )
    )
    approvals: dict[UUID, int] = defaultdict(int)
    any_rejection = False
    for decision in recorded:
        if decision.unit_content_hash != hashes[decision.unit_id]:
            continue
        if decision.decision in (DecisionValue.REJECT, DecisionValue.REQUEST_CHANGES):
            any_rejection = True  # either way it goes to the admin, who sees the comments
        else:
            approvals[decision.unit_id] += 1

    if any_rejection:
        await transition(db, assignment, Action.PEER_REJECTED, actor, viewer.id)
        await _close_open_requests(db, assignment.id)
        return
    if all(approvals[unit.id] >= assignment.required_approvals for unit in units):
        for unit in units:
            unit.status = UnitStatus.APPROVED
        await transition(
            db, assignment, Action.PEERS_APPROVED, actor, viewer.id, {"approved": len(units)}
        )
        await _close_open_requests(db, assignment.id)


def _require_comments(decisions: list[UnitDecisionInput]) -> None:
    """Asking for changes without saying what to change would leave the author guessing."""
    if missing := [
        str(d.unit_id)
        for d in decisions
        if d.decision == DecisionValue.REQUEST_CHANGES and not (d.comment or "").strip()
    ]:
        raise invalid(
            "comment_required",
            "Say what should change when asking for changes.",
            {"unit_ids": missing},
        )


async def submit_decisions(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    decisions: list[UnitDecisionInput],
) -> None:
    _require_comments(decisions)
    units = await _units(db, assignment)
    if actor == Actor.REVIEWER:
        await _peer_decides(db, assignment, actor, viewer, units, decisions)
    else:
        await _admin_decides(db, assignment, actor, viewer, units, decisions)
