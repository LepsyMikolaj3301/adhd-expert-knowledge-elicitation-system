"""Open review: every colleague who may read a submission sees its answers, discusses each one and
votes on it; only the admin closes the review."""

from api_helpers import (
    admin_api,
    answer_and_submit,
    assign,
    decide_all,
    expert_api,
    published_version,
    reach_review,
    run_jobs,
    to_review,
    two_experts,
)
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.db import session_factory


def comments_url(assignment_id, question_id):
    return f"/assignments/{assignment_id}/answers/{question_id}/comments"


def vote_url(assignment_id, question_id="Q1"):
    return f"/assignments/{assignment_id}/answers/{question_id}/vote"


async def open_review(api, assignment_id):
    await api.ok("POST", f"/assignments/{assignment_id}/review/open", 204)


async def answers_of(api, assignment_id):
    return (await api.ok("GET", f"/assignments/{assignment_id}/answers"))["answers"]


def by_question(answers):
    return {answer["question_id"]: answer for answer in answers}


async def vote(api, assignment_id, value, question_id="Q1", review_round=1):
    view = await api.ok(
        "PUT",
        vote_url(assignment_id, question_id),
        json={"vote": value, "review_round": review_round},
    )
    return by_question(view["answers"])[question_id]


async def three_in_review():
    """An author and two colleagues, all finished: everyone is in review, and e2 and e3 can read
    e1's answers."""
    admin = await admin_api()
    e1, e2, e3 = [await expert_api(f"e{i}@example.com") for i in (1, 2, 3)]
    [first, *_], _ = await reach_review(admin, e1, e2, e3)
    return admin, e1, e2, e3, first


# --- who may read ---------------------------------------------------------------------------


async def test_the_first_expert_on_a_vignette_is_reviewed_by_whoever_finishes_later():
    admin = await admin_api()
    e1, e2 = await expert_api("e1@example.com"), await expert_api("e2@example.com")
    [first, second] = await assign(admin, await published_version(admin), e1, e2)
    await answer_and_submit(e1, first)
    await to_review(e1, first)
    assert await e2.ok("GET", "/reviews") == [], "e2 has the vignette to answer first"

    await answer_and_submit(e2, second)
    assert await e2.ok("GET", "/reviews") == [], "e2 can still edit after proofreading"
    await to_review(e2, second)
    assert {r["assignment_id"] for r in await e2.ok("GET", "/reviews")} == {first, second}


async def test_an_expert_outside_the_vignette_sees_every_review_of_it():
    admin, e1, e2, e3, first = await three_in_review()
    outsider = await expert_api("outsider@example.com")
    [item] = [r for r in await outsider.ok("GET", "/reviews") if r["assignment_id"] == first]
    assert (item["relation"], item["opened"], item["state"]) == ("reviewer", False, "peer_review")
    assert item["author_pseudonym"] is None, "only the admin knows whose it is"
    [admin_item] = [r for r in await admin.ok("GET", "/reviews") if r["assignment_id"] == first]
    assert admin_item["relation"] == "admin" and admin_item["author_pseudonym"] == e1.pseudonym


async def test_reading_needs_the_reviewer_to_open_the_review_first():
    admin, e1, e2, e3, first = await three_in_review()
    for method, path, body in [
        ("GET", f"/assignments/{first}", None),
        ("GET", f"/assignments/{first}/answers", None),
        ("POST", comments_url(first, "Q1"), {"body": "hello"}),
        ("PUT", vote_url(first), {"vote": "approve", "review_round": 1}),
    ]:
        await e2.fails(method, path, 409, "review_not_opened", json=body)

    await open_review(e2, first)
    await open_review(e2, first)  # idempotent
    view = await e2.ok("GET", f"/assignments/{first}")
    assert view["audience"] == "peer" and view["vignette"]["text"]
    async with session_factory()() as db:
        events = [e for e in await db.scalars(select(AuditEvent)) if e.action == "review_opened"]
    assert len(events) == 1, "opening twice is one event"


async def test_the_author_and_the_admin_need_not_open_anything():
    admin, e1, e2, e3, first = await three_in_review()
    await open_review(e1, first)
    await open_review(admin, first)
    assert (await e1.ok("GET", f"/assignments/{first}"))["audience"] == "expert"
    async with session_factory()() as db:
        events = [e for e in await db.scalars(select(AuditEvent)) if e.action == "review_opened"]
    assert events == [], "the author and the admin are not readers"


