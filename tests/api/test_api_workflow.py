"""Jobs, the expert check, review, access control and hidden data, end to end over the API."""

import asyncio
from datetime import timedelta

import pytest
from api_helpers import (
    DESIGN_SECRET,
    FULL_PAYLOAD,
    HYPOTHESIS,
    Q4_WHY,
    admin_api,
    answer_and_submit,
    assign,
    decide_all,
    expert_api,
    published_version,
    reach_review,
    run_jobs,
)
from conftest import TEST_URL
from sqlalchemy import select, update
from sqlalchemy.pool import NullPool

from app.audit.models import AuditEvent
from app.core.db import configure_engine, session_factory, utcnow
from app.jobs import handlers, worker
from app.jobs.models import Job, JobKind, JobStatus
from app.jobs.queue import MAX_ATTEMPTS
from app.jobs.worker import run_once
from app.settings import settings


async def _state(api, assignment_id):
    return (await api.ok("GET", f"/assignments/{assignment_id}"))["state"]


async def _jobs(kind: JobKind | None = None) -> list[Job]:
    async with session_factory()() as db:
        query = select(Job)
        if kind:
            query = query.where(Job.kind == kind)
        return list(await db.scalars(query))


# --- jobs and the expert check ----------------------------------------------------------------


async def test_full_path_with_admin_approval_alone():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    version = await published_version(admin)
    [assignment_id] = await assign(admin, version, expert)
    assert await _state(expert, assignment_id) == "assigned"

    await answer_and_submit(expert, assignment_id)
    assert await _state(expert, assignment_id) == "processing"
    assert await run_jobs() == 1
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "expert_check"
    assert view["allowed_actions"] == [
        "complete_expert_check",
        "correct_findings",
        "skip_expert_check",
    ]

    await expert.ok("POST", f"/assignments/{assignment_id}/expert-check/complete")
    assert await _state(expert, assignment_id) == "building_units"
    assert await run_jobs() == 1
    assert await _state(admin, assignment_id) == "peer_review"

    units = await admin.ok("GET", f"/assignments/{assignment_id}/units")
    assert [(u["kind"], u["direction"]) for u in units] == [("fragment", "toward"), ("case", None)]
    # Units are cut by citation, and every sentence the expert wrote stays verbatim in one of them.
    answers = FULL_PAYLOAD["answers"]
    assert answers["Q1"] in units[0]["text"]
    assert all(answers[q] in units[1]["text"] for q in ("Q2", "Q3", "Q5"))
    assert all(u["status"] == "pending" for u in units)

    await decide_all(admin, assignment_id)
    assert await _state(admin, assignment_id) == "ingesting"
    assert await run_jobs() == 1
    assert await _state(admin, assignment_id) == "ingested"
    listed = await admin.ok("GET", "/knowledge-units", params={"status": "ingested"})
    assert len(listed) == len(units)
    assert listed[0]["expert_pseudonym"] == expert.pseudonym


async def test_expert_check_waits_and_the_admin_can_skip_it():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    assert await run_jobs() == 0, "nothing runs while the expert check is open"
    assert await _state(admin, assignment_id) == "expert_check"
    await admin.fails(
        "POST", f"/assignments/{assignment_id}/expert-check/complete", 403, "forbidden"
    )
    await admin.ok("POST", f"/assignments/{assignment_id}/expert-check/skip")
    await run_jobs()
    assert await _state(admin, assignment_id) == "peer_review"


async def test_failed_job_retries_then_fails_and_admin_retry_recovers(monkeypatch, caplog):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)

    calls = {"n": 0}
    message = "the-answer-text must not be stored"

    async def broken(db, assignment, prepared):
        calls["n"] += 1
        raise RuntimeError(message)

    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROCESS, broken)
    assert await run_jobs() == MAX_ATTEMPTS
    assert calls["n"] == MAX_ATTEMPTS
    assert await _state(admin, assignment_id) == "processing_failed"
    [job] = await _jobs()
    assert job.status == JobStatus.FAILED
    assert job.last_error == "RuntimeError", "only the class: messages may quote expert text"
    assert "RuntimeError" in caplog.text
    assert "the-answer-text" not in caplog.text

    await expert.fails("POST", f"/assignments/{assignment_id}/retry", 403, "forbidden")
    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROCESS, handlers.process)
    view = await admin.ok("POST", f"/assignments/{assignment_id}/retry")
    assert view["state"] == "processing"
    assert await run_jobs() == 1
    assert await _state(admin, assignment_id) == "expert_check"


