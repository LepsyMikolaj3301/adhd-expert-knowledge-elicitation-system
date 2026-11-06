"""The worker splits a job into slow work without a lock, and recording under the lock."""

import asyncio
from datetime import timedelta

from api_helpers import admin_api, answer_and_submit, assign, expert_api, published_version
from sqlalchemy import select, text

from app.assignments.states import Action
from app.core.db import session_factory
from app.jobs import handlers, queue, worker
from app.jobs.models import Job, JobKind, JobStatus
from app.jobs.worker import run_once


async def _submitted():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    return admin, expert, assignment_id


async def test_slow_preparation_holds_no_lock_on_the_assignment(monkeypatch):
    _, _, assignment_id = await _submitted()
    seen = {}

    async def prepare(assignment_id):
        async with session_factory()() as db:
            try:
                await db.execute(
                    text("SELECT id FROM app.assignments WHERE id = :id FOR UPDATE NOWAIT"),
                    {"id": assignment_id},
                )
                seen["lock_free"] = True
            except Exception:
                seen["lock_free"] = False
        return "prepared"

    async def record(db, assignment, prepared):
        seen["prepared"] = prepared

    monkeypatch.setitem(handlers.PREPARE, JobKind.PROCESS, prepare)
    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROCESS, record)
    assert await run_once() is True
    assert seen == {"lock_free": True, "prepared": "prepared"}


async def test_the_heartbeat_keeps_a_long_job_from_being_taken_over(monkeypatch):
    await _submitted()
    monkeypatch.setattr(queue, "LEASE", timedelta(seconds=0.3))
    monkeypatch.setattr(worker, "LEASE", timedelta(seconds=0.3))
    started = []

    async def slow_prepare(assignment_id):
        started.append(assignment_id)
        await asyncio.sleep(1.0)  # more than three leases

    async def record(db, assignment, prepared):
        return None

    monkeypatch.setitem(handlers.PREPARE, JobKind.PROCESS, slow_prepare)
    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROCESS, record)
    first = asyncio.create_task(run_once())
    await asyncio.sleep(0.7)  # the first lease ended long ago
    assert await run_once() is False, "another worker took a job that is still being worked on"
    assert await first is True
    assert len(started) == 1
    async with session_factory()() as db:
        job = await db.scalar(select(Job))
    assert job is not None and job.status == JobStatus.DONE


async def test_a_handler_can_choose_how_its_job_ends(monkeypatch):
    admin, _, assignment_id = await _submitted()

    async def record(db, assignment, prepared):
        return Action.PROCESSING_FAILED

    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROCESS, record)
    await run_once()
    view = await admin.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "processing_failed"
