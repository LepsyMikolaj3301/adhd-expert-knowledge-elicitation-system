"""Answers under review, their discussion and the reviewers' votes. Only the admin's decision
closes a review."""

from collections import defaultdict
from typing import Literal
from uuid import UUID

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment
from app.assignments.state_machine import check_transition, transition
from app.assignments.states import Action, Actor, State
from app.audit.service import record_event
from app.core.db import utcnow
from app.core.errors import DomainError, forbidden, invalid, not_found
from app.knowledge import findings
from app.proofread import service as proofread
from app.proofread.models import AnswerRevision, ProofreadRound
from app.reviews import access
from app.reviews.models import (
    AnswerComment,
    AnswerDecision,
    AnswerVote,
    AnswerVoteValue,
    DecisionValue,
    ReviewParticipant,
)
from app.reviews.schemas import (
    AnswerDecisionInput,
    CommentCreate,
    CommentView,
    DecisionView,
    ReviewAnswer,
    ReviewAnswersView,
    ReviewItem,
    Speaker,
    VoteEntry,
    VoteInput,
)
from app.users.models import Role, User
from app.vignettes.models import Vignette, VignetteVersion
from app.vignettes.questions import QUESTIONS, render_question
from app.vignettes.service import version_and_code


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


async def submitted_rounds(db: AsyncSession, assignment_id: UUID) -> list[int]:
    return list(
        await db.scalars(
            select(ProofreadRound.review_round)
            .where(
                ProofreadRound.assignment_id == assignment_id,
                ProofreadRound.submitted_at.is_not(None),
            )
            .order_by(ProofreadRound.review_round)
        )
    )


def _comment_view(
    assignment: Assignment, actor: Actor, viewer: User, comment: AnswerComment, role, pseudonym
) -> CommentView:
    return CommentView(
        id=comment.id,
        question_id=comment.question_id,
        parent_id=comment.parent_id,
        stance=comment.stance,
        body=comment.body,
        created_at=comment.created_at,
        speaker=speaker_for(
            assignment, actor, user_id=comment.author_id, role=role, pseudonym=pseudonym
        ),
        is_mine=comment.author_id == viewer.id,
    )