async def test_retry_runs_the_job_that_failed(monkeypatch):
    """processing_failed is shared by two jobs: a failed unit build must not reprocess."""
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    await expert.ok("POST", f"/assignments/{assignment_id}/expert-check/skip")

    async def broken(db, assignment, prepared):
        raise RuntimeError

    monkeypatch.setitem(handlers.HANDLERS, JobKind.BUILD_UNITS, broken)
    await run_jobs()
    assert await _state(admin, assignment_id) == "processing_failed"
    monkeypatch.setitem(handlers.HANDLERS, JobKind.BUILD_UNITS, handlers.build_units)
    view = await admin.ok("POST", f"/assignments/{assignment_id}/retry")
    assert view["state"] == "building_units"
    await run_jobs()
    assert await _state(admin, assignment_id) == "peer_review"


async def test_ingestion_failure_and_retry(monkeypatch):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(admin, expert)
    await decide_all(admin, assignment_id)

    async def broken(db, assignment, prepared):
        raise RuntimeError

    monkeypatch.setitem(handlers.HANDLERS, JobKind.INGEST, broken)
    await run_jobs()
    assert await _state(admin, assignment_id) == "ingestion_failed"
    monkeypatch.setitem(handlers.HANDLERS, JobKind.INGEST, handlers.ingest)
    await admin.ok("POST", f"/assignments/{assignment_id}/retry")
    await run_jobs()
    assert await _state(admin, assignment_id) == "ingested"


async def test_two_workers_never_run_the_same_job(monkeypatch):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    calls = {"n": 0}

    async def slow(db, assignment, prepared):
        calls["n"] += 1
        await asyncio.sleep(0.2)

    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROCESS, slow)
    results = await asyncio.gather(*(run_once() for _ in range(4)))
    assert calls["n"] == 1
    assert sum(results) >= 1
    assert await _state(admin, assignment_id) == "expert_check"


async def test_job_of_a_crashed_worker_is_retried_after_its_lease(monkeypatch):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    async with session_factory()() as db:
        await db.execute(
            update(Job).values(
                status=JobStatus.RUNNING, attempts=1, locked_until=utcnow() + timedelta(minutes=1)
            )
        )
        await db.commit()
    assert await run_once() is False, "the lease is still valid"
    async with session_factory()() as db:
        await db.execute(update(Job).values(locked_until=utcnow() - timedelta(seconds=1)))
        await db.commit()
    assert await run_once() is True
    assert await _state(admin, assignment_id) == "expert_check"
    [job] = await _jobs()
    assert job.attempts == 2


async def test_crashing_on_the_last_attempt_fails_the_job():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    async with session_factory()() as db:
        await db.execute(
            update(Job).values(
                status=JobStatus.RUNNING,
                attempts=MAX_ATTEMPTS,
                locked_until=utcnow() - timedelta(seconds=1),
            )
        )
        await db.commit()
    assert await run_once() is True
    assert await _state(admin, assignment_id) == "processing_failed"
    [job] = await _jobs()
    assert job.last_error == "LeaseExpired"


async def test_synthetic_answers_never_enter_production(monkeypatch):
    admin = await admin_api()
    expert = await expert_api("s@example.com", is_synthetic=True)
    [assignment_id], _ = await reach_review(admin, expert)
    await decide_all(admin, assignment_id)

    monkeypatch.setattr(settings, "environment", "production")
    assert await run_jobs() == 1, "refused at once: retrying can't help"
    assert await _state(admin, assignment_id) == "ingestion_failed"
    units = await admin.ok("GET", f"/assignments/{assignment_id}/units")
    assert {u["status"] for u in units} == {"approved"}
    [job] = await _jobs(JobKind.INGEST)
    assert job.last_error == "SyntheticIngestionRefused"

    monkeypatch.setattr(settings, "environment", "development")
    await admin.ok("POST", f"/assignments/{assignment_id}/retry")
    await run_jobs()
    assert await _state(admin, assignment_id) == "ingested"


async def _until(condition, seconds: float = 5.0) -> None:
    async with asyncio.timeout(seconds):
        while not await condition():  # noqa: ASYNC110 (polling the database: no event to wait on)
            await asyncio.sleep(0.01)


async def test_the_worker_survives_a_database_outage_and_resumes(monkeypatch, caplog):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    monkeypatch.setattr(worker, "POLL_SECONDS", 0.01)

    configure_engine("postgresql://rag:rag@127.0.0.1:1/down", poolclass=NullPool)
    task = asyncio.create_task(worker.main())

    async def outage_noticed():
        return task.done() or "ConnectionRefusedError" in caplog.text

    await _until(outage_noticed)
    assert not task.done(), "the worker died with the database"

    configure_engine(TEST_URL, poolclass=NullPool)

    async def job_finished():
        return await _state(admin, assignment_id) == "expert_check"

    await _until(job_finished)
    task.cancel()


