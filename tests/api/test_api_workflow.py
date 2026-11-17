"""Jobs, the proofread check, review, access control and hidden data, end to end over the API."""

import asyncio
from datetime import timedelta

import pytest
from api_helpers import (
    DESIGN_SECRET,
    FULL_PAYLOAD,
    HYPOTHESIS,
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
from app.proofread import service as proofread_service
from app.settings import settings


async def _state(api, assignment_id):
    return (await api.ok("GET", f"/assignments/{assignment_id}"))["state"]


async def _jobs(kind: JobKind | None = None) -> list[Job]:
    async with session_factory()() as db:
        query = select(Job)
        if kind:
            query = query.where(Job.kind == kind)
        return list(await db.scalars(query))


async def _decide(admin, assignment_id, by_question: dict[str, str], comment=None):
    return await admin.ok(
        "POST",
        f"/assignments/{assignment_id}/answer-decisions",
        json={
            "decisions": [
                {"question_id": q, "decision": d, "comment": comment}
                for q, d in by_question.items()
            ]
        },
    )


EVERY_ANSWER = ("Q1", "Q2", "Q3", "Q4", "Q5")


# --- jobs and the proofread check ---------------------------------------------------------


async def test_full_path_with_admin_approval_alone():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    version = await published_version(admin)
    [assignment_id] = await assign(admin, version, expert)
    assert await _state(expert, assignment_id) == "assigned"

    await answer_and_submit(expert, assignment_id)
    assert await _state(expert, assignment_id) == "proofreading"
    assert await run_jobs() == 1
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "proofread_check"
    assert view["allowed_actions"] == ["edit_proofread", "submit_for_review"]

    await expert.ok("POST", f"/assignments/{assignment_id}/submit-for-review")
    assert await _state(admin, assignment_id) == "peer_review"
    assert await run_jobs() == 0, "nothing is cut before the answers are approved"

    review = await admin.ok("GET", f"/assignments/{assignment_id}/answers")
    # Reviewers read the answers as the author left them, one per question.
    answers = FULL_PAYLOAD["answers"]
    assert {a["question_id"]: a["text"] for a in review["answers"]} == answers

    await decide_all(admin, assignment_id)
    assert await _state(admin, assignment_id) == "processing"
    assert await run_jobs() == 2, "cut into units, then ingested"
    assert await _state(admin, assignment_id) == "ingested"
    listed = await admin.ok("GET", "/knowledge-units", params={"status": "ingested"})
    by_kind = {u["kind"]: u for u in listed}
    assert by_kind["fragment"]["direction"] == "toward" and by_kind["case"]["direction"] is None
    assert len(listed) == 2
    # Units are cut by citation, and every sentence the expert wrote stays verbatim in one of them.
    assert answers["Q1"] in by_kind["fragment"]["text"]
    assert all(answers[q] in by_kind["case"]["text"] for q in ("Q2", "Q3", "Q5"))
    assert listed[0]["expert_pseudonym"] == expert.pseudonym


async def test_the_proofread_check_waits_for_the_author():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    assert await run_jobs() == 0, "nothing runs while the author checks"
    assert await _state(admin, assignment_id) == "proofread_check"
    await admin.fails("POST", f"/assignments/{assignment_id}/submit-for-review", 403, "forbidden")
    await expert.ok("POST", f"/assignments/{assignment_id}/submit-for-review")
    await expert.fails(
        "POST", f"/assignments/{assignment_id}/submit-for-review", 409, "illegal_transition"
    )


async def test_failed_job_retries_then_fails_and_admin_retry_recovers(monkeypatch, caplog):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)

    calls = {"n": 0}
    message = "the-answer-text must not be stored"

    async def broken(db, assignment, prepared):
        calls["n"] += 1
        raise RuntimeError(message)

    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROOFREAD, broken)
    assert await run_jobs() == MAX_ATTEMPTS
    assert calls["n"] == MAX_ATTEMPTS
    assert await _state(admin, assignment_id) == "processing_failed"
    [job] = await _jobs()
    assert job.status == JobStatus.FAILED
    assert job.last_error == "RuntimeError", "only the class: messages may quote expert text"
    assert "RuntimeError" in caplog.text
    assert "the-answer-text" not in caplog.text

    await expert.fails("POST", f"/assignments/{assignment_id}/retry", 403, "forbidden")
    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROOFREAD, proofread_service.record)
    view = await admin.ok("POST", f"/assignments/{assignment_id}/retry")
    assert view["state"] == "proofreading"
    assert await run_jobs() == 1
    assert await _state(admin, assignment_id) == "proofread_check"


