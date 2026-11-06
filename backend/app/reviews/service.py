"""Units, their discussion and the reviewers' votes. Only the admin's decision closes a review."""

from collections import defaultdict
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment
from app.assignments.state_machine import check_transition, transition
from app.assignments.states import Action, Actor, State
from app.audit.service import record_event
from app.core.db import utcnow
from app.core.errors import DomainError, forbidden, invalid, not_found
from app.knowledge.models import AnswerFindings, KnowledgeUnit, UnitStatus
from app.reviews import access
from app.reviews.models import (
    DecisionValue,
    ReviewParticipant,
    ReviewStage,
    SubmissionVote,
    UnitComment,
    UnitDecision,
    Vote,
)
from app.reviews.schemas import (
    CommentCreate,
    CommentView,
    DecisionView,
    ReviewItem,
    Speaker,
    UnitAdminView,
    UnitAuthorView,
    UnitDecisionInput,
    UnitPeerView,
    VoteEntry,
    VoteInput,
    VotesView,
)
from app.users.models import Role, User
from app.vignettes.models import Vignette, VignetteVersion


def speaker_for(
    assignment: Assignment, actor: Actor, *, user_id: UUID, role: Role, pseudonym: str
) -> Speaker:
    """Who a line of the discussion is from, as the viewer (acting as `actor`) may know it."""
    if user_id == assignment.expert_id:
        kind: Literal["author", "reviewer", "admin"] = "author"
    elif role == Role.ADMIN:
        kind = "admin"
    else:
        kind = "reviewer"
    return Speaker(
        kind=kind, pseudonym=pseudonym if kind == "reviewer" or actor == Actor.ADMIN else None
    )


async def _units(
    db: AsyncSession, assignment: Assignment, review_round: int | None = None
) -> list[KnowledgeUnit]:
    """The units of the assignment's current round, or of another one (the history)."""
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


async def _comments(
    db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User, unit_ids: list[UUID]
) -> dict[UUID, list[CommentView]]:
    by_unit: dict[UUID, list[CommentView]] = defaultdict(list)
    rows = await db.execute(
        select(UnitComment, User.role, User.pseudonym)
        .join(User, User.id == UnitComment.author_id)
        .where(UnitComment.unit_id.in_(unit_ids))
        .order_by(UnitComment.created_at, UnitComment.id)
    )
    for comment, role, pseudonym in rows:
        by_unit[comment.unit_id].append(
            CommentView(
                id=comment.id,
                unit_id=comment.unit_id,
                parent_id=comment.parent_id,
                stance=comment.stance,
                body=comment.body,
                created_at=comment.created_at,
                speaker=speaker_for(
                    assignment, actor, user_id=comment.author_id, role=role, pseudonym=pseudonym
                ),
                is_mine=comment.author_id == viewer.id,
            )
        )
    return by_unit


async def list_units(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    review_round: int | None = None,
) -> list[UnitAdminView | UnitPeerView | UnitAuthorView]:
    """The current round's units, with their discussion. The admin and the author can ask for an
    earlier round: the author to read what was said while correcting the filing."""
    history = actor in (Actor.ADMIN, Actor.ASSIGNEE)
    units = await _units(db, assignment, review_round if history else None)
    unit_ids = [unit.id for unit in units]
    comments = await _comments(db, assignment, actor, viewer, unit_ids)
    common: dict[UUID, dict[str, Any]] = {
        unit.id: {
            "id": unit.id,
            "ordinal": unit.ordinal,
            "review_round": unit.review_round,
            "text": unit.text,
            "kind": unit.kind,
            "direction": unit.direction,
            "patient_words": unit.patient_words,
            "comments": comments[unit.id],
        }
        for unit in units
    }
    if actor == Actor.ASSIGNEE:
        return [UnitAuthorView(**common[unit.id], status=unit.status) for unit in units]
    if actor == Actor.REVIEWER:
        return [UnitPeerView(**common[unit.id]) for unit in units]
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
            **common[unit.id],
            status=unit.status,
            content_hash=unit.content_hash,
            decisions=decisions[unit.id],
        )
        for unit in units
    ]


# --- the list of reviews --------------------------------------------------------------------


