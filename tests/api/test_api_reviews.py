"""Open review: every colleague who may read a submission sees it, discusses it and votes on it;
only the admin closes the review."""

from api_helpers import (
    admin_api,
    answer_and_submit,
    assign,
    decide_all,
    expert_api,
    published_version,
    reach_review,
    run_jobs,
    to_units,
    two_experts,
)
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.db import session_factory
from app.knowledge.models import KnowledgeUnit


def comments_url(assignment_id, unit_id):
    return f"/assignments/{assignment_id}/units/{unit_id}/comments"


async def open_review(api, assignment_id):
    await api.ok("POST", f"/assignments/{assignment_id}/review/open", 204)


async def units_of(api, assignment_id):
    return await api.ok("GET", f"/assignments/{assignment_id}/units")


async def vote(api, assignment_id, value, review_round=1):
    return await api.ok(
        "PUT",
        f"/assignments/{assignment_id}/vote",
        json={"vote": value, "review_round": review_round},
    )


async def three_in_review():
    """An author and two colleagues, all finished: everyone is in review, and e2 and e3 can read
    e1's units."""
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
    await to_units(admin, e1, first, skip=True)
    assert await e2.ok("GET", "/reviews") == [], "e2 has the vignette to answer first"

    await answer_and_submit(e2, second)
    assert [r["assignment_id"] for r in await e2.ok("GET", "/reviews")] == [first]


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
    unit = (await units_of(admin, first))[0]
    for method, path, body in [
        ("GET", f"/assignments/{first}", None),
        ("GET", f"/assignments/{first}/units", None),
        ("GET", f"/assignments/{first}/votes", None),
        ("POST", comments_url(first, unit["id"]), {"body": "hello"}),
        ("PUT", f"/assignments/{first}/vote", {"vote": "accept", "review_round": 1}),
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


async def test_someone_who_still_has_to_answer_cannot_open_the_review():
    admin = await admin_api()
    e1, e2 = await expert_api("e1@example.com"), await expert_api("e2@example.com")
    [first, second] = await assign(admin, await published_version(admin), e1, e2)
    await answer_and_submit(e1, first)
    await to_units(admin, e1, first, skip=True)
    await e2.fails("POST", f"/assignments/{first}/review/open", 404, "not_found")
    async with session_factory()() as db:
        assert (
            list(await db.scalars(select(AuditEvent).where(AuditEvent.action == "review_opened")))
            == []
        )


# --- the discussion -------------------------------------------------------------------------


async def test_everyone_in_the_review_talks_under_the_unit():
    admin, e1, e2, e3, first = await three_in_review()
    await open_review(e2, first)
    await open_review(e3, first)
    unit = (await units_of(e1, first))[0]
    url = comments_url(first, unit["id"])

    challenge = await e2.ok(
        "POST", url, 201, json={"body": "  I'd file this elsewhere.  ", "stance": "challenge"}
    )
    assert challenge["body"] == "I'd file this elsewhere.", "trimmed"
    assert challenge["speaker"] == {"kind": "reviewer", "pseudonym": e2.pseudonym}
    assert challenge["is_mine"] is True and challenge["parent_id"] is None

    reply = await e1.ok("POST", url, 201, json={"body": "Why?", "parent_id": challenge["id"]})
    assert reply["speaker"] == {"kind": "author", "pseudonym": None}
    await e3.ok("POST", url, 201, json={"body": "Agree.", "stance": "support"})
    await admin.ok("POST", url, 201, json={"body": "Noted.", "parent_id": challenge["id"]})

    for viewer, fields in (
        (e1, "author"),
        (e2, "peer"),
        (e3, "peer"),
        (admin, "admin"),
    ):
        unit_view = (await units_of(viewer, first))[0]
        assert unit_view["audience"] == fields
        assert [c["body"] for c in unit_view["comments"]] == [
            "I'd file this elsewhere.",
            "Why?",
            "Agree.",
            "Noted.",
        ]
    as_e3 = (await units_of(e3, first))[0]["comments"]
    assert [c["is_mine"] for c in as_e3] == [False, False, True, False]
    as_admin = (await units_of(admin, first))[0]["comments"]
    assert as_admin[1]["speaker"] == {"kind": "author", "pseudonym": e1.pseudonym}
    assert as_admin[3]["speaker"]["kind"] == "admin"
    as_author = (await units_of(e1, first))[0]["comments"]
    assert as_author[0]["speaker"]["pseudonym"] == e2.pseudonym
    assert as_author[3]["speaker"] == {"kind": "admin", "pseudonym": None}

    [item] = [r for r in await e2.ok("GET", "/reviews") if r["assignment_id"] == first]
    assert item["comment_count"] == 4


async def test_only_reviewers_take_a_side():
    admin, e1, e2, e3, first = await three_in_review()
    unit = (await units_of(e1, first))[0]
    for api in (e1, admin):
        await api.fails(
            "POST",
            comments_url(first, unit["id"]),
            422,
            "stance_not_allowed",
            json={"body": "I support me.", "stance": "support"},
        )
    await open_review(e2, first)
    for stance in ("support", "challenge", "question"):
        await e2.ok(
            "POST", comments_url(first, unit["id"]), 201, json={"body": "x", "stance": stance}
        )
    await e2.ok("POST", comments_url(first, unit["id"]), 201, json={"body": "no side"})


async def test_replies_are_one_level_deep_and_stay_on_their_unit():
    admin, e1, e2, e3, first = await three_in_review()
    await open_review(e2, first)
    first_unit, second_unit = (await units_of(e2, first))[:2]
    top = await e2.ok("POST", comments_url(first, first_unit["id"]), 201, json={"body": "top"})
    reply = await e1.ok(
        "POST",
        comments_url(first, first_unit["id"]),
        201,
        json={"body": "r", "parent_id": top["id"]},
    )
    await e1.fails(
        "POST",
        comments_url(first, first_unit["id"]),
        422,
        "invalid_parent",
        json={"body": "reply to a reply", "parent_id": reply["id"]},
    )
    await e1.fails(
        "POST",
        comments_url(first, second_unit["id"]),
        422,
        "invalid_parent",
        json={"body": "wrong unit", "parent_id": top["id"]},
    )
    await e1.fails(
        "POST",
        comments_url(first, first_unit["id"]),
        422,
        "invalid_parent",
        json={"body": "nowhere", "parent_id": "00000000-0000-0000-0000-000000000000"},
    )


async def test_comment_input_is_checked():
    admin, e1, e2, e3, first = await three_in_review()
    unit = (await units_of(e1, first))[0]
    url = comments_url(first, unit["id"])
    for body in (
        {"body": ""},
        {"body": "   "},
        {"body": "x" * 5001},
        {"body": "x", "stance": "meh"},
    ):
        response = await e1.request("POST", url, json=body)
        assert response.status_code == 422, body
    assert (await e1.request("POST", url, json={"body": "x" * 5000})).status_code == 201
    await e1.fails(
        "POST",
        comments_url(first, "00000000-0000-0000-0000-000000000000"),
        404,
        "not_found",
        json={"body": "x"},
    )


async def test_a_unit_of_another_submission_is_not_found():
    admin, e1, e2, e3, first = await three_in_review()
    async with session_factory()() as db:
        elsewhere = await db.scalar(
            select(KnowledgeUnit.id).where(KnowledgeUnit.assignment_id != first)
        )
    await e1.fails(
        "POST", comments_url(first, str(elsewhere)), 404, "not_found", json={"body": "x"}
    )


# --- the vote -------------------------------------------------------------------------------


async def test_a_vote_is_advisory_changeable_and_never_closes_the_review():
    admin, e1, e2, e3, first = await three_in_review()
    for reader in (e2, e3):
        await open_review(reader, first)

    tally = await vote(e2, first, "accept")
    assert (tally["accepts"], tally["declines"], tally["my_vote"]) == (1, 0, "accept")
    tally = await vote(e3, first, "accept")
    assert tally["accepts"] == 2
    tally = await vote(e2, first, "decline")
    assert (tally["accepts"], tally["declines"], tally["my_vote"]) == (1, 1, "decline")
    assert sorted(v["vote"] for v in tally["votes"]) == ["accept", "decline"]
    assert {v["speaker"]["pseudonym"] for v in tally["votes"]} == {e2.pseudonym, e3.pseudonym}
    assert (await e3.ok("GET", f"/assignments/{first}/votes"))["my_vote"] == "accept"

    assert (await admin.ok("GET", f"/assignments/{first}"))["state"] == "peer_review"
    [item] = [r for r in await e2.ok("GET", "/reviews") if r["assignment_id"] == first]
    assert (item["accepts"], item["declines"], item["my_vote"]) == (1, 1, "decline")


async def test_the_author_and_the_admin_do_not_vote():
    admin, e1, e2, e3, first = await three_in_review()
    for api in (e1, admin):
        await api.fails(
            "PUT",
            f"/assignments/{first}/vote",
            403,
            "forbidden",
            json={"vote": "accept", "review_round": 1},
        )
    assert (await e1.ok("GET", f"/assignments/{first}/votes"))["votes"] == []
    assert "vote" not in (await e1.ok("GET", f"/assignments/{first}"))["allowed_actions"]
    assert "comment" in (await e1.ok("GET", f"/assignments/{first}"))["allowed_actions"]
    assert "vote" not in (await admin.ok("GET", f"/assignments/{first}"))["allowed_actions"]


async def test_a_vote_is_for_the_round_that_was_read():
    admin, e1, e2, e3, first = await three_in_review()
    await open_review(e2, first)
    body = await e2.fails(
        "PUT",
        f"/assignments/{first}/vote",
        409,
        "stale_round",
        json={"vote": "accept", "review_round": 2},
    )
    assert body["details"] == {"current_round": 1}
    for invalid in (
        {"vote": "maybe", "review_round": 1},
        {"vote": "accept"},
        {"vote": "accept", "review_round": 0},
    ):
        response = await e2.request("PUT", f"/assignments/{first}/vote", json=invalid)
        assert response.status_code == 422, invalid


async def test_nothing_can_be_added_once_the_admin_has_decided():
    admin, e1, e2, e3, first = await three_in_review()
    await open_review(e2, first)
    unit = (await units_of(e2, first))[0]
    await vote(e2, first, "accept")
    await decide_all(admin, first)

    closed = "review_closed"
    await e2.fails(
        "PUT",
        f"/assignments/{first}/vote",
        409,
        closed,
        json={"vote": "decline", "review_round": 1},
    )
    for api in (e1, e2, admin):
        await api.fails("POST", comments_url(first, unit["id"]), 409, closed, json={"body": "late"})
    # What was said stays readable, to the people who may read it.
    assert (await e2.ok("GET", f"/assignments/{first}/votes"))["accepts"] == 1
    assert [r["state"] for r in await e2.ok("GET", "/reviews", params={"status": "closed"})] == [
        "ingesting"
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
    await e3.fails("GET", f"/assignments/{first}/units", 409, "review_not_opened")
    await open_review(e3, first)
    assert (await units_of(e3, first))[0]["audience"] == "peer"


# --- the admin ------------------------------------------------------------------------------


async def test_the_admin_decides_each_unit_with_the_discussion_in_front_of_them():
    admin, e1, e2, e3, first = await three_in_review()
    await open_review(e2, first)
    units = await units_of(admin, first)
    await e2.ok(
        "POST",
        comments_url(first, units[1]["id"]),
        201,
        json={"body": "too vague", "stance": "challenge"},
    )
    await vote(e2, first, "decline")
    decisions = [
        {"unit_id": u["id"], "decision": "approve" if i == 0 else "reject", "comment": "ok"}
        for i, u in enumerate(units)
    ]
    view = await admin.ok(
        "POST", f"/assignments/{first}/unit-decisions", json={"decisions": decisions}
    )
    assert view["state"] == "ingesting"
    after = await units_of(admin, first)
    assert [u["status"] for u in after] == ["approved", "rejected"]
    assert [c["body"] for c in after[1]["comments"]] == ["too vague"]


async def test_home_style_lists_show_the_whole_of_a_review_to_the_admin():
    admin, e1, e2 = (await two_experts())[:3]
    open_ones = await admin.ok("GET", "/reviews", params={"status": "open"})
    assert len(open_ones) == 2 and {r["relation"] for r in open_ones} == {"admin"}
    assert await admin.ok("GET", "/reviews", params={"status": "closed"}) == []
    response = await admin.request("GET", "/reviews", params={"status": "other"})
    assert response.status_code == 422
