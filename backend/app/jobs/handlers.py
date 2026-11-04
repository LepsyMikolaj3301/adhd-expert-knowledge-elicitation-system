"""What each job does. STUBS: processing and ingestion logic are out of scope for now.

The real pipeline replaces these bodies; the workflow around them stays the same.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment, Submission
from app.core.security import content_hash
from app.jobs.models import JobKind
from app.knowledge.models import KnowledgeUnit, UnitStatus
from app.settings import settings
from app.users.models import User
from app.vignettes.questions import QUESTIONS


class PermanentJobError(Exception):
    """Retrying can't help, so the job fails at once instead of using up its attempts."""


class SyntheticIngestionRefused(PermanentJobError):
    pass


Handler = Callable[[AsyncSession, Assignment], Awaitable[None]]


async def process(db: AsyncSession, assignment: Assignment) -> None:
    """Stub: nothing to compute yet, so the expert check has nothing to show."""


async def build_units(db: AsyncSession, assignment: Assignment) -> None:
    """Stub: one verbatim unit per answered open question. Replaced by real segmentation."""
    submission = await db.get(Submission, assignment.id)
    assert submission is not None
    answers: dict[str, str] = submission.payload["answers"]
    open_answers = [
        (question_id, answers[question_id])
        for question_id in QUESTIONS
        if QUESTIONS[question_id].kind == "open" and question_id in answers
    ]
    db.add_all(
        KnowledgeUnit(
            assignment_id=assignment.id,
            submission_id=submission.assignment_id,
            ordinal=ordinal,
            question_id=question_id,
            text=text,
            content_hash=content_hash(text),
        )
        for ordinal, (question_id, text) in enumerate(open_answers, start=1)
    )


async def ingest(db: AsyncSession, assignment: Assignment) -> None:
    """Stub: marks approved units as ingested. Nothing is written to the RAG tables yet."""
    is_synthetic = await db.scalar(select(User.is_synthetic).where(User.id == assignment.expert_id))
    if settings.environment == "production" and is_synthetic:
        raise SyntheticIngestionRefused(
            "synthetic answers can't enter the production knowledge base"
        )
    await db.execute(
        update(KnowledgeUnit)
        .where(
            KnowledgeUnit.assignment_id == assignment.id,
            KnowledgeUnit.status == UnitStatus.APPROVED,
        )
        .values(status=UnitStatus.INGESTED)
    )


HANDLERS: dict[JobKind, Handler] = {
    JobKind.PROCESS: process,
    JobKind.BUILD_UNITS: build_units,
    JobKind.INGEST: ingest,
}
