"""Claiming work from the `jobs` table. A worker holds a job through a lease, not a connection."""

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.jobs.models import Job, JobStatus

MAX_ATTEMPTS = 3
LEASE = timedelta(minutes=5)


async def next_job(db: AsyncSession) -> Job | None:
    """The oldest job that is queued, or running on a lease that has expired (a crashed worker).
    SKIP LOCKED lets several workers run side by side without taking the same job."""
    return await db.scalar(
        select(Job)
        .where(
            or_(
                Job.status == JobStatus.QUEUED,
                (Job.status == JobStatus.RUNNING) & (Job.locked_until < utcnow()),
            )
        )
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