async def test_a_failing_worker_loop_waits_between_tries_and_logs_no_message(monkeypatch, caplog):
    secret = "the-answer-text must not be stored"
    calls = 0

    async def failing_next_job(db):
        nonlocal calls
        calls += 1
        raise RuntimeError(secret)

    monkeypatch.setattr(worker, "next_job", failing_next_job)
    monkeypatch.setattr(worker, "POLL_SECONDS", 0.05)
    task = asyncio.create_task(worker.main())
    await asyncio.sleep(0.25)
    assert not task.done(), "the worker died on the error"
    task.cancel()

    assert 1 <= calls <= 10, "the loop must not spin at full speed while failing"
    assert "RuntimeError" in caplog.text
    assert secret not in caplog.text


# --- admin review -----------------------------------------------------------------------------


async def test_partial_approval_ingests_only_the_approved_units():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(admin, expert)
    units = await admin.ok("GET", f"/assignments/{assignment_id}/units")
    decisions = [
        {
            "unit_id": unit["id"],
            "decision": "approve" if index == 0 else "reject",
            "comment": None if index == 0 else "too generic",
        }
        for index, unit in enumerate(units)
    ]
    await admin.ok(
        "POST", f"/assignments/{assignment_id}/unit-decisions", json={"decisions": decisions}
    )
    await run_jobs()
    assert await _state(admin, assignment_id) == "ingested"
    after = await admin.ok("GET", f"/assignments/{assignment_id}/units")
    assert [u["status"] for u in after] == ["ingested", "rejected"]
    assert after[1]["decisions"][0]["comment"] == "too generic"
    assert after[1]["decisions"][0]["stage"] == "admin"


async def test_rejecting_every_unit_ends_the_assignment():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(admin, expert)
    view = await decide_all(admin, assignment_id, "reject")
    assert view["state"] == "rejected"
    assert view["allowed_actions"] == []
    assert await _jobs(JobKind.INGEST) == []


@pytest.mark.parametrize("variant", ["missing", "duplicate", "foreign"])
async def test_decisions_must_cover_every_unit_exactly_once(variant):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(admin, expert)
    units = await admin.ok("GET", f"/assignments/{assignment_id}/units")
    decisions = [{"unit_id": u["id"], "decision": "approve"} for u in units]
    if variant == "missing":
        decisions.pop()
    elif variant == "duplicate":
        decisions.append(decisions[0])
    else:
        decisions[0]["unit_id"] = "00000000-0000-0000-0000-000000000000"
    await admin.fails(
        "POST",
        f"/assignments/{assignment_id}/unit-decisions",
        422,
        "decisions_incomplete",
        json={"decisions": decisions},
    )
    assert await _state(admin, assignment_id) == "peer_review"


async def test_an_admin_decision_cannot_be_repeated():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(admin, expert)
    units = await admin.ok("GET", f"/assignments/{assignment_id}/units")
    await decide_all(admin, assignment_id)
    await admin.fails(
        "POST",
        f"/assignments/{assignment_id}/unit-decisions",
        409,
        "illegal_transition",
        json={"decisions": [{"unit_id": u["id"], "decision": "reject"} for u in units]},
    )