async def test_opening_a_review_rules_the_reader_out_of_the_vignette_afterwards():
    admin = await admin_api()
    e1, e2 = await expert_api("e1@example.com"), await expert_api("e2@example.com")
    reader = await expert_api("reader@example.com")
    ids, version = await reach_review(admin, e1, e2)
    await open_review(reader, ids[0])
    await admin.fails(
        "POST",
        f"/vignette-versions/{version['id']}/assignments",
        409,
        "reviewer_contaminated",
        json={"expert_ids": [reader.user_id]},
    )
    # Merely being allowed to read is not enough to be ruled out.
    await assign(admin, version, await expert_api("unread@example.com"))


async def test_a_review_that_is_not_open_yet_cannot_be_opened():
    admin = await admin_api()
    author, free = await expert_api("author@example.com"), await expert_api("free@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), author)
    await free.fails("POST", f"/assignments/{assignment_id}/review/open", 404, "not_found")
    await answer_and_submit(author, assignment_id)
    await run_jobs()
    await free.fails("POST", f"/assignments/{assignment_id}/review/open", 404, "not_found")


async def test_someone_who_still_has_to_answer_cannot_open_the_review():
    admin = await admin_api()
    e1, e2 = await expert_api("e1@example.com"), await expert_api("e2@example.com")
    [first, second] = await assign(admin, await published_version(admin), e1, e2)
    await answer_and_submit(e1, first)
    await to_review(e1, first)
    await e2.fails("POST", f"/assignments/{first}/review/open", 404, "not_found")
    async with session_factory()() as db:
        assert (
            list(await db.scalars(select(AuditEvent).where(AuditEvent.action == "review_opened")))
            == []
        )


# --- the discussion -------------------------------------------------------------------------


async def test_everyone_in_the_review_talks_under_the_answer():
    admin, e1, e2, e3, first = await three_in_review()
    await open_review(e2, first)
    await open_review(e3, first)
    url = comments_url(first, "Q1")

    challenge = await e2.ok(
        "POST", url, 201, json={"body": "  I'd file this elsewhere.  ", "stance": "challenge"}
    )
    assert challenge["body"] == "I'd file this elsewhere.", "trimmed"
    assert challenge["speaker"] == {"kind": "reviewer", "pseudonym": e2.pseudonym}
    assert challenge["is_mine"] is True and challenge["parent_id"] is None
    assert challenge["question_id"] == "Q1"

    reply = await e1.ok("POST", url, 201, json={"body": "Why?", "parent_id": challenge["id"]})
    assert reply["speaker"] == {"kind": "author", "pseudonym": None}
    await e3.ok("POST", url, 201, json={"body": "Agree.", "stance": "support"})
    await admin.ok("POST", url, 201, json={"body": "Noted.", "parent_id": challenge["id"]})

    for viewer in (e1, e2, e3, admin):
        answers = by_question(await answers_of(viewer, first))
        assert [c["body"] for c in answers["Q1"]["comments"]] == [
            "I'd file this elsewhere.",
            "Why?",
            "Agree.",
            "Noted.",
        ]
        assert answers["Q2"]["comments"] == []
    as_e3 = (await answers_of(e3, first))[0]["comments"]
    assert [c["is_mine"] for c in as_e3] == [False, False, True, False]
    as_admin = (await answers_of(admin, first))[0]["comments"]
    assert as_admin[1]["speaker"] == {"kind": "author", "pseudonym": e1.pseudonym}
    assert as_admin[3]["speaker"]["kind"] == "admin"
    as_author = (await answers_of(e1, first))[0]["comments"]
    assert as_author[0]["speaker"]["pseudonym"] == e2.pseudonym
    assert as_author[3]["speaker"] == {"kind": "admin", "pseudonym": None}

    [item] = [r for r in await e2.ok("GET", "/reviews") if r["assignment_id"] == first]
    assert item["comment_count"] == 4


async def test_only_reviewers_take_a_side():
    admin, e1, e2, e3, first = await three_in_review()
    for api in (e1, admin):
        await api.fails(
            "POST",
            comments_url(first, "Q1"),
            422,
            "stance_not_allowed",
            json={"body": "I support me.", "stance": "support"},
        )
    await open_review(e2, first)
    for stance in ("support", "challenge", "question"):
        await e2.ok("POST", comments_url(first, "Q1"), 201, json={"body": "x", "stance": stance})
    await e2.ok("POST", comments_url(first, "Q1"), 201, json={"body": "no side"})


async def test_replies_are_one_level_deep_and_stay_on_their_answer():
    admin, e1, e2, e3, first = await three_in_review()
    await open_review(e2, first)
    top = await e2.ok("POST", comments_url(first, "Q1"), 201, json={"body": "top"})
    reply = await e1.ok(
        "POST",
        comments_url(first, "Q1"),
        201,
        json={"body": "r", "parent_id": top["id"]},
    )
    await e1.fails(
        "POST",
        comments_url(first, "Q1"),
        422,
        "invalid_parent",
        json={"body": "reply to a reply", "parent_id": reply["id"]},
    )
    await e1.fails(
        "POST",
        comments_url(first, "Q2"),
        422,
        "invalid_parent",
        json={"body": "wrong answer", "parent_id": top["id"]},
    )
    await e1.fails(
        "POST",
        comments_url(first, "Q1"),
        422,
        "invalid_parent",
        json={"body": "nowhere", "parent_id": "00000000-0000-0000-0000-000000000000"},
    )


async def test_comment_input_is_checked():
    admin, e1, e2, e3, first = await three_in_review()
    url = comments_url(first, "Q1")
    for body in (
        {"body": ""},
        {"body": "   "},
        {"body": "x" * 5001},
        {"body": "x", "stance": "meh"},
    ):
        response = await e1.request("POST", url, json=body)
        assert response.status_code == 422, body
    assert (await e1.request("POST", url, json={"body": "x" * 5000})).status_code == 201
    assert (
        await e1.request("POST", comments_url(first, "Q9"), json={"body": "x"})
    ).status_code == 422
    await e1.fails("POST", comments_url(first, "Q6"), 404, "not_found", json={"body": "x"})


# --- the vote -------------------------------------------------------------------------------


async def test_a_vote_is_per_answer_advisory_changeable_and_never_closes_the_review():
    admin, e1, e2, e3, first = await three_in_review()
    for reader in (e2, e3):
        await open_review(reader, first)

    q1 = await vote(e2, first, "approve")
    assert (q1["approvals"], q1["disapprovals"], q1["my_vote"]) == (1, 0, "approve")
    q1 = await vote(e3, first, "approve")
    assert q1["approvals"] == 2
    q1 = await vote(e2, first, "disapprove")
    assert (q1["approvals"], q1["disapprovals"], q1["my_vote"]) == (1, 1, "disapprove")
    assert sorted(v["vote"] for v in q1["votes"]) == ["approve", "disapprove"]
    assert {v["speaker"]["pseudonym"] for v in q1["votes"]} == {e2.pseudonym, e3.pseudonym}
    q2 = await vote(e2, first, "approve", "Q2")
    assert (q2["approvals"], q2["disapprovals"]) == (1, 0)
    answers = by_question(await answers_of(e3, first))
    assert answers["Q1"]["my_vote"] == "approve" and answers["Q2"]["my_vote"] is None

    assert (await admin.ok("GET", f"/assignments/{first}"))["state"] == "peer_review"
    [item] = [r for r in await e2.ok("GET", "/reviews") if r["assignment_id"] == first]
    assert (item["approvals"], item["disapprovals"], item["my_votes"]) == (2, 1, 2)
    assert item["answer_count"] == 5


async def test_the_author_and_the_admin_do_not_vote():
    admin, e1, e2, e3, first = await three_in_review()
    for api in (e1, admin):
        await api.fails(
            "PUT", vote_url(first), 403, "forbidden", json={"vote": "approve", "review_round": 1}
        )
    assert (await answers_of(e1, first))[0]["votes"] == []
    assert "vote" not in (await e1.ok("GET", f"/assignments/{first}"))["allowed_actions"]
    assert "comment" in (await e1.ok("GET", f"/assignments/{first}"))["allowed_actions"]
    assert "vote" not in (await admin.ok("GET", f"/assignments/{first}"))["allowed_actions"]


async def test_a_vote_is_for_the_round_that_was_read():
    admin, e1, e2, e3, first = await three_in_review()
    await open_review(e2, first)
    body = await e2.fails(
        "PUT",
        vote_url(first),
        409,
        "stale_round",
        json={"vote": "approve", "review_round": 2},
    )
    assert body["details"] == {"current_round": 1}
    for invalid in (
        {"vote": "maybe", "review_round": 1},
        {"vote": "approve"},
        {"vote": "approve", "review_round": 0},
    ):
        response = await e2.request("PUT", vote_url(first), json=invalid)
        assert response.status_code == 422, invalid
    await e2.fails(
        "PUT", vote_url(first, "Q6"), 404, "not_found", json={"vote": "approve", "review_round": 1}
    )


async def test_nothing_can_be_added_once_the_admin_has_decided():
    admin, e1, e2, e3, first = await three_in_review()
    await open_review(e2, first)
    await vote(e2, first, "approve")
    await decide_all(admin, first)

    closed = "review_closed"
    await e2.fails(
        "PUT", vote_url(first), 409, closed, json={"vote": "disapprove", "review_round": 1}
    )
    for api in (e1, e2, admin):
        await api.fails("POST", comments_url(first, "Q1"), 409, closed, json={"body": "late"})
    # What was said stays readable, to the people who may read it.
    answers = by_question(await answers_of(e2, first))
    assert answers["Q1"]["approvals"] == 1
    assert answers["Q1"]["decision"]["decision"] == "approve"
    assert [r["state"] for r in await e2.ok("GET", "/reviews", params={"status": "closed"})] == [
        "processing"
    ]
    view = await e2.ok("GET", f"/assignments/{first}")
    assert "comment" not in view["allowed_actions"] and "vote" not in view["allowed_actions"]


async def test_an_expert_who_never_opened_a_closed_review_still_must_open_it_to_read():
    admin, e1, e2, e3, first = await three_in_review()
    await decide_all(admin, first)
    await run_jobs()
    assert [r["state"] for r in await e3.ok("GET", "/reviews", params={"status": "closed"})] == [
        "ingested"
    ]
    await e3.fails("GET", f"/assignments/{first}/answers", 409, "review_not_opened")
    await open_review(e3, first)
    assert len(await answers_of(e3, first)) == 5


# --- the admin ------------------------------------------------------------------------------


async def test_the_admin_decides_each_answer_with_the_discussion_in_front_of_them():
    admin, e1, e2, e3, first = await three_in_review()
    await open_review(e2, first)
    await e2.ok(
        "POST", comments_url(first, "Q2"), 201, json={"body": "too vague", "stance": "challenge"}
    )
    await vote(e2, first, "disapprove", "Q2")
    answers = await answers_of(admin, first)
    decisions = [
        {
            "question_id": a["question_id"],
            "decision": "reject" if a["question_id"] == "Q2" else "approve",
            "comment": "ok",
        }
        for a in answers
    ]
    view = await admin.ok(
        "POST", f"/assignments/{first}/answer-decisions", json={"decisions": decisions}
    )
    assert view["state"] == "processing"
    after = by_question(await answers_of(admin, first))
    assert after["Q2"]["decision"]["decision"] == "reject"
    assert after["Q1"]["decision"]["decision"] == "approve"
    assert [c["body"] for c in after["Q2"]["comments"]] == ["too vague"]


async def test_every_answer_is_decided_exactly_once():
    admin, e1, e2, e3, first = await three_in_review()
    url = f"/assignments/{first}/answer-decisions"
    some = [{"question_id": "Q1", "decision": "approve"}]
    await admin.fails("POST", url, 422, "decisions_incomplete", json={"decisions": some})
    twice = [{"question_id": q, "decision": "approve"} for q in ("Q1", "Q1", "Q2", "Q3", "Q4")]
    await admin.fails("POST", url, 422, "decisions_incomplete", json={"decisions": twice})
    vague = [
        {"question_id": q, "decision": "request_changes" if q == "Q1" else "approve"}
        for q in ("Q1", "Q2", "Q3", "Q4", "Q5")
    ]
    await admin.fails("POST", url, 422, "comment_required", json={"decisions": vague})
    assert (await admin.ok("GET", f"/assignments/{first}"))["state"] == "peer_review"


async def test_home_style_lists_show_the_whole_of_a_review_to_the_admin():
    admin, e1, e2 = (await two_experts())[:3]
    open_ones = await admin.ok("GET", "/reviews", params={"status": "open"})
    assert len(open_ones) == 2 and {r["relation"] for r in open_ones} == {"admin"}
    assert await admin.ok("GET", "/reviews", params={"status": "closed"}) == []
    response = await admin.request("GET", "/reviews", params={"status": "other"})
    assert response.status_code == 422
