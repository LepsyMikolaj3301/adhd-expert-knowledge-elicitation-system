"""The proofread check: the author edits the proofread answers and their links, then submits them
for review. Also what the jobs need: proofreading a submission, and reading what was approved."""

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.answers import check_chips
from app.assignments.models import Assignment, Submission
from app.assignments.state_machine import check_transition, transition
from app.assignments.states import Action, Actor, State
from app.core.db import session_factory, utcnow
from app.core.errors import DomainError, forbidden, invalid, not_found
from app.core.security import content_hash
from app.knowledge import classifier, findings
from app.proofread import links
from app.proofread.models import AnswerRevision, ProofreadRound
from app.proofread.pipeline import proofread_answer
from app.proofread.schemas import (
    AnswerLine,
    LinkedHighlight,
    ProofreadFeedback,
    ProofreadFlag,
    ProofreadItem,
    ProofreadSave,
    ProofreadView,
)
from app.settings import settings
from app.users.models import User
from app.vignettes.models import VignetteVersion
from app.vignettes.questions import QUESTIONS, QuestionId, render_question
from app.vignettes.service import version_and_code

# --- reading --------------------------------------------------------------------------------


async def get_round(
    db: AsyncSession, assignment_id: UUID, review_round: int, *, lock: bool = False
) -> ProofreadRound | None:
    query = select(ProofreadRound).where(
        ProofreadRound.assignment_id == assignment_id,
        ProofreadRound.review_round == review_round,
    )
    if lock:
        query = query.with_for_update()
    return await db.scalar(query)


async def revisions(
    db: AsyncSession, assignment_id: UUID, review_round: int, question_ids: list[str]
) -> list[AnswerRevision]:
    """The answers of a round, in the order the questions were asked."""
    rows = await db.scalars(
        select(AnswerRevision).where(
            AnswerRevision.assignment_id == assignment_id,
            AnswerRevision.review_round == review_round,
        )
    )
    order = {question_id: index for index, question_id in enumerate(question_ids)}
    return sorted(rows, key=lambda row: order.get(row.question_id, len(order)))


def answer_hash(revision: AnswerRevision) -> str:
    """What an approval is for: the text and how its lines are linked."""
    targets = "\n".join(",".join(line["targets"]) for line in revision.lines)
    return content_hash(revision.final + "\n\n" + targets)


def highlight_views(highlights: list[dict]) -> list[LinkedHighlight]:
    return [
        LinkedHighlight(
            id=h["id"],
            chip=h["chip"],
            text=h["text"],
            span=(h["span"][0], h["span"][1]),
            origin=h["origin"],
            direction=h["direction"],
        )
        for h in highlights
    ]


def line_views(lines: list[dict]) -> list[AnswerLine]:
    return [AnswerLine(**line) for line in lines]


def _view(
    assignment: Assignment,
    actor: Actor,
    version: VignetteVersion,
    round_: ProofreadRound,
    rows: list[AnswerRevision],
) -> ProofreadView:
    return ProofreadView(
        review_round=round_.review_round,
        version=round_.version,
        editable=actor == Actor.ASSIGNEE
        and assignment.state == State.PROOFREAD_CHECK
        and round_.submitted_at is None,
        submitted_at=round_.submitted_at,
        feedback=[ProofreadFeedback(**item) for item in round_.feedback],
        highlights=highlight_views(round_.highlights),
        flags=[
            ProofreadFlag(kind=f["kind"], highlight=f["highlight"], message=f["message"])
            for f in round_.flags
        ],
        passes=round_.passes,
        items=[
            ProofreadItem(
                question_id=row.question_id,
                question=render_question(QUESTIONS[row.question_id], version.q4_whatif),
                original=row.original,
                proposed=row.proposed,
                final=row.final,
                linked=findings.is_filed(row.question_id),
                lines=line_views(row.lines),
                dropped=row.dropped,
            )
            for row in rows
        ],
    )


async def view(
    db: AsyncSession, assignment: Assignment, actor: Actor, review_round: int | None = None
) -> ProofreadView:
    """The author's and the admin's view. Reviewers read the submitted answers instead."""
    if actor == Actor.REVIEWER:
        raise not_found("Proofread")
    wanted = assignment.review_round if review_round is None else review_round
    round_ = await get_round(db, assignment.id, wanted)
    if round_ is None:
        raise not_found("Proofread")
    version, _ = await version_and_code(db, assignment.vignette_version_id)
    rows = await revisions(db, assignment.id, wanted, version.question_ids)
    return _view(assignment, actor, version, round_, rows)