async def test_two_admins_deciding_at_once_only_one_wins():
    first, second = await admin_api(), await admin_api("second@example.com")
    expert = await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(first, expert)
    units = await first.ok("GET", f"/assignments/{assignment_id}/units")
    body = {"decisions": [{"unit_id": u["id"], "decision": "approve"} for u in units]}
    url = f"/assignments/{assignment_id}/unit-decisions"
    responses = await asyncio.gather(
        first.request("POST", url, json=body), second.request("POST", url, json=body)
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(await _jobs(JobKind.INGEST)) == 1


# Reading, discussing and voting on a review is in test_api_reviews.py.


async def test_assignment_rules():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    version = await published_version(admin)
    url = f"/vignette-versions/{version['id']}/assignments"
    await admin.fails("POST", url, 422, "invalid_assignee", json={"expert_ids": [admin.user_id]})
    [assignment_id] = await assign(admin, version, expert)
    await admin.fails("POST", url, 409, "already_assigned", json={"expert_ids": [expert.user_id]})

    view = await admin.ok("POST", f"/assignments/{assignment_id}/cancel")
    assert view["state"] == "cancelled"
    await assign(admin, version, expert)  # a cancelled assignment doesn't block a new one


async def test_cancel_is_admin_only_and_only_before_submission():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await expert.fails("POST", f"/assignments/{assignment_id}/cancel", 403, "forbidden")
    await answer_and_submit(expert, assignment_id)
    await admin.fails("POST", f"/assignments/{assignment_id}/cancel", 409, "illegal_transition")


# --- access and hidden data -------------------------------------------------------------------

ASSIGNMENT_READS = ["", "/units", "/events", "/submission"]
ASSIGNMENT_WRITES = [
    ("POST", "/start"),
    ("POST", "/cancel"),
    ("POST", "/pass-gate"),
    ("POST", "/submit"),
    ("POST", "/expert-check/complete"),
    ("POST", "/expert-check/skip"),
    ("POST", "/unit-decisions"),
]


async def test_experts_who_may_not_read_get_404_on_everything_about_an_assignment():
    """Before a submission is in review, only its author and the admin can see it. Afterwards a
    colleague who still has the vignette to answer can't either."""
    admin, author = await admin_api(), await expert_api("a@example.com")
    free, midcase = await expert_api("f@example.com"), await expert_api("m@example.com")
    [in_review], version = await reach_review(admin, author)
    await assign(admin, version, midcase)
    [not_yet] = await assign(admin, await published_version(admin), author)

    async def refused(stranger, assignment_id):
        for suffix in ASSIGNMENT_READS:
            await stranger.fails("GET", f"/assignments/{assignment_id}{suffix}", 404, "not_found")
        for method, suffix in ASSIGNMENT_WRITES:
            await stranger.fails(
                method,
                f"/assignments/{assignment_id}{suffix}",
                404,
                "not_found",
                json={"decisions": []},
            )
        await stranger.fails(
            "PUT",
            f"/assignments/{assignment_id}/draft",
            404,
            "not_found",
            json={"version": 1, "payload": {}},
        )

    await refused(midcase, in_review)
    await refused(free, not_yet)
    assert await midcase.ok("GET", "/assignments") != [], "their own assignment is theirs"
    assert await midcase.ok("GET", "/reviews") == []
    assert await free.ok("GET", "/reviews", params={"status": "open"}) != []


async def test_author_cannot_decide_their_own_units():
    admin, author = await admin_api(), await expert_api("a@example.com")
    [assignment_id], _ = await reach_review(admin, author)
    units = await author.ok("GET", f"/assignments/{assignment_id}/units")
    assert units[0]["audience"] == "author"
    assert "decisions" not in units[0]
    await author.fails(
        "POST",
        f"/assignments/{assignment_id}/unit-decisions",
        403,
        "forbidden",
        json={"decisions": [{"unit_id": u["id"], "decision": "approve"} for u in units]},
    )


async def test_a_reviewer_cannot_use_the_authors_actions_or_decide():
    admin, author = await admin_api(), await expert_api("a@example.com")
    peer = await expert_api("p@example.com")
    [assignment_id, _], _ = await reach_review(admin, author, peer)
    await peer.ok("POST", f"/assignments/{assignment_id}/review/open", 204)
    await peer.fails("POST", f"/assignments/{assignment_id}/start", 409, "illegal_transition")
    await peer.fails(
        "PUT",
        f"/assignments/{assignment_id}/draft",
        403,
        "forbidden",
        json={"version": 1, "payload": {}},
    )
    await peer.fails("POST", f"/assignments/{assignment_id}/pass-gate", 403, "forbidden")
    units = await peer.ok("GET", f"/assignments/{assignment_id}/units")
    await peer.fails(
        "POST",
        f"/assignments/{assignment_id}/unit-decisions",
        403,
        "forbidden",
        json={"decisions": [{"unit_id": u["id"], "decision": "approve"} for u in units]},
    )


async def test_peers_see_neither_the_author_nor_the_raw_answers_nor_the_design():
    admin, author = await admin_api(), await expert_api("author@example.com")
    peer, other = await expert_api("p@example.com"), await expert_api("o@example.com")
    [assignment_id, *_], _ = await reach_review(admin, author, peer, other)
    for reader in (peer, other):
        await reader.ok("POST", f"/assignments/{assignment_id}/review/open", 204)
    units = await author.ok("GET", f"/assignments/{assignment_id}/units")
    url = f"/assignments/{assignment_id}/units/{units[0]['id']}/comments"
    await author.ok("POST", url, 201, json={"body": "The author speaks."})
    await other.ok("POST", url, 201, json={"body": "A colleague speaks.", "stance": "support"})
    await other.ok(
        "PUT", f"/assignments/{assignment_id}/vote", json={"vote": "accept", "review_round": 1}
    )

    await peer.fails("GET", f"/assignments/{assignment_id}/submission", 404, "not_found")
    await peer.fails("GET", f"/assignments/{assignment_id}/events", 404, "not_found")
    await peer.fails("GET", f"/assignments/{assignment_id}/findings", 404, "not_found")
    responses = [
        await peer.ok("GET", f"/assignments/{assignment_id}"),
        await peer.ok("GET", f"/assignments/{assignment_id}/units"),
        await peer.ok("GET", f"/assignments/{assignment_id}/votes"),
        await peer.ok("GET", "/reviews"),
    ]
    assert responses[0]["audience"] == "peer"
    assert responses[1][0]["audience"] == "peer"
    assert responses[0]["allowed_actions"] == ["comment", "vote"]
    seen = str(responses)
    assert "A colleague speaks." in seen and "The author speaks." in seen
    assert other.pseudonym in seen, "reviewers talk to each other by pseudonym"
    for hidden in (
        author.pseudonym,
        author.user_id,
        "author@example.com",
        "o@example.com",
        other.user_id,
        Q4_WHY,
        HYPOTHESIS,
        DESIGN_SECRET,
        "planted_cues",
        "the-whatif-secret",
        "rating",
    ):
        assert hidden not in seen, hidden


async def test_author_timeline_hides_the_discussion_and_no_event_holds_text():
    admin, author = await admin_api(), await expert_api("author@example.com")
    peer = await expert_api("p@example.com")
    [assignment_id, _], _ = await reach_review(admin, author, peer)
    await peer.ok("POST", f"/assignments/{assignment_id}/review/open", 204)
    units = await peer.ok("GET", f"/assignments/{assignment_id}/units")
    secret = "a-comment-nobody-should-find-in-the-audit-trail"
    await peer.ok(
        "POST",
        f"/assignments/{assignment_id}/units/{units[0]['id']}/comments",
        201,
        json={"body": secret, "stance": "challenge"},
    )
    await peer.ok(
        "PUT", f"/assignments/{assignment_id}/vote", json={"vote": "decline", "review_round": 1}
    )
    await decide_all(admin, assignment_id)
    await run_jobs()

    author_events = await author.ok("GET", f"/assignments/{assignment_id}/events")
    assert [e["action"] for e in author_events] == [
        "assigned",
        "start",
        "gate_passed",
        "submit",
        "processing_succeeded",
        "skip_expert_check",
        "units_built",
        "approve_units",
        "ingestion_succeeded",
    ]
    actors = {e["action"]: e["actor"] for e in author_events}
    assert actors["start"] == "you"
    assert actors["assigned"] == "admin"
    assert actors["approve_units"] == "admin"
    assert actors["units_built"] == "system"
    text = str(author_events)
    assert peer.user_id not in text
    assert peer.pseudonym not in text

    admin_events = await admin.ok("GET", f"/assignments/{assignment_id}/events")
    by_action = {e["action"]: e for e in admin_events}
    assert by_action["vote_cast"]["actor_id"] == peer.user_id
    assert by_action["vote_cast"]["meta"]["vote"] == "decline"
    assert by_action["comment_added"]["meta"]["stance"] == "challenge"
    assert "review_opened" in by_action

    async with session_factory()() as db:
        stored = list(await db.scalars(select(AuditEvent)))
    everything = " ".join(str((e.action, e.from_state, e.to_state, e.meta)) for e in stored)
    for answer in FULL_PAYLOAD["answers"].values():
        assert answer not in everything
    assert HYPOTHESIS not in everything
    assert secret not in everything


async def test_allowed_actions_in_the_lists():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    assert (await expert.ok("GET", "/assignments"))[0]["allowed_actions"] == ["start"]
    assert (await admin.ok("GET", "/assignments"))[0]["allowed_actions"] == ["cancel"]
    await expert.ok("POST", f"/assignments/{assignment_id}/start")
    assert (await expert.ok("GET", "/assignments"))[0]["allowed_actions"] == [
        "pass_gate",
        "save_draft",
    ]
    assert (await expert.ok("GET", "/assignments"))[0]["job_running"] is False
    filtered = await admin.ok("GET", "/assignments", params={"state": "ingested"})
    assert filtered == []


async def test_list_says_when_a_job_is_running():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    assert (await expert.ok("GET", "/assignments"))[0]["job_running"] is True
    await run_jobs()
    assert (await expert.ok("GET", "/assignments"))[0]["job_running"] is False