async def list_answers(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    review_round: int | None = None,
) -> ReviewAnswersView:
    """The answers of the round under review, with their discussion and votes. The admin and the
    author can ask for an earlier round: the author to read what was said while editing."""
    rounds = await submitted_rounds(db, assignment.id)
    if not rounds:
        raise not_found("Review")
    history = actor in (Actor.ADMIN, Actor.ASSIGNEE)
    wanted = review_round if history and review_round is not None else rounds[-1]
    if wanted not in rounds:
        raise not_found("Review round")
    round_ = await proofread.get_round(db, assignment.id, wanted)
    assert round_ is not None
    version, _ = await version_and_code(db, assignment.vignette_version_id)
    rows = await proofread.revisions(db, assignment.id, wanted, version.question_ids)

    comments: dict[str, list[CommentView]] = defaultdict(list)
    for comment, role, pseudonym in await db.execute(
        select(AnswerComment, User.role, User.pseudonym)
        .join(User, User.id == AnswerComment.author_id)
        .where(AnswerComment.assignment_id == assignment.id, AnswerComment.review_round == wanted)
        .order_by(AnswerComment.created_at, AnswerComment.id)
    ):
        comments[comment.question_id].append(
            _comment_view(assignment, actor, viewer, comment, role, pseudonym)
        )
    votes: dict[str, list[VoteEntry]] = defaultdict(list)
    mine: dict[str, AnswerVoteValue] = {}
    for vote, role, pseudonym in await db.execute(
        select(AnswerVote, User.role, User.pseudonym)
        .join(User, User.id == AnswerVote.voter_id)
        .where(AnswerVote.assignment_id == assignment.id, AnswerVote.review_round == wanted)
        .order_by(AnswerVote.created_at, AnswerVote.voter_id)
    ):
        votes[vote.question_id].append(
            VoteEntry(
                speaker=speaker_for(
                    assignment, actor, user_id=vote.voter_id, role=role, pseudonym=pseudonym
                ),
                vote=vote.vote,
                at=vote.updated_at,
            )
        )
        if vote.voter_id == viewer.id:
            mine[vote.question_id] = vote.vote
    decisions = {
        decision.question_id: DecisionView(
            decision=decision.decision, comment=decision.comment, decided_at=decision.decided_at
        )
        for decision in await db.scalars(
            select(AnswerDecision).where(
                AnswerDecision.assignment_id == assignment.id,
                AnswerDecision.review_round == wanted,
            )
        )
    }
    return ReviewAnswersView(
        review_round=wanted,
        rounds=rounds,
        state=assignment.state,
        highlights=proofread.highlight_views(round_.highlights),
        answers=[
            ReviewAnswer(
                question_id=row.question_id,
                question=render_question(QUESTIONS[row.question_id], version.q4_whatif),
                text=row.final,
                lines=proofread.line_views(row.lines),
                comments=comments[row.question_id],
                approvals=sum(v.vote == AnswerVoteValue.APPROVE for v in votes[row.question_id]),
                disapprovals=sum(
                    v.vote == AnswerVoteValue.DISAPPROVE for v in votes[row.question_id]
                ),
                my_vote=mine.get(row.question_id),
                votes=votes[row.question_id],
                decision=decisions.get(row.question_id),
            )
            for row in rows
        ],
    )


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
    answer_count = (
        select(func.count())
        .select_from(AnswerRevision)
        .where(
            AnswerRevision.assignment_id == Assignment.id,
            AnswerRevision.review_round == Assignment.review_round,
        )
    )
    comment_count = (
        select(func.count())
        .select_from(AnswerComment)
        .where(
            AnswerComment.assignment_id == Assignment.id,
            AnswerComment.review_round == Assignment.review_round,
        )
    )

    def votes(*extra):
        return (
            select(func.count())
            .select_from(AnswerVote)
            .where(
                AnswerVote.assignment_id == Assignment.id,
                AnswerVote.review_round == Assignment.review_round,
                *extra,
            )
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
            answer_count.scalar_subquery(),
            votes(AnswerVote.vote == AnswerVoteValue.APPROVE).scalar_subquery(),
            votes(AnswerVote.vote == AnswerVoteValue.DISAPPROVE).scalar_subquery(),
            comment_count.scalar_subquery(),
            votes(AnswerVote.voter_id == viewer.id).scalar_subquery(),
            case((opened, True), else_=False),
            Assignment.updated_at,
        )
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
        .join(User, User.id == Assignment.expert_id)
        .where(Assignment.state.in_(states), access.was_submitted())
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
        (answers, approvals, disapprovals, comments, my_votes, was_opened, updated_at) = row[7:]
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
                answer_count=answers,
                approvals=approvals,
                disapprovals=disapprovals,
                comment_count=comments,
                my_votes=my_votes,
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


async def _answer(db: AsyncSession, assignment: Assignment, question_id: str) -> AnswerRevision:
    row = await db.get(AnswerRevision, (assignment.id, assignment.review_round, question_id))
    if row is None:
        raise not_found("Answer")
    return row


async def add_comment(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    question_id: str,
    body: CommentCreate,
) -> CommentView:
    _require_open(assignment)
    if body.stance is not None and actor != Actor.REVIEWER:
        # The author taking a side on their own work would be a vote for it.
        raise invalid("stance_not_allowed", "Only reviewers can take a side.")
    await _answer(db, assignment, question_id)
    if body.parent_id is not None:
        parent = await db.get(AnswerComment, body.parent_id)
        if (
            parent is None
            or parent.assignment_id != assignment.id
            or parent.review_round != assignment.review_round
            or parent.question_id != question_id
            or parent.parent_id is not None
        ):
            raise invalid(
                "invalid_parent", "Reply to a comment on this answer that is not itself a reply."
            )
    comment = AnswerComment(
        assignment_id=assignment.id,
        review_round=assignment.review_round,
        question_id=question_id,
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
            "question_id": question_id,
            "comment_id": str(comment.id),
            "stance": body.stance.value if body.stance else None,
        },
    )
    return _comment_view(assignment, actor, viewer, comment, viewer.role, viewer.pseudonym)


