"""The admin takes units out of the knowledge base: one unit, or everything an expert gave. The
chips rows go at once; the BM25 weights are refit by a `refit` job on the worker."""

from uuid import UUID

from api_helpers import (
    admin_api,
    answer_and_submit,
    assign,
    decide_all,
    expert_api,
    published_version,
    run_jobs,
    to_review,
)
from sqlalchemy import select, text
from test_api_pipeline import chips, count, ingested_single, units_of

from app.audit.models import AuditEvent
from app.core.db import session_factory
from app.jobs.models import Job, JobKind, JobStatus
from app.jobs.worker import run_once


async def _listed(admin) -> list[dict]:
    return await admin.ok("GET", "/knowledge-units", params={"status": "ingested"})


async def _refit_jobs() -> list[Job]:
    async with session_factory()() as db:
        return list(await db.scalars(select(Job).where(Job.kind == JobKind.REFIT)))


async def _ingest(admin, expert) -> str:
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    await to_review(expert, assignment_id)
    await decide_all(admin, assignment_id)
    await run_jobs()
    return assignment_id


async def test_removing_a_unit_takes_it_out_of_retrieval_and_queues_a_refit(models):
    admin, _, assignment_id = await ingested_single(models)
    listed = await _listed(admin)
    fragment = next(u for u in listed if u["kind"] == "fragment")
    assert fragment["expert_id"]
    units_before = await count("finding_units")
    assert await admin.ok("GET", "/knowledge-units/index") == {
        "state": "up_to_date",
        "last_error": None,
    }

    await admin.ok("DELETE", f"/knowledge-units/{fragment['id']}", 204)

    assert fragment["id"] not in {u["id"] for u in await _listed(admin)}
    statuses = {str(u.id): u.status for u in await units_of(assignment_id)}
    assert statuses[fragment["id"]] == "removed"
    assert await count("finding_units") == units_before - 1
    [(document,)] = await chips(
        "SELECT document FROM chips.elicitation_sessions WHERE id = :sid", sid=assignment_id
    )
    assert "h1" not in {u["id"] for u in document["units"]}
    # A search no longer finds it, even by its own text.
    found = await admin.ok(
        "POST", "/knowledge-units/search", json={"query": fragment["embed_text"], "k": 20}
    )
    assert fragment["id"] not in {h["unit"]["id"] for h in found["hits"]}

    async with session_factory()() as db:
        [event] = await db.scalars(select(AuditEvent).where(AuditEvent.action == "unit_removed"))
    assert event.entity_id == UUID(fragment["id"]) and event.to_state == "removed"

    [job] = await _refit_jobs()
    assert job.assignment_id is None and job.status == JobStatus.QUEUED
    assert (await admin.ok("GET", "/knowledge-units/index"))["state"] == "queued"
    async with session_factory()() as db:  # so the refit has something to show for itself
        await db.execute(text("UPDATE chips.finding_units SET sparse = NULL"))
        await db.commit()
    assert await run_once() is True
    assert (await admin.ok("GET", "/knowledge-units/index"))["state"] == "up_to_date"
    assert await chips("SELECT id FROM chips.finding_units WHERE sparse IS NULL") == []
    # The assignment's workflow is untouched by a corpus job.
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "ingested"


async def test_removing_the_last_unit_drops_the_answer_from_chips(models):
    admin, _, assignment_id = await ingested_single(models)
    for unit in await _listed(admin):
        await admin.ok("DELETE", f"/knowledge-units/{unit['id']}", 204)
    assert await count("elicitation_sessions") == 0
    assert await count("finding_units") == 0
    assert await count("cue_keys") == 0
    assert await count("experts") == 0
    # Several removals, one waiting refit.
    assert len(await _refit_jobs()) == 1


async def test_an_experts_knowledge_is_withdrawn_from_every_case_and_only_theirs(models):
    admin = await admin_api()
    leaving, staying = await expert_api("e1@example.com"), await expert_api("e2@example.com")
    first, second = await _ingest(admin, leaving), await _ingest(admin, leaving)
    kept = await _ingest(admin, staying)
    listed = await _listed(admin)
    leaving_id = next(u["expert_id"] for u in listed if u["assignment_id"] == first)
    theirs = [u for u in listed if u["expert_id"] == leaving_id]
    assert {u["assignment_id"] for u in theirs} == {first, second}

    body = await admin.ok("DELETE", f"/knowledge-units/by-expert/{leaving_id}")

    assert body == {"removed": len(theirs)}
    assert {u["assignment_id"] for u in await _listed(admin)} == {kept}
    assert [r[0] for r in await chips("SELECT id FROM chips.elicitation_sessions")] == [kept]
    assert [r[0] for r in await chips("SELECT id FROM chips.experts")] != [leaving_id]
    async with session_factory()() as db:
        [event] = await db.scalars(
            select(AuditEvent).where(AuditEvent.action == "knowledge_withdrawn")
        )
    assert event.meta == {"units": len(theirs)}
    # Nothing left to remove is not an error.
    assert await admin.ok("DELETE", f"/knowledge-units/by-expert/{leaving_id}") == {"removed": 0}


async def test_only_ingested_units_can_be_removed_and_only_by_the_admin(models):
    admin, expert, _ = await ingested_single(models)
    unit = (await _listed(admin))[0]
    await expert.fails("DELETE", f"/knowledge-units/{unit['id']}", 403, "forbidden")
    await expert.fails(
        "DELETE", f"/knowledge-units/by-expert/{unit['expert_id']}", 403, "forbidden"
    )
    await expert.fails("POST", "/knowledge-units/index/refit", 403, "forbidden")
    await admin.ok("DELETE", f"/knowledge-units/{unit['id']}", 204)
    await admin.fails("DELETE", f"/knowledge-units/{unit['id']}", 404, "not_found")
    await admin.fails(
        "DELETE", "/knowledge-units/00000000-0000-0000-0000-000000000000", 404, "not_found"
    )


async def test_a_refit_that_fails_is_retried_then_reported_and_can_be_queued_again(
    models, monkeypatch
):
    admin = await admin_api()
    monkeypatch.setattr("app.knowledge.ingest.refresh_sparse", _raise(RuntimeError("bm25 broke")))
    await admin.ok("POST", "/knowledge-units/index/refit", 202)
    while await run_once():
        pass
    [job] = await _refit_jobs()
    assert job.status == JobStatus.FAILED and job.attempts == 3
    assert await admin.ok("GET", "/knowledge-units/index") == {
        "state": "failed",
        "last_error": "RuntimeError",
    }

    monkeypatch.undo()
    await admin.ok("POST", "/knowledge-units/index/refit", 202)
    assert await run_once() is True
    assert (await admin.ok("GET", "/knowledge-units/index"))["state"] == "up_to_date"


def _raise(exc: Exception):
    async def fail(db):
        raise exc

    return fail
