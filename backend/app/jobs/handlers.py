"""What each job does: file the answers, build the units, ingest the approved ones."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment, Submission
from app.assignments.states import Action
from app.core.db import session_factory, utcnow
from app.core.security import content_hash
from app.jobs.errors import (  # noqa: F401  (PermanentJobError is also imported from here)
    NoFindings,
    NoUnits,
    PermanentJobError,
    SyntheticIngestionRefused,
)
from app.jobs.models import JobKind
from app.knowledge import classifier, findings
from app.knowledge import ingest as ingest_module
from app.knowledge.models import AnswerFindings, KnowledgeUnit, UnitStatus
from app.reviews.models import ReviewRequest, ReviewStage
from app.reviews.service import eligible_peers
from app.settings import settings
from app.users.models import User
from app.vignettes.models import Vignette, VignetteVersion

# What a job does has two parts. `PREPARE[kind](assignment_id)` is the slow part (models, network):
# it runs with no transaction and no lock open, and returns what `HANDLERS[kind]` needs. The
# handler then records the result, under the assignment lock, in the transaction that also moves
# the workflow on. It may return the action to use instead of the job's usual success action.
Prepare = Callable[[UUID], Awaitable[Any]]
Handler = Callable[[AsyncSession, Assignment, Any], Awaitable[Action | None]]
PREPARE: dict[JobKind, Prepare] = {}


async def prepare_process(assignment_id: UUID) -> dict[str, Any]:
    """Files the submitted answers' sentences under the expert's citations (steps 2 to 4 of
    docs/new-chips-knowledge.md). The slow part is the classifier call: no transaction is open."""
    async with session_factory()() as db:
        assignment = await db.get(Assignment, assignment_id)
        submission = await db.get(Submission, assignment_id)
        assert assignment is not None and submission is not None
        row = (
            await db.execute(
                select(VignetteVersion, Vignette.code)
                .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
                .where(VignetteVersion.id == assignment.vignette_version_id)
            )
        ).one()
        version, code = row[0], row[1]
        expert = await db.get(User, assignment.expert_id)
        assert expert is not None
        payload, text, framing, design = (
            submission.payload,
            version.text,
            version.framing,
            version.design,
        )
        number, expert_id, is_synthetic = version.version, expert.id, expert.is_synthetic

    response = findings.response_from_submission(payload, code, number)
    highlights, sentences = findings.assign(response, text)
    left = findings.unresolved(sentences)
    labels, info = await classifier.classify(text, highlights, sentences, left)
    record = findings.build_record(
        response,
        text,
        str(assignment_id),
        str(expert_id),
        None,  # experts have no role yet
        framing,
        design.get("population", "adult"),
        labels if left else None,
    )
    record |= {
        # What the expert is shown, as ids: the flags themselves quote their words and change as
        # they correct things, but the evaluation wants to know what was shown.
        "flags_shown": [
            {"kind": f["kind"], "highlight": f["highlight"], "sentence": f.get("sentence")}
            for f in record["flags"]
        ],
        "track": design.get("track", "general"),
        "origin": design.get("origin", "hand_written"),
        "is_synthetic": is_synthetic,
        "corrections": [],
    }
    return {
        "record": record,
        "classifier": settings.classifier_model if left else None,
        "prompt": classifier.PROMPT if left else None,
        "attempts": info["attempts"],
    }


async def process(db: AsyncSession, assignment: Assignment, prepared: Any = None) -> Action | None:
    """Saves the findings for the expert to check. Running again replaces them."""
    row = await db.get(AnswerFindings, assignment.id)
    if row is None:
        row = AnswerFindings(assignment_id=assignment.id, version=1)
        db.add(row)
    row.record = prepared["record"]
    row.classifier = prepared["classifier"]
    row.prompt = prepared["prompt"]
    row.findings_version = findings.FINDINGS_VERSION
    row.check_outcome = None
    return None


def unit_content_hash(embed_text: str, embed_text_combined: str) -> str:
    """What an approval is for: both texts that will be embedded, not only the one shown."""
    return content_hash(embed_text + "\n" + embed_text_combined)


async def build_units(
    db: AsyncSession, assignment: Assignment, prepared: Any = None
) -> Action | None:
    """Cuts the checked filing into units (steps 6 and 7 of docs/new-chips-knowledge.md), saves
    them for review, and asks the colleagues who can review them, if there are any."""
    row = await db.get(AnswerFindings, assignment.id)
    if row is None:
        raise NoFindings
    record = row.record
    by_id = {h["id"]: h for h in record["highlights"]}
    units = findings.build_units(record)  # from the corrected sentences, never from a stale copy
    if not units:
        raise NoUnits
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
        )
        for ordinal, unit in enumerate(units, start=1)
    )
    peers = await eligible_peers(db, assignment)
    if not peers:
        return None  # the admin decides alone
    assignment.required_approvals = 1
    # In a later round the same peers are asked again: their closed request is reopened.
    earlier = {
        request.reviewer_id: request
        for request in await db.scalars(
            select(ReviewRequest).where(
                ReviewRequest.assignment_id == assignment.id,
                ReviewRequest.stage == ReviewStage.PEER,
            )
        )
    }
    for peer_id in peers:
        if request := earlier.get(peer_id):
            request.completed_at = None
            request.requested_at = utcnow()
        else:
            db.add(
                ReviewRequest(
                    assignment_id=assignment.id,
                    reviewer_id=peer_id,
                    stage=ReviewStage.PEER,
                    requested_by=None,  # the system asked
                )
            )
    return Action.UNITS_BUILT_FOR_PEERS


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


PREPARE[JobKind.PROCESS] = prepare_process
PREPARE[JobKind.INGEST] = prepare_ingest

HANDLERS: dict[JobKind, Handler] = {
    JobKind.PROCESS: process,
    JobKind.BUILD_UNITS: build_units,
    JobKind.INGEST: ingest,
}