async def list_reviews(
    db: AsyncSession,
    viewer: User,
    *,
    status: Literal["open", "closed"] | None = None,
    limit: int = 100,
) -> list[ReviewItem]:
    """Reviews the viewer is part of: an expert's own submissions and every one they may read; for
    the admin, all. Open means the admin has yet to decide."""
    states = {
        "open": access.OPEN_REVIEW_STATES,
        "closed": access.CLOSED_REVIEW_STATES,
        None: access.REVIEW_VISIBLE_STATES,
    }[status]
    is_admin = viewer.role == Role.ADMIN
    this_round = (
        KnowledgeUnit.assignment_id == Assignment.id,
        KnowledgeUnit.review_round == Assignment.review_round,
    )
    unit_count = select(func.count()).select_from(KnowledgeUnit).where(*this_round)
    comment_count = (
        select(func.count())
        .select_from(UnitComment)
        .join(KnowledgeUnit, KnowledgeUnit.id == UnitComment.unit_id)
        .where(*this_round)
    )

    def votes(*extra):
        return (
            select(func.count())
            .select_from(SubmissionVote)
            .where(
                SubmissionVote.assignment_id == Assignment.id,
                SubmissionVote.review_round == Assignment.review_round,
                *extra,
            )
        )

    my_vote = select(SubmissionVote.vote).where(
        SubmissionVote.assignment_id == Assignment.id,
        SubmissionVote.review_round == Assignment.review_round,
        SubmissionVote.voter_id == viewer.id,
    )
    opened = exists().where(
        ReviewParticipant.assignment_id == Assignment.id,
        ReviewParticipant.expert_id == viewer.id,
    )
    query = (
        select(
            Assignment.id,
            Vignette.code,
            VignetteVersion.version,
            Assignment.review_round,
            Assignment.state,
            Assignment.expert_id,
            User.pseudonym,
            unit_count.scalar_subquery(),
            votes(SubmissionVote.vote == Vote.ACCEPT).scalar_subquery(),
            votes(SubmissionVote.vote == Vote.DECLINE).scalar_subquery(),
            comment_count.scalar_subquery(),
            my_vote.scalar_subquery(),
            case((opened, True), else_=False),
            Assignment.updated_at,
        )
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
        .join(User, User.id == Assignment.expert_id)
        .where(Assignment.state.in_(states))
        .order_by(Assignment.updated_at.desc(), Assignment.id)
        .limit(limit)
    )
    if not is_admin:
        blocked = await access.blocked_vignettes(db, viewer.id)
        query = query.where(
            or_(
                Assignment.expert_id == viewer.id,
                opened,
                VignetteVersion.vignette_id.not_in(blocked),
            )
        )
    items = []
    for row in await db.execute(query):
        (assignment_id, code, version, review_round, state, author_id, author_pseudonym) = row[:7]
        (units, accepts, declines, comments, mine, was_opened, updated_at) = row[7:]
        relation: Literal["reviewer", "author", "admin"] = (
            "admin" if is_admin else "author" if author_id == viewer.id else "reviewer"
        )
        items.append(
            ReviewItem(
                assignment_id=assignment_id,
                vignette_code=code,
                vignette_version=version,
                review_round=review_round,
                state=state,
                relation=relation,
                opened=relation != "reviewer" or was_opened,
                unit_count=units,
                accepts=accepts,
                declines=declines,
                comment_count=comments,
                my_vote=mine,
                updated_at=updated_at,
                author_pseudonym=author_pseudonym if is_admin else None,
            )
        )
    return items


# --- reading, discussing and voting ---------------------------------------------------------


async def open_review(db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User) -> None:
    """A reviewer agrees to read. Idempotent; a no-op for the author and the admin."""
    if actor != Actor.REVIEWER or await access.has_opened(db, assignment.id, viewer.id):
        return
    db.add(ReviewParticipant(assignment_id=assignment.id, expert_id=viewer.id))
    record_event(
        db,
        actor_id=viewer.id,
        entity_type="assignment",
        entity_id=assignment.id,
        action="review_opened",
    )


def _require_open(assignment: Assignment) -> None:
    if assignment.state != State.PEER_REVIEW:
        raise DomainError(
            "review_closed",
            "This review is closed, so it can't take more comments or votes.",
            details={"state": assignment.state.value},
        )


