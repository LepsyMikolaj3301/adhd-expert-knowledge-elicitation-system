"""The expert check: the author reads how the answers were filed, may correct it, then approves.

The answers themselves never change here. Only which citations a sentence belongs to, and each
citation's direction, can be corrected. The units are built from the result.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment
from app.assignments.schemas import (
    FindingFeedback,
    FindingFlag,
    FindingHighlight,
    FindingsCorrection,
    FindingSentence,
    FindingsView,
)
from app.assignments.state_machine import transition
from app.assignments.states import Action, Actor, State
from app.audit.service import record_event
from app.core.db import utcnow
from app.core.errors import DomainError, forbidden, invalid, not_found
from app.knowledge import findings
from app.knowledge.models import AnswerFindings, KnowledgeUnit
from app.reviews.models import DecisionValue, ReviewStage, UnitDecision
from app.users.models import User


async def _row(db: AsyncSession, assignment: Assignment) -> AnswerFindings:
    row = await db.get(AnswerFindings, assignment.id)
    if row is None:
        raise not_found("Findings")
    return row


async def feedback(db: AsyncSession, assignment: Assignment) -> list[FindingFeedback]:
    """The requests for changes of the round before this one, with the unit each is about. Who made
    them is reduced to a role: the author never learns which colleague reviewed."""
    if assignment.review_round < 2:
        return []
    rows = await db.execute(
        select(UnitDecision, KnowledgeUnit)
        .join(KnowledgeUnit, KnowledgeUnit.id == UnitDecision.unit_id)
        .where(
            KnowledgeUnit.assignment_id == assignment.id,
            KnowledgeUnit.review_round == assignment.review_round - 1,
            UnitDecision.decision == DecisionValue.REQUEST_CHANGES,
        )
        .order_by(UnitDecision.decided_at, UnitDecision.id)
    )
    return [
        FindingFeedback(
            kind=unit.kind,  # ty: ignore[invalid-argument-type]
            patient_words=unit.patient_words,
            unit_text=unit.text,
            comment=decision.comment or "",
            by="admin" if decision.stage == ReviewStage.ADMIN else "reviewer",
        )
        for decision, unit in rows
    ]


def view(
    row: AnswerFindings,
    assignment: Assignment,
    actor: Actor,
    requested_changes: list[FindingFeedback],
) -> FindingsView:
    record = row.record
    return FindingsView(
        version=row.version,
        review_round=assignment.review_round,
        feedback=requested_changes,
        editable=actor == Actor.ASSIGNEE and assignment.state == State.EXPERT_CHECK,
        check_outcome=row.check_outcome,  # ty: ignore[invalid-argument-type]
        highlights=[
            FindingHighlight(
                id=h["id"],
                chip=h["chip"],
                text=h["text"],
                origin=h["origin"],
                direction=h["direction"],
            )
            for h in record["highlights"]
        ],
        sentences=[
            FindingSentence(
                id=s["id"],
                question_id=s["question_id"],
                text=findings.render_sentence(s["text"], record["highlights"]),
                targets=s["targets"],
                assigned_by=s["assigned_by"],
            )
            for s in record["sentences"]
        ],
        flags=[
            FindingFlag(
                kind=f["kind"],
                highlight=f["highlight"],
                sentence=f.get("sentence"),
                message=f["message"],
            )
            for f in record["flags"]
        ],
    )


async def get(db: AsyncSession, assignment: Assignment, actor: Actor) -> FindingsView:
    """Reviewers get a 404 before they get here: `actor_for` only lets them see units."""
    if actor == Actor.REVIEWER:
        raise not_found("Findings")
    return view(await _row(db, assignment), assignment, actor, await feedback(db, assignment))


def _validate(record: dict, correction: FindingsCorrection) -> None:
    sentences = {s["id"] for s in record["sentences"]}
    expert_highlights = {h["id"] for h in record["highlights"] if h["origin"] == "expert"}
    targets = {h["id"] for h in record["highlights"]} | {findings.CASE}
    for sentence_id, new in correction.sentences.items():
        if sentence_id not in sentences:
            raise invalid("unknown_sentence", "That sentence isn't in your answers.")
        if not new:
            raise invalid(
                "no_target", "A sentence has to belong somewhere: pick a citation or case."
            )
        if unknown := [t for t in new if t not in targets]:
            raise invalid(
                "unknown_target", "That isn't one of your citations.", {"targets": unknown}
            )
    for highlight_id in correction.directions:
        if highlight_id not in expert_highlights:
            raise invalid("unknown_highlight", "That isn't one of your citations.")


async def correct(
    db: AsyncSession,
    assignment: Assignment,
    actor: Actor,
    viewer: User,
    correction: FindingsCorrection,
) -> FindingsView:
    if actor != Actor.ASSIGNEE:
        raise forbidden("Only the author can correct how the answers were filed.")
    if assignment.state != State.EXPERT_CHECK:
        raise DomainError(
            "not_editable",
            "The filing can only be corrected while you are checking it.",
            details={"state": assignment.state.value},
        )
    row = await _row(db, assignment)
    if correction.version != row.version:
        raise DomainError(
            "findings_conflict",
            "This was corrected elsewhere. Reload it before continuing.",
            details={"current_version": row.version},
        )
    _validate(row.record, correction)

    record = {**row.record, "corrections": list(row.record["corrections"])}
    moved, changed = findings.apply_corrections(
        record, correction.sentences, dict(correction.directions), utcnow().isoformat()
    )
    if moved or changed:
        row.record = record  # a new object, so that the JSONB change is noticed
        row.version += 1
        record_event(
            db,
            actor_id=viewer.id,
            entity_type="assignment",
            entity_id=assignment.id,
            action="findings_corrected",
            meta={"version": row.version, "sentences": moved, "directions": changed},
        )
    return view(row, assignment, actor, await feedback(db, assignment))


async def finish(
    db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User, *, skip: bool
) -> None:
    """Approve the filing (or skip the check) and queue the building of units."""
    await transition(
        db,
        assignment,
        Action.SKIP_EXPERT_CHECK if skip else Action.COMPLETE_EXPERT_CHECK,
        actor,
        viewer.id,
    )
    row = await db.get(AnswerFindings, assignment.id)
    if row is not None:
        row.check_outcome = "skipped" if skip else "completed"