async def test_retry_runs_the_job_that_failed(monkeypatch):
    """processing_failed is shared by two jobs: a failed cut must not proofread again."""
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(admin, expert)
    await decide_all(admin, assignment_id)

    async def broken(db, assignment, prepared):
        raise RuntimeError

    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROCESS, broken)
    await run_jobs()
    assert await _state(admin, assignment_id) == "processing_failed"
    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROCESS, handlers.process)
    view = await admin.ok("POST", f"/assignments/{assignment_id}/retry")
    assert view["state"] == "processing"
    await run_jobs()
    assert await _state(admin, assignment_id) == "ingested"


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

    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROOFREAD, slow)
    results = await asyncio.gather(*(run_once() for _ in range(4)))
    assert calls["n"] == 1
    assert sum(results) >= 1
    assert await _state(admin, assignment_id) == "proofread_check"


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
    assert await _state(admin, assignment_id) == "proofread_check"
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
    assert await run_jobs() == 2, "cut, then refused at once: retrying can't help"
    assert await _state(admin, assignment_id) == "ingestion_failed"
    units = await admin.ok("GET", "/knowledge-units")
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
        return await _state(admin, assignment_id) == "proofread_check"

    await _until(job_finished)
    await _stop(task)


async def _stop(task: asyncio.Task) -> None:
    """Cancel a worker loop and wait until it has let go of its database session. Left running,
    the loop can be caught in the middle of a query when the test ends: its transaction then stays
    open and blocks the TRUNCATE that starts the next test."""
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


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
    await _stop(task)

    assert 1 <= calls <= 10, "the loop must not spin at full speed while failing"
    assert "RuntimeError" in caplog.text
    assert secret not in caplog.text


# --- admin review -----------------------------------------------------------------------------


async def test_partial_approval_ingests_only_the_approved_answers():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(admin, expert)
    decisions = {q: "approve" if q == "Q1" else "reject" for q in EVERY_ANSWER}
    await _decide(admin, assignment_id, decisions, "too generic")
    await run_jobs()
    assert await _state(admin, assignment_id) == "ingested"
    units = await admin.ok("GET", "/knowledge-units")
    assert [(u["kind"], u["status"]) for u in units] == [("fragment", "ingested")]
    review = await admin.ok("GET", f"/assignments/{assignment_id}/answers")
    decided = {a["question_id"]: a["decision"] for a in review["answers"]}
    assert decided["Q2"]["decision"] == "reject" and decided["Q2"]["comment"] == "too generic"


async def test_rejecting_every_answer_ends_the_assignment():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(admin, expert)
    view = await decide_all(admin, assignment_id, "reject")
    assert view["state"] == "rejected"
    assert view["allowed_actions"] == []
    assert await _jobs(JobKind.PROCESS) == []


@pytest.mark.parametrize("variant", ["missing", "duplicate", "foreign"])
async def test_decisions_must_cover_every_answer_exactly_once(variant):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(admin, expert)
    decisions = [{"question_id": q, "decision": "approve"} for q in EVERY_ANSWER]
    if variant == "missing":
        decisions.pop()
    elif variant == "duplicate":
        decisions.append(decisions[0])
    else:
        decisions[0]["question_id"] = "Q6"
    await admin.fails(
        "POST",
        f"/assignments/{assignment_id}/answer-decisions",
        422,
        "decisions_incomplete",
        json={"decisions": decisions},
    )
    assert await _state(admin, assignment_id) == "peer_review"


