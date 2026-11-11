"""What each job does: proofread the answers, cut the approved ones into units, ingest them."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment, Submission
from app.assignments.states import Action
from app.core.db import session_factory
from app.core.security import content_hash
from app.jobs.errors import (  # noqa: F401  (PermanentJobError is also imported from here)
    NoFindings,
    NoUnits,
    PermanentJobError,
    SyntheticIngestionRefused,
)
from app.jobs.models import JobKind
from app.knowledge import findings
from app.knowledge import ingest as ingest_module
from app.knowledge.models import AnswerFindings, KnowledgeUnit, UnitStatus
from app.proofread import service as proofread_service
from app.reviews.models import AnswerDecision, DecisionValue
from app.users.models import User

# What a job does has two parts. `PREPARE[kind](assignment_id)` is the slow part (models, network):
# it runs with no transaction and no lock open, and returns what `HANDLERS[kind]` needs. The
# handler then records the result, under the assignment lock, in the transaction that also moves
# the workflow on. It may return the action to use instead of the job's usual success action.
Prepare = Callable[[UUID], Awaitable[Any]]
Handler = Callable[[AsyncSession, Assignment, Any], Awaitable[Action | None]]
PREPARE: dict[JobKind, Prepare] = {}


async def prepare_proofread(assignment_id: UUID) -> dict[str, Any]:
    """Proofreads the submitted answers and links their lines to the citations. The slow part
    (LanguageTool, the models) runs with no transaction open."""
    return await proofread_service.prepare(assignment_id)


async def proofread(db: AsyncSession, assignment: Assignment, prepared: Any) -> Action | None:
    """Saves the proofread answers for the author to check."""
    await proofread_service.record(db, assignment, prepared)
    return None


def unit_content_hash(embed_text: str, embed_text_combined: str) -> str:
    """Both texts that will be embedded, not only the one shown."""
    return content_hash(embed_text + "\n" + embed_text_combined)


async def process(db: AsyncSession, assignment: Assignment, prepared: Any = None) -> Action | None:
    """Cuts the answers the admin approved into units (steps 6 and 7 of
    docs/new-chips-knowledge.md), from their lines as the author linked them. The units are
    approved with their answers; nobody reads them before ingestion."""
    submission = await db.get(Submission, assignment.id)
    round_ = await proofread_service.get_round(db, assignment.id, assignment.review_round)
    expert = await db.get(User, assignment.expert_id)
    assert expert is not None
    if submission is None or round_ is None:
        raise NoFindings
    version, code = await proofread_service.version_and_code(db, assignment.vignette_version_id)
    approved = set(
        await db.scalars(
            select(AnswerDecision.question_id).where(
                AnswerDecision.assignment_id == assignment.id,
                AnswerDecision.review_round == assignment.review_round,
                AnswerDecision.decision == DecisionValue.APPROVE,
            )
        )
    )
    rows = [
        row
        for row in await proofread_service.revisions(
            db, assignment.id, assignment.review_round, version.question_ids
        )
        if row.question_id in approved
    ]
    payload = {**submission.payload, "answers": {row.question_id: row.final for row in rows}}
    response = findings.response_from_submission(payload, code, version.version)
    record = findings.record_from_lines(
        response,
        {row.question_id: row.lines for row in rows},
        round_.highlights,
        str(assignment.id),
        str(expert.id),
        None,  # experts have no role yet
        version.framing,
        version.design.get("population", "adult"),
    )
    record |= {
        # What the author was shown, as ids: the evaluation wants to know what was shown.
        "flags_shown": [
            {"kind": f["kind"], "highlight": f["highlight"], "sentence": f.get("sentence")}
            for f in round_.flags
        ],
        "track": version.design.get("track", "general"),
        "origin": version.design.get("origin", "hand_written"),
        "is_synthetic": expert.is_synthetic,
        "corrections": [],
    }
    units = record["units"]
    if not units:
        raise NoUnits
    row = await db.get(AnswerFindings, assignment.id)
    if row is None:
        row = AnswerFindings(assignment_id=assignment.id, version=1)
        db.add(row)
    row.record = record
    row.classifier = round_.classifier
    row.prompt = round_.prompt
    row.findings_version = findings.FINDINGS_VERSION
    row.check_outcome = "completed"
    by_id = {h["id"]: h for h in record["highlights"]}
    db.add_all(
        KnowledgeUnit(
            assignment_id=assignment.id,
            submission_id=assignment.id,
            ordinal=ordinal,
            review_round=assignment.review_round,
            text=unit["body"],
            content_hash=unit_content_hash(unit["i1"], unit["i3"]),
            kind=unit["kind"],
            highlight_id=unit["highlight"],
            direction=unit["direction"],
            patient_words=by_id[unit["highlight"]]["text"] if unit["highlight"] else None,
            sentence_ids=unit["sentences"],
            context=unit["context"],
            embed_text=unit["i1"],
            embed_text_combined=unit["i3"],
            status=UnitStatus.APPROVED,
        )
        for ordinal, unit in enumerate(units, start=1)
    )
    return None


async def prepare_ingest(assignment_id: UUID) -> ingest_module.Ingestion:
    """Reads what was approved and embeds it. Refuses synthetic answers in production first."""
    async with session_factory()() as db:
        data = await ingest_module.load(db, assignment_id)
    return await ingest_module.embed(data)


async def ingest(
    db: AsyncSession, assignment: Assignment, prepared: ingest_module.Ingestion
) -> Action | None:
    """Writes the approved units into the RAG tables and marks them ingested."""
    await ingest_module.write(db, prepared)
    await db.execute(
        update(KnowledgeUnit)
        .where(
            KnowledgeUnit.assignment_id == assignment.id,
            KnowledgeUnit.status == UnitStatus.APPROVED,
        )
        .values(status=UnitStatus.INGESTED)
    )
    return None


PREPARE[JobKind.PROOFREAD] = prepare_proofread
PREPARE[JobKind.INGEST] = prepare_ingest

HANDLERS: dict[JobKind, Handler] = {
    JobKind.PROOFREAD: proofread,
    JobKind.PROCESS: process,
    JobKind.INGEST: ingest,
}
