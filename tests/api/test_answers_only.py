"""The answers-only deployment: experts answer and submit, and nothing follows a submission up."""

import api_helpers
import pytest
from api_helpers import (
    FULL_PAYLOAD,
    admin_api,
    answer_and_submit,
    assign,
    expert_api,
    published_version,
)
from sqlalchemy import select

from app.core.db import session_factory
from app.jobs.models import Job, JobKind, JobStatus
from app.main import create_app
from app.settings import settings


@pytest.fixture(autouse=True)
def answers_only(monkeypatch):
    """The routers are chosen when the app is built, so build one with the flag on."""
    monkeypatch.setattr(settings, "answers_only", True)
    monkeypatch.setattr(api_helpers, "app", create_app())


# List endpoints that answer 200 whenever they exist, so a 404 can only mean the route is gone.
EXTRA_LISTS = ["/me/home", "/reviews", "/knowledge-units"]


async def test_review_knowledge_and_home_routes_are_gone():
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    for path in EXTRA_LISTS:
        response = await admin.request("GET", path)
        assert response.status_code == 404, f"GET {path}: {response.status_code}"
    paths = (await admin.ok("GET", "/openapi.json"))["paths"]
    assert not [p for p in paths if p.startswith(("/reviews", "/knowledge", "/me/"))]
    assert not [p for p in paths if p.endswith(("/units", "/votes", "/unit-decisions"))]
    assert not [p for p in paths if "/review/" in p or "/comments" in p]
    # What the experts need is still there.
    await expert.ok("GET", "/assignments")
    await admin.ok("GET", "/vignettes")


async def test_submit_keeps_the_answers_and_queues_a_job_nobody_runs():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    version = await published_version(admin)
    [assignment_id] = await assign(admin, version, expert)

    await answer_and_submit(expert, assignment_id)

    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "processing"
    submission = await expert.ok("GET", f"/assignments/{assignment_id}/submission")
    assert submission["payload"]["answers"] == FULL_PAYLOAD["answers"]

    async with session_factory()() as db:
        jobs = list(await db.scalars(select(Job)))
    assert [(j.kind, j.status) for j in jobs] == [(JobKind.PROCESS, JobStatus.QUEUED)]

    # The page must not poll for a job that no worker will ever run.
    [summary] = await expert.ok("GET", "/assignments")
    assert summary["state"] == "processing"
    assert summary["job_running"] is False
    [summary] = await admin.ok("GET", "/assignments")
    assert summary["job_running"] is False


async def test_experts_cannot_read_each_others_answers():
    admin = await admin_api()
    first, second = await expert_api("e1@example.com"), await expert_api("e2@example.com")
    version = await published_version(admin)
    one, two = await assign(admin, version, first, second)
    await answer_and_submit(first, one)

    # A colleague gets nothing of a submitted case, however they ask.
    assert (await second.request("GET", f"/assignments/{one}")).status_code in (403, 404)
    assert (await second.request("GET", f"/assignments/{one}/submission")).status_code in (
        403,
        404,
    )
    assert [a["id"] for a in await second.ok("GET", "/assignments")] == [two]
    # The admin still can, for the export.
    await admin.ok("GET", f"/assignments/{one}/submission")


async def test_the_flag_is_off_by_default(monkeypatch):
    monkeypatch.setattr(settings, "answers_only", False)
    monkeypatch.setattr(api_helpers, "app", create_app())
    admin = await admin_api()
    for path in EXTRA_LISTS:
        await admin.ok("GET", path)
