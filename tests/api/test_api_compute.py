"""With REQUIRE_COMPUTE on, a submit while the PC with the models is off is refused, end to end."""

import httpx
import pytest
from api_helpers import FULL_PAYLOAD, admin_api, assign, expert_api, published_version, save
from sqlalchemy import select

from app import compute
from app.core.db import session_factory
from app.jobs.models import Job, JobStatus
from app.jobs.worker import run_once
from app.settings import settings


def _pc(ollama_up: bool):
    def handler(request: httpx.Request) -> httpx.Response:
        if not ollama_up:
            raise httpx.ConnectError("down", request=request)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": settings.classifier_model}, {"name": "bge-m3:latest"}]},
            )
        return httpx.Response(200, json=[])

    return lambda base_url: httpx.AsyncClient(
        base_url=base_url, transport=httpx.MockTransport(handler)
    )


@pytest.fixture
def switched_on(monkeypatch):
    monkeypatch.setattr(settings, "require_compute", True)
    monkeypatch.setattr(settings, "enhance_model", "")
    compute.forget()
    yield
    compute.forget()


async def _started():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await expert.ok("POST", f"/assignments/{assignment_id}/start")
    await save(expert, assignment_id, FULL_PAYLOAD)
    return expert, assignment_id


async def test_submit_is_refused_while_the_pc_is_off(switched_on, monkeypatch):
    monkeypatch.setattr(compute, "client", _pc(ollama_up=False))
    expert, assignment_id = await _started()

    body = await expert.fails(
        "POST", f"/assignments/{assignment_id}/submit", 503, "compute_unavailable"
    )
    assert body["details"]["missing"][0] == "ollama"
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "in_progress"


async def test_the_same_submit_goes_through_once_the_pc_is_on(switched_on, monkeypatch):
    monkeypatch.setattr(compute, "client", _pc(ollama_up=True))
    expert, assignment_id = await _started()

    await expert.ok("POST", f"/assignments/{assignment_id}/submit")
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "proofreading"


async def _job() -> Job:
    async with session_factory()() as db:
        job = await db.scalar(select(Job))
    assert job is not None
    return job


async def test_a_pc_that_goes_off_after_the_submit_holds_the_job_without_using_attempts(
    switched_on, monkeypatch, models
):
    monkeypatch.setattr(compute, "client", _pc(ollama_up=True))
    expert, assignment_id = await _started()
    await expert.ok("POST", f"/assignments/{assignment_id}/submit")

    # Off before the worker gets to it; the worker still trusts the probe of the submit.
    monkeypatch.setattr(compute, "client", _pc(ollama_up=False))
    models.grammar_down = True
    assert await run_once() is True
    job = await _job()
    assert (job.status, job.attempts) == (JobStatus.QUEUED, 0), "the failure used up an attempt"
    # Now the worker knows the PC is off: the job is not taken again.
    assert await run_once() is False

    monkeypatch.setattr(compute, "client", _pc(ollama_up=True))
    models.grammar_down = False
    compute.forget()
    assert await run_once() is True
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "proofread_check"
    assert (await _job()).attempts == 1