async def cast_vote(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    question_id: str,
    body: VoteInput,
) -> ReviewAnswersView:
    """Advisory, and changeable until the admin closes the review."""
    if actor != Actor.REVIEWER:
        raise forbidden("Only reviewers vote.")
    _require_open(assignment)
    if body.review_round != assignment.review_round:
        raise DomainError(
            "stale_round",
            "These answers have been edited since you opened them. Reload the review.",
            details={"current_round": assignment.review_round},
        )
    await _answer(db, assignment, question_id)
    key = (assignment.id, assignment.review_round, question_id, viewer.id)
    existing = await db.get(AnswerVote, key)
    if existing is None:
        db.add(
            AnswerVote(
                assignment_id=assignment.id,
                review_round=assignment.review_round,
                question_id=question_id,
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
        meta={
            "question_id": question_id,
            "vote": body.vote.value,
            "review_round": assignment.review_round,
        },
    )
    await db.flush()
    return await list_answers(db, assignment, actor, viewer)


# --- the admin's decision -------------------------------------------------------------------


def _require_comments(decisions: list[AnswerDecisionInput]) -> None:
    """Asking for changes without saying what to change would leave the author guessing."""
    if missing := [
        d.question_id
        for d in decisions
        if d.decision == DecisionValue.REQUEST_CHANGES and not (d.comment or "").strip()
    ]:
        raise invalid(
            "comment_required",
            "Say what should change when asking for changes.",
            {"question_ids": missing},
        )


async def submit_decisions(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    decisions: list[AnswerDecisionInput],
) -> None:
    """Only the admin decides, per answer; the reviewers' votes and comments are what they read.

    Any request for changes sends every answer back to the author for a new round. Otherwise the
    approved answers are cut into units and ingested; with none approved, the submission is
    rejected.
    """
    check_transition(assignment.state, Action.APPROVE_ANSWERS, actor)
    _require_comments(decisions)
    version, _ = await version_and_code(db, assignment.vignette_version_id)
    rows = await proofread.revisions(
        db, assignment.id, assignment.review_round, version.question_ids
    )
    given = [decision.question_id for decision in decisions]
    if len(set(given)) != len(given) or set(given) != {row.question_id for row in rows}:
        raise invalid("decisions_incomplete", "Decide every answer exactly once.")
    by_question = {row.question_id: row for row in rows}
    db.add_all(
        AnswerDecision(
            assignment_id=assignment.id,
            review_round=assignment.review_round,
            question_id=decision.question_id,
            reviewer_id=viewer.id,
            decision=decision.decision,
            comment=(decision.comment or "").strip() or None,
            content_hash=proofread.answer_hash(by_question[decision.question_id]),
        )
        for decision in decisions
    )
    counts = {value.value: sum(d.decision == value for d in decisions) for value in DecisionValue}
    if counts[DecisionValue.REQUEST_CHANGES.value]:
        assignment.review_round += 1
        await transition(
            db,
            assignment,
            Action.REQUEST_CHANGES,
            actor,
            viewer.id,
            {**counts, "review_round": assignment.review_round},
        )
        feedback = [
            {"question_id": d.question_id, "comment": d.comment.strip()}
            for d in decisions
            if d.comment and d.comment.strip()
        ]
        await proofread.open_next_round(db, assignment, feedback)
        return
    # Only answers that are filed become units: approving Q4's why alone leaves nothing to ingest.
    filed = [
        d
        for d in decisions
        if d.decision == DecisionValue.APPROVE and findings.is_filed(d.question_id)
    ]
    action = Action.APPROVE_ANSWERS if filed else Action.REJECT_ALL_ANSWERS
    await transition(db, assignment, action, actor, viewer.id, counts)