async def add_comment(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    unit_id: UUID,
    body: CommentCreate,
) -> CommentView:
    _require_open(assignment)
    if body.stance is not None and actor != Actor.REVIEWER:
        # The author taking a side on their own work would be a vote for it.
        raise invalid("stance_not_allowed", "Only reviewers can take a side.")
    unit = await db.scalar(
        select(KnowledgeUnit).where(
            KnowledgeUnit.id == unit_id,
            KnowledgeUnit.assignment_id == assignment.id,
            KnowledgeUnit.review_round == assignment.review_round,
        )
    )
    if unit is None:
        raise not_found("Unit")
    if body.parent_id is not None:
        parent = await db.get(UnitComment, body.parent_id)
        if parent is None or parent.unit_id != unit.id or parent.parent_id is not None:
            raise invalid(
                "invalid_parent", "Reply to a comment on this unit that is not itself a reply."
            )
    comment = UnitComment(
        unit_id=unit.id,
        author_id=viewer.id,
        parent_id=body.parent_id,
        stance=body.stance,
        body=body.body,
    )
    db.add(comment)
    await db.flush()
    record_event(
        db,
        actor_id=viewer.id,
        entity_type="assignment",
        entity_id=assignment.id,
        action="comment_added",
        meta={
            "unit_id": str(unit.id),
            "comment_id": str(comment.id),
            "stance": body.stance.value if body.stance else None,
        },
    )
    return CommentView(
        id=comment.id,
        unit_id=comment.unit_id,
        parent_id=comment.parent_id,
        stance=comment.stance,
        body=comment.body,
        created_at=comment.created_at,
        speaker=speaker_for(
            assignment, actor, user_id=viewer.id, role=viewer.role, pseudonym=viewer.pseudonym
        ),
        is_mine=True,
    )


async def votes_view(
    db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User
) -> VotesView:
    rows = await db.execute(
        select(SubmissionVote, User.role, User.pseudonym)
        .join(User, User.id == SubmissionVote.voter_id)
        .where(
            SubmissionVote.assignment_id == assignment.id,
            SubmissionVote.review_round == assignment.review_round,
        )
        .order_by(SubmissionVote.created_at, SubmissionVote.voter_id)
    )
    entries = [
        VoteEntry(
            speaker=speaker_for(
                assignment, actor, user_id=vote.voter_id, role=role, pseudonym=pseudonym
            ),
            vote=vote.vote,
            at=vote.updated_at,
        )
        for vote, role, pseudonym in rows
    ]
    mine = await db.scalar(
        select(SubmissionVote.vote).where(
            SubmissionVote.assignment_id == assignment.id,
            SubmissionVote.review_round == assignment.review_round,
            SubmissionVote.voter_id == viewer.id,
        )
    )
    return VotesView(
        review_round=assignment.review_round,
        accepts=sum(entry.vote == Vote.ACCEPT for entry in entries),
        declines=sum(entry.vote == Vote.DECLINE for entry in entries),
        my_vote=mine,
        votes=entries,
    )


async def cast_vote(
    db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User, body: VoteInput
) -> VotesView:
    """Advisory, and changeable until the admin closes the review."""
    if actor != Actor.REVIEWER:
        raise forbidden("Only reviewers vote.")
    _require_open(assignment)
    if body.review_round != assignment.review_round:
        raise DomainError(
            "stale_round",
            "These units have been cut again since you opened them. Reload the review.",
            details={"current_round": assignment.review_round},
        )
    existing = await db.get(SubmissionVote, (assignment.id, assignment.review_round, viewer.id))
    if existing is None:
        db.add(
            SubmissionVote(
                assignment_id=assignment.id,
                review_round=assignment.review_round,
                voter_id=viewer.id,
                vote=body.vote,
            )
        )
    else:
        existing.vote = body.vote
        existing.updated_at = utcnow()
    record_event(
        db,
        actor_id=viewer.id,
        entity_type="assignment",
        entity_id=assignment.id,
        action="vote_cast",
        meta={"vote": body.vote.value, "review_round": assignment.review_round},
    )
    await db.flush()
    return await votes_view(db, assignment, actor, viewer)


# --- the admin's decision -------------------------------------------------------------------


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
    """Only the admin decides, per unit; the reviewers' votes and comments are what they read."""
    check_transition(assignment.state, Action.APPROVE_UNITS, actor)
    _require_comments(decisions)
    await _admin_decides(db, assignment, actor, viewer, await _units(db, assignment), decisions)
