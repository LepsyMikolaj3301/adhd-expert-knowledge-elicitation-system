"""Background worker: python -m app.jobs.worker. Run as many as needed."""

import asyncio
import contextlib
import logging
from uuid import UUID

from sqlalchemy import select, update

import app.models  # noqa: F401  (a worker runs without app.main: every table must be known)
from app.assignments.state_machine import lock_assignment, transition
from app.assignments.states import Action, Actor
from app.core.db import session_factory, utcnow
from app.core.errors import safe_traceback
from app.jobs.handlers import CORPUS_HANDLERS, HANDLERS, PREPARE, PermanentJobError
from app.jobs.models import Job, JobKind, JobStatus
from app.jobs.queue import LEASE, MAX_ATTEMPTS, next_job

logger = logging.getLogger(__name__)
POLL_SECONDS = 2.0

SUCCESS_ACTION = {
    JobKind.PROOFREAD: Action.PROOFREAD_SUCCEEDED,
    JobKind.PROCESS: Action.PROCESSING_SUCCEEDED,
    JobKind.INGEST: Action.INGESTION_SUCCEEDED,
}
FAILURE_ACTION = {
    JobKind.PROOFREAD: Action.PROOFREAD_FAILED,
    JobKind.PROCESS: Action.PROCESSING_FAILED,
    JobKind.INGEST: Action.INGESTION_FAILED,
}


async def _fail(db, job: Job, error: str) -> None:
    job.status = JobStatus.FAILED
    job.locked_until = None
    job.last_error = error
    if job.assignment_id is None:  # a corpus job: no workflow to move on
        return
    assignment = await lock_assignment(db, job.assignment_id)
    await transition(
        db, assignment, FAILURE_ACTION[job.kind], Actor.SYSTEM, None, {"job_id": str(job.id)}
    )


async def _current(db, job_id: UUID, attempt: int) -> Job | None:
    """The job, unless its lease expired and another worker has taken it since."""
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None or job.status != JobStatus.RUNNING or job.attempts != attempt:
        return None
    return job


async def _heartbeat(job_id: UUID, attempt: int) -> None:
    """Renews the lease while the job runs, so that a long job isn't taken over by another worker
    but a crashed one still is, one lease later."""
    factory = session_factory()
    while True:
        await asyncio.sleep(LEASE.total_seconds() / 3)
        try:
            async with factory() as db:
                await db.execute(
                    update(Job)
                    .where(
                        Job.id == job_id, Job.status == JobStatus.RUNNING, Job.attempts == attempt
                    )
                    .values(locked_until=utcnow() + LEASE)
                )
                await db.commit()
        except Exception as exc:  # a database outage must not end the job's own work
            logger.error("lease renewal failed\n%s", safe_traceback(exc))


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def run_once() -> bool:
    """Claim and run one job. Returns False when there was nothing to do."""
    factory = session_factory()
    async with factory() as db:
        job = await next_job(db)
        if job is None:
            return False
        if job.attempts >= MAX_ATTEMPTS:
            # Its last worker died mid-job: the lease expired with no attempts left.
            await _fail(db, job, "LeaseExpired")
            await db.commit()
            return True
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.locked_until = utcnow() + LEASE
        job_id, kind, assignment_id, attempt = job.id, job.kind, job.assignment_id, job.attempts
        await db.commit()

    # Slow work (the classifier, embeddings) happens in `prepare`, with no transaction and no row
    # lock open. Only recording the result takes the assignment lock, for as short as it can.
    heartbeat = asyncio.create_task(_heartbeat(job_id, attempt))
    try:
        try:
            if assignment_id is None:
                async with factory() as db:
                    job = await _current(db, job_id, attempt)
                    if job is None:
                        return True
                    await CORPUS_HANDLERS[kind](db)
                    job.status = JobStatus.DONE
                    job.locked_until = None
                    await db.commit()
                return True
            prepare = PREPARE.get(kind)
            prepared = await prepare(assignment_id) if prepare else None
            async with factory() as db:
                assignment = await lock_assignment(db, assignment_id)
                job = await _current(db, job_id, attempt)
                if job is None:
                    return True
                await HANDLERS[kind](db, assignment, prepared)
                job.status = JobStatus.DONE
                job.locked_until = None
                await transition(db, assignment, SUCCESS_ACTION[kind], Actor.SYSTEM, None)
                await db.commit()
        finally:
            await _stop(heartbeat)
    except Exception as exc:
        logger.error(
            "job %s (%s) failed on attempt %d\n%s",
            job_id,
            kind.value,
            attempt,
            safe_traceback(exc),
        )
        error = type(exc).__name__
        async with factory() as db:
            if assignment_id is not None:
                await lock_assignment(db, assignment_id)  # same lock order as the success path
            job = await _current(db, job_id, attempt)
            if job is not None:
                if isinstance(exc, PermanentJobError) or attempt >= MAX_ATTEMPTS:
                    await _fail(db, job, error)
                else:
                    job.status = JobStatus.QUEUED
                    job.locked_until = None
                    job.last_error = error
                await db.commit()
    return True


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("worker started")
    while True:
        try:
            found_work = await run_once()
        except Exception as exc:
            # E.g. Postgres restarting. A job caught in it is picked up again once its lease ends.
            logger.error("worker loop failed, trying again\n%s", safe_traceback(exc))
            found_work = False
        if not found_work:
            await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
