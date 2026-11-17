"""The check that the PC with Ollama and LanguageTool is up (app/compute.py), without a network."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app import compute
from app.assignments import state_machine
from app.assignments.states import Action, Actor, State
from app.core.errors import DomainError
from app.jobs.models import JobKind
from app.settings import settings

OLLAMA = "http://pc-ollama"
LANGUAGETOOL = "http://pc-languagetool"
MODELS = ["qwen3.5:9b", "bge-m3:latest"]


@pytest.fixture(autouse=True)
def pc(monkeypatch):
    """A PC that answers, unless a test changes `state`. The check is switched on."""
    state = SimpleNamespace(ollama=True, languagetool=True, models=list(MODELS), calls=[])

    def handler(request: httpx.Request) -> httpx.Response:
        state.calls.append(str(request.url))
        if request.url.host == "pc-ollama":
            if not state.ollama:
                raise httpx.ConnectError("down", request=request)
            return httpx.Response(200, json={"models": [{"name": n} for n in state.models]})
        if not state.languagetool:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json=[{"name": "English", "code": "en"}])

    def client(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(compute, "client", client)
    monkeypatch.setattr(compute, "_embedding_model", lambda: "bge-m3")
    monkeypatch.setattr(settings, "require_compute", True)
    monkeypatch.setattr(settings, "ollama_base_url", OLLAMA)
    monkeypatch.setattr(settings, "languagetool_url", LANGUAGETOOL)
    monkeypatch.setattr(settings, "classifier_model", "qwen3.5:9b")
    monkeypatch.setattr(settings, "enhance_model", "qwen3.5:9b")
    compute.forget()
    yield state
    compute.forget()


async def test_it_is_off_unless_switched_on(pc, monkeypatch):
    monkeypatch.setattr(settings, "require_compute", False)
    pc.ollama = pc.languagetool = False
    await compute.require_compute(JobKind.PROOFREAD)
    assert pc.calls == []


@pytest.mark.parametrize("kind", [JobKind.PROOFREAD, JobKind.PROCESS, JobKind.INGEST])
async def test_a_pc_that_answers_passes(kind):
    await compute.require_compute(kind)


async def test_ollama_down_is_a_503(pc):
    pc.ollama = False
    with pytest.raises(DomainError) as caught:
        await compute.require_compute(JobKind.PROOFREAD)
    assert caught.value.code == "compute_unavailable"
    assert caught.value.status_code == 503
    assert "Ollama" in caught.value.message
    assert caught.value.details is not None
    assert "ollama" in caught.value.details["missing"]


async def test_a_model_that_was_not_pulled_is_named(pc):
    pc.models = ["bge-m3:latest"]
    with pytest.raises(DomainError) as caught:
        await compute.require_compute(JobKind.PROOFREAD)
    assert "qwen3.5:9b" in caught.value.message
    assert caught.value.details == {"missing": ["model qwen3.5:9b"]}


async def test_a_model_without_a_tag_matches_latest(pc):
    pc.models = ["bge-m3:latest"]
    await compute.require_compute(JobKind.INGEST)


async def test_languagetool_down_stops_proofreading_only(pc):
    pc.languagetool = False
    with pytest.raises(DomainError) as caught:
        await compute.require_compute(JobKind.PROOFREAD)
    assert caught.value.details == {"missing": ["languagetool"]}
    await compute.require_compute(JobKind.INGEST)


async def test_an_empty_enhance_model_is_not_required(pc, monkeypatch):
    monkeypatch.setattr(settings, "enhance_model", "")
    pc.models = ["qwen3.5:9b"]
    await compute.require_compute(JobKind.PROOFREAD)


async def test_ingestion_needs_the_embedding_model_not_the_classifier(pc):
    pc.models = ["qwen3.5:9b"]
    with pytest.raises(DomainError) as caught:
        await compute.require_compute(JobKind.INGEST)
    assert caught.value.details == {"missing": ["model bge-m3"]}


async def test_approving_checks_the_embedding_model_that_ingestion_will_need(pc):
    """Cutting into units calls no model, but the ingestion that follows it does."""
    pc.models = ["qwen3.5:9b"]
    pc.languagetool = False
    with pytest.raises(DomainError) as caught:
        await compute.require_compute(JobKind.PROCESS)
    assert caught.value.details == {"missing": ["model bge-m3"]}


async def test_a_kind_that_needs_nothing_asks_nothing(pc):
    pc.ollama = pc.languagetool = False
    await compute.require_compute(JobKind.REFIT)
    assert pc.calls == []


async def test_everything_missing_is_reported_at_once(pc):
    pc.ollama = pc.languagetool = False
    with pytest.raises(DomainError) as caught:
        await compute.require_compute(JobKind.PROOFREAD)
    assert caught.value.details == {"missing": ["ollama", "languagetool"]}


# --- the probe is reused, so a request doesn't wait on the network --------------------------


async def test_a_recent_probe_is_reused(pc):
    await compute.require_compute(JobKind.PROOFREAD)
    calls = len(pc.calls)
    pc.ollama = False  # not seen until the probe is redone
    await compute.require_compute(JobKind.PROOFREAD)
    assert len(pc.calls) == calls


async def test_an_old_probe_is_redone(pc, monkeypatch):
    await compute.require_compute(JobKind.PROOFREAD)
    pc.ollama = False
    monkeypatch.setattr(compute, "API_TRUSTS", -1.0)
    with pytest.raises(DomainError):
        await compute.require_compute(JobKind.PROOFREAD)


async def test_the_watcher_keeps_probing(pc, monkeypatch):
    monkeypatch.setattr(compute, "WATCH_EVERY", 0.01)
    task = asyncio.create_task(compute.watch())
    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert len(pc.calls) >= 4  # two requests per probe


# --- the worker -----------------------------------------------------------------------------


async def test_the_worker_runs_everything_while_the_check_is_off(pc, monkeypatch):
    monkeypatch.setattr(settings, "require_compute", False)
    assert await compute.ready_kinds() is None
    assert not await compute.is_down_for(JobKind.PROOFREAD)


async def test_the_worker_holds_back_only_the_jobs_whose_machine_is_down(pc):
    pc.languagetool = False
    assert await compute.ready_kinds() == {JobKind.PROCESS, JobKind.INGEST, JobKind.REFIT}
    pc.ollama = False
    compute.forget()
    assert await compute.ready_kinds() == {JobKind.PROCESS, JobKind.REFIT}


async def test_after_a_failure_the_worker_asks_the_pc_again(pc):
    assert await compute.ready_kinds() == set(JobKind)
    pc.ollama = False
    assert await compute.is_down_for(JobKind.INGEST)
    assert not await compute.is_down_for(JobKind.PROCESS)


# --- where the check sits: transition() ----------------------------------------------------


class _Db:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)


@pytest.fixture
def workflow(monkeypatch):
    checked: list[JobKind] = []

    async def fake_require(kind: JobKind) -> None:
        checked.append(kind)
        if fake_require.down:
            raise DomainError("compute_unavailable", "down", 503)

    fake_require.down = False
    monkeypatch.setattr(state_machine, "require_compute", fake_require)
    monkeypatch.setattr(state_machine, "record_event", lambda *a, **k: None)
    return SimpleNamespace(checked=checked, check=fake_require, db=_Db())


async def test_a_person_moving_an_assignment_into_a_job_is_checked(workflow):
    assignment = SimpleNamespace(id=uuid4(), state=State.IN_PROGRESS)
    await state_machine.transition(workflow.db, assignment, Action.SUBMIT, Actor.ASSIGNEE, uuid4())
    assert workflow.checked == [JobKind.PROOFREAD]
    assert assignment.state == State.PROOFREADING
    assert len(workflow.db.added) == 1


async def test_a_503_leaves_the_assignment_and_the_queue_untouched(workflow):
    workflow.check.down = True
    assignment = SimpleNamespace(id=uuid4(), state=State.IN_PROGRESS)
    with pytest.raises(DomainError) as caught:
        await state_machine.transition(
            workflow.db, assignment, Action.SUBMIT, Actor.ASSIGNEE, uuid4()
        )
    assert caught.value.status_code == 503
    assert assignment.state == State.IN_PROGRESS
    assert workflow.db.added == []


async def test_the_workers_own_transitions_are_not_checked(workflow):
    assignment = SimpleNamespace(id=uuid4(), state=State.PROCESSING)
    await state_machine.transition(
        workflow.db, assignment, Action.PROCESSING_SUCCEEDED, Actor.SYSTEM, None
    )
    assert assignment.state == State.INGESTING
    assert workflow.checked == []
    assert len(workflow.db.added) == 1


async def test_a_move_that_queues_no_job_is_not_checked(workflow):
    assignment = SimpleNamespace(id=uuid4(), state=State.ASSIGNED)
    await state_machine.transition(workflow.db, assignment, Action.START, Actor.ASSIGNEE, uuid4())
    assert workflow.checked == []
