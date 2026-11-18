"""Knowledge units as the admin reads them: the unit, its case and expert, and how it was cut."""

from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.answers import Direction
from app.assignments.models import Assignment
from app.knowledge.models import AnswerFindings, KnowledgeUnit
from app.knowledge.schemas import CitedTogether, KnowledgeUnitListItem, UnitSentence
from app.users.models import User
from app.vignettes.models import Vignette, VignetteVersion


async def unit_items(
    db: AsyncSession,
    *conditions: ColumnElement[bool],
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeUnitListItem]:
    """The units matching `conditions`, newest first, with the findings record of each one's
    assignment read for the sentences and the quotes cited together."""
    query = (
        select(
            KnowledgeUnit,
            Vignette.code,
            VignetteVersion.version,
            VignetteVersion.framing,
            User.id,
            User.pseudonym,
        )
        .join(Assignment, Assignment.id == KnowledgeUnit.assignment_id)
        .join(VignetteVersion, VignetteVersion.id == Assignment.vignette_version_id)
        .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
        .join(User, User.id == Assignment.expert_id)
        .where(*conditions)
        .order_by(KnowledgeUnit.created_at.desc(), KnowledgeUnit.ordinal, KnowledgeUnit.id)
        .offset(offset)
    )
    if limit is not None:
        query = query.limit(limit)
    rows = (await db.execute(query)).all()
    findings = await _findings(db, {unit.assignment_id for unit, *_ in rows})
    return [
        _item(
            unit,
            code,
            version,
            framing,
            expert_id,
            pseudonym,
            findings.get(unit.assignment_id),
        )
        for unit, code, version, framing, expert_id, pseudonym in rows
    ]


async def _findings(db: AsyncSession, assignment_ids: set[UUID]) -> dict[UUID, AnswerFindings]:
    if not assignment_ids:
        return {}
    rows = await db.scalars(
        select(AnswerFindings).where(AnswerFindings.assignment_id.in_(assignment_ids))
    )
    return {row.assignment_id: row for row in rows}


def _item(
    unit: KnowledgeUnit,
    code: str,
    version: int,
    framing: str | None,
    expert_id: UUID,
    pseudonym: str,
    findings: AnswerFindings | None,
) -> KnowledgeUnitListItem:
    record = findings.record if findings else {}
    return KnowledgeUnitListItem(
        id=unit.id,
        assignment_id=unit.assignment_id,
        vignette_code=code,
        vignette_version=version,
        expert_id=expert_id,
        expert_pseudonym=pseudonym,
        ordinal=unit.ordinal,
        review_round=unit.review_round,
        text=unit.text,
        kind=unit.kind,
        highlight_id=unit.highlight_id,
        direction=cast(Direction | None, unit.direction),
        patient_words=unit.patient_words,
        status=unit.status,
        created_at=unit.created_at,
        embed_text=unit.embed_text,
        embed_text_combined=unit.embed_text_combined,
        sentences=_sentences(unit.sentence_ids or [], record),
        context=_context(unit.context or [], record),
        framing=framing,
        classifier=findings.classifier if findings else None,
        prompt=findings.prompt if findings else None,
        findings_version=findings.findings_version if findings else None,
    )


def _sentences(ids: Sequence[str], record: dict) -> list[UnitSentence]:
    """The unit's sentences in the order it was built, each with how it was filed. The record
    is the expert's current one: a sentence it no longer holds is left out, not guessed."""
    by_id = {s["id"]: s for s in record.get("sentences", [])}
    return [
        UnitSentence(
            id=i, question_id=by_id[i]["question_id"], assigned_by=by_id[i].get("assigned_by")
        )
        for i in ids
        if i in by_id
    ]


def _context(ids: Sequence[str], record: dict) -> list[CitedTogether]:
    by_id = {h["id"]: h for h in record.get("highlights", [])}
    return [CitedTogether(id=i, text=by_id[i]["text"]) for i in ids if i in by_id]