# --- the author's edits ---------------------------------------------------------------------


def _check_overrides(
    overrides: dict[QuestionId, dict[str, list[str]]], highlights: list[dict]
) -> None:
    allowed = {h["id"] for h in highlights} | {findings.CASE}
    for question_id, by_line in overrides.items():
        for targets in by_line.values():
            if not targets:
                raise invalid(
                    "no_target", "A line has to belong somewhere: pick a quote or the case."
                )
            if unknown := [t for t in targets if t not in allowed]:
                raise invalid(
                    "unknown_target",
                    "That isn't one of your quotes.",
                    {"question_id": question_id, "targets": unknown},
                )


async def _editable_round(db: AsyncSession, assignment: Assignment, actor: Actor) -> ProofreadRound:
    if actor != Actor.ASSIGNEE:
        raise forbidden("Only the author can edit their answers.")
    if assignment.state != State.PROOFREAD_CHECK:
        raise DomainError(
            "not_editable",
            "The answers can only be edited while you are checking them.",
            details={"state": assignment.state.value},
        )
    round_ = await get_round(db, assignment.id, assignment.review_round, lock=True)
    assert round_ is not None and round_.submitted_at is None, "an open check has an open round"
    return round_


async def save(
    db: AsyncSession, assignment: Assignment, actor: Actor, body: ProofreadSave
) -> ProofreadView:
    round_ = await _editable_round(db, assignment, actor)
    if body.version != round_.version:
        raise DomainError(
            "proofread_conflict",
            "These answers were saved elsewhere. Reload them before continuing.",
            details={"current_version": round_.version},
        )
    version, _ = await version_and_code(db, assignment.vignette_version_id)
    rows = await revisions(db, assignment.id, assignment.review_round, version.question_ids)
    by_question = {row.question_id: row for row in rows}
    if unknown := [q for q in [*body.answers, *body.overrides] if q not in by_question]:
        raise invalid(
            "question_not_answered", "Only answers you gave can be edited.", {"ids": unknown}
        )
    highlights = [dict(h) for h in round_.highlights]
    chips = {h["chip"] for h in highlights if h["chip"] is not None}
    _check_overrides(body.overrides, highlights)
    for question_id, text in body.answers.items():
        check_chips(question_id, text, chips)
    for row in rows:
        text = body.answers.get(row.question_id, row.final)
        overrides = body.overrides.get(row.question_id, {})
        row.final = text
        if findings.is_filed(row.question_id):
            row.lines = links.relink(row.lines, text, overrides, highlights, version.text)
    round_.highlights = highlights
    filed = {row.question_id: row.lines for row in rows if findings.is_filed(row.question_id)}
    round_.flags = findings.check(highlights, links.as_sentences(filed))
    round_.version += 1
    round_.updated_at = utcnow()
    return _view(assignment, actor, version, round_, rows)


async def submit_for_review(
    db: AsyncSession, assignment: Assignment, actor: Actor, viewer: User
) -> None:
    check_transition(assignment.state, Action.SUBMIT_FOR_REVIEW, actor)
    round_ = await _editable_round(db, assignment, actor)
    version, _ = await version_and_code(db, assignment.vignette_version_id)
    rows = await revisions(db, assignment.id, assignment.review_round, version.question_ids)
    if empty := [row.question_id for row in rows if not row.final.strip()]:
        raise invalid(
            "empty_answer",
            f"{', '.join(empty)} need an answer before review.",
            {"question_ids": empty},
        )
    missing = {
        row.question_id: positions
        for row in rows
        if findings.is_filed(row.question_id) and (positions := links.unlinked(row.lines))
    }
    if missing:
        raise invalid(
            "links_missing",
            "Some sentences are not linked to a quote or the case yet.",
            {"lines": missing},
        )
    round_.submitted_at = utcnow()
    await transition(
        db,
        assignment,
        Action.SUBMIT_FOR_REVIEW,
        actor,
        viewer.id,
        {"review_round": assignment.review_round, "version": round_.version},
    )