async def test_an_admin_decision_cannot_be_repeated():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(admin, expert)
    await decide_all(admin, assignment_id)
    await admin.fails(
        "POST",
        f"/assignments/{assignment_id}/answer-decisions",
        409,
        "illegal_transition",
        json={"decisions": [{"question_id": q, "decision": "reject"} for q in EVERY_ANSWER]},
    )


async def test_two_admins_deciding_at_once_only_one_wins():
    first, second = await admin_api(), await admin_api("second@example.com")
    expert = await expert_api("e@example.com")
    [assignment_id], _ = await reach_review(first, expert)
    body = {"decisions": [{"question_id": q, "decision": "approve"} for q in EVERY_ANSWER]}
    url = f"/assignments/{assignment_id}/answer-decisions"
    responses = await asyncio.gather(
        first.request("POST", url, json=body), second.request("POST", url, json=body)
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(await _jobs(JobKind.PROCESS)) == 1


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

ASSIGNMENT_READS = ["", "/answers", "/events", "/submission", "/proofread"]
ASSIGNMENT_WRITES = [
    ("POST", "/start"),
    ("POST", "/cancel"),
    ("POST", "/submit"),
    ("POST", "/submit-for-review"),
    ("POST", "/answer-decisions"),
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


async def test_author_cannot_decide_their_own_answers():
    admin, author = await admin_api(), await expert_api("a@example.com")
    [assignment_id], _ = await reach_review(admin, author)
    review = await author.ok("GET", f"/assignments/{assignment_id}/answers")
    assert all(a["decision"] is None for a in review["answers"])
    await author.fails(
        "POST",
        f"/assignments/{assignment_id}/answer-decisions",
        403,
        "forbidden",
        json={"decisions": [{"question_id": q, "decision": "approve"} for q in EVERY_ANSWER]},
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
    await peer.fails(
        "PUT",
        f"/assignments/{assignment_id}/proofread",
        403,
        "forbidden",
        json={"version": 1, "answers": {}},
    )
    await peer.fails(
        "POST",
        f"/assignments/{assignment_id}/answer-decisions",
        403,
        "forbidden",
        json={"decisions": [{"question_id": q, "decision": "approve"} for q in EVERY_ANSWER]},
    )


async def test_peers_see_neither_the_author_nor_the_raw_answers_nor_the_design():
    admin, author = await admin_api(), await expert_api("author@example.com")
    peer, other = await expert_api("p@example.com"), await expert_api("o@example.com")
    [assignment_id, *_], _ = await reach_review(admin, author, peer, other)
    for reader in (peer, other):
        await reader.ok("POST", f"/assignments/{assignment_id}/review/open", 204)
    url = f"/assignments/{assignment_id}/answers/Q1/comments"
    await author.ok("POST", url, 201, json={"body": "The author speaks."})
    await other.ok("POST", url, 201, json={"body": "A colleague speaks.", "stance": "support"})
    await other.ok(
        "PUT",
        f"/assignments/{assignment_id}/answers/Q1/vote",
        json={"vote": "approve", "review_round": 1},
    )

    await peer.fails("GET", f"/assignments/{assignment_id}/submission", 404, "not_found")
    await peer.fails("GET", f"/assignments/{assignment_id}/events", 404, "not_found")
    await peer.fails("GET", f"/assignments/{assignment_id}/findings", 404, "not_found")
    await peer.fails("GET", f"/assignments/{assignment_id}/proofread", 404, "not_found")
    responses = [
        await peer.ok("GET", f"/assignments/{assignment_id}"),
        await peer.ok("GET", f"/assignments/{assignment_id}/answers"),
        await peer.ok("GET", "/reviews"),
    ]
    assert responses[0]["audience"] == "peer"
    assert responses[0]["allowed_actions"] == ["comment", "vote"]
    seen = str(responses)
    assert "A colleague speaks." in seen and "The author speaks." in seen
    assert other.pseudonym is not None
    assert other.pseudonym in seen, "reviewers talk to each other by pseudonym"
    for hidden in (
        author.pseudonym,
        author.user_id,
        "author@example.com",
        "o@example.com",
        other.user_id,
        HYPOTHESIS,
        DESIGN_SECRET,
        "planted_cues",
        "rating",
    ):
        assert hidden is not None
        assert hidden not in seen, hidden


async def test_author_timeline_hides_the_discussion_and_no_event_holds_text():
    admin, author = await admin_api(), await expert_api("author@example.com")
    peer = await expert_api("p@example.com")
    [assignment_id, _], _ = await reach_review(admin, author, peer)
    await peer.ok("POST", f"/assignments/{assignment_id}/review/open", 204)
    secret = "a-comment-nobody-should-find-in-the-audit-trail"
    await peer.ok(
        "POST",
        f"/assignments/{assignment_id}/answers/Q2/comments",
        201,
        json={"body": secret, "stance": "challenge"},
    )
    await peer.ok(
        "PUT",
        f"/assignments/{assignment_id}/answers/Q2/vote",
        json={"vote": "disapprove", "review_round": 1},
    )
    await decide_all(admin, assignment_id)
    await run_jobs()

    author_events = await author.ok("GET", f"/assignments/{assignment_id}/events")
    assert [e["action"] for e in author_events] == [
        "assigned",
        "start",
        "submit",
        "proofread_succeeded",
        "submit_for_review",
        "approve_answers",
        "processing_succeeded",
        "ingestion_succeeded",
    ]
    actors = {e["action"]: e["actor"] for e in author_events}
    assert actors["start"] == "you"
    assert actors["submit_for_review"] == "you"
    assert actors["assigned"] == "admin"
    assert actors["approve_answers"] == "admin"
    assert actors["proofread_succeeded"] == "system"
    text = str(author_events)
    assert peer.user_id is not None and peer.pseudonym is not None
    assert peer.user_id not in text
    assert peer.pseudonym not in text

    admin_events = await admin.ok("GET", f"/assignments/{assignment_id}/events")
    by_action = {e["action"]: e for e in admin_events}
    assert by_action["vote_cast"]["actor_id"] == peer.user_id
    assert by_action["vote_cast"]["meta"]["vote"] == "disapprove"
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
        "save_draft",
        "submit",
    ]
    assert (await expert.ok("GET", "/assignments"))[0]["job_running"] is False
    filtered = await admin.ok("GET", "/assignments", params={"state": "ingested"})
    assert filtered == []


async def test_list_says_when_a_job_is_running():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    [row] = await expert.ok("GET", "/assignments")
    assert (row["state"], row["job_running"]) == ("proofreading", True)
    await run_jobs()
    [row] = await expert.ok("GET", "/assignments")
    assert (row["state"], row["job_running"]) == ("proofread_check", False)


async def test_the_admin_sees_the_patient_text_and_can_cancel_a_case_in_review():
    admin, expert = await admin_api(), await expert_api("late@example.com")
    (assignment_id,), _ = await reach_review(admin, expert)
    view = await admin.ok("GET", f"/assignments/{assignment_id}")
    assert view["vignette"]["text"] and view["vignette"]["patient_summary"]
    row = (await admin.ok("GET", "/assignments"))[0]
    assert row["opening"] and row["expert_id"] == expert.user_id
    await admin.ok("POST", f"/assignments/{assignment_id}/cancel")
    assert await _state(admin, assignment_id) == "cancelled"


async def test_a_pseudonym_card_shows_the_admin_more_than_anyone_else():
    admin, expert = await admin_api(), await expert_api("who@example.com")
    other = await expert_api("other@example.com")
    version = await published_version(admin)
    await assign(admin, version, expert)
    full = await admin.ok("GET", f"/users/by-pseudonym/{expert.pseudonym}")
    assert full["display_name"] and full["cases"]["open"] == 1
    plain = await other.ok("GET", f"/users/by-pseudonym/{expert.pseudonym}")
    assert plain == {"audience": "peer", "pseudonym": expert.pseudonym, "role": "expert"}
    await other.fails("GET", "/users/by-pseudonym/NOPE", 404, "not_found")