async def open_next_round(
    db: AsyncSession, assignment: Assignment, feedback: list[dict[str, str]]
) -> None:
    """The admin sent the answers back: a new round starts from the last one's text and links.
    `assignment.review_round` is already the new round."""
    previous = await get_round(db, assignment.id, assignment.review_round - 1)
    assert previous is not None
    db.add(
        ProofreadRound(
            assignment_id=assignment.id,
            review_round=assignment.review_round,
            version=1,
            highlights=previous.highlights,
            flags=previous.flags,
            passes=previous.passes,
            classifier=previous.classifier,
            prompt=previous.prompt,
            feedback=feedback,
        )
    )
    await db.flush()
    rows = await db.scalars(
        select(AnswerRevision).where(
            AnswerRevision.assignment_id == assignment.id,
            AnswerRevision.review_round == assignment.review_round - 1,
        )
    )
    db.add_all(
        AnswerRevision(
            assignment_id=assignment.id,
            review_round=assignment.review_round,
            question_id=row.question_id,
            original=row.original,
            proposed=row.proposed,
            final=row.final,
            lines=row.lines,
            dropped=row.dropped,
        )
        for row in list(rows)
    )


# --- the proofread job ----------------------------------------------------------------------


async def prepare(assignment_id: UUID) -> dict[str, Any]:
    """Proofreads every written answer and links its lines. The slow part (LanguageTool, the
    models) runs with no transaction open."""
    async with session_factory()() as db:
        assignment = await db.get(Assignment, assignment_id)
        submission = await db.get(Submission, assignment_id)
        assert assignment is not None and submission is not None
        version, code = await version_and_code(db, assignment.vignette_version_id)
        payload, vignette, question_ids = submission.payload, version.text, version.question_ids
        q4_whatif = version.q4_whatif

    response = findings.response_from_submission(payload, code, version.version)
    quotes = {h.chip: h.text for h in response.highlights}
    answers: dict[str, str] = payload.get("answers", {})
    items, passes = [], {}
    for question_id in [q for q in question_ids if q in answers]:
        question = render_question(QUESTIONS[question_id], q4_whatif)
        result = await proofread_answer(question, answers[question_id], quotes, vignette)
        passes[question_id] = result.passes
        items.append(
            {
                "question_id": question_id,
                "original": answers[question_id],
                "proposed": result.text,
                "dropped": result.dropped,
            }
        )

    highlights = findings.expert_highlights(response.highlights)
    filed = {item["question_id"]: item["proposed"] for item in items}
    filed = {q: text for q, text in filed.items() if findings.is_filed(q)}
    linked = links.link_lines(filed, highlights, vignette)
    info = await links.classify_rest(linked, highlights, vignette)
    passes["links"] = info
    for item in items:
        item["lines"] = linked.get(item["question_id"], [])
    return {
        "items": items,
        "highlights": highlights,
        "flags": findings.check(highlights, links.as_sentences(linked)),
        "passes": passes,
        "classifier": settings.classifier_model if info["left"] else None,
        "prompt": classifier.PROMPT if info["left"] else None,
    }


async def record(db: AsyncSession, assignment: Assignment, prepared: dict[str, Any]) -> None:
    """Saves the proofread answers as round `assignment.review_round`. Running again replaces
    them."""
    await db.execute(
        delete(ProofreadRound).where(
            ProofreadRound.assignment_id == assignment.id,
            ProofreadRound.review_round == assignment.review_round,
        )
    )
    db.add(
        ProofreadRound(
            assignment_id=assignment.id,
            review_round=assignment.review_round,
            version=1,
            highlights=prepared["highlights"],
            flags=prepared["flags"],
            passes=prepared["passes"],
            classifier=prepared["classifier"],
            prompt=prepared["prompt"],
            feedback=[],
        )
    )
    await db.flush()
    db.add_all(
        AnswerRevision(
            assignment_id=assignment.id,
            review_round=assignment.review_round,
            question_id=item["question_id"],
            original=item["original"],
            proposed=item["proposed"],
            final=item["proposed"],
            lines=item["lines"],
            dropped=item["dropped"],
        )
        for item in prepared["items"]
    )
