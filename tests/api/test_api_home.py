"""What the home page is told: what to do next, which reviews wait, what changed."""

from collections import Counter
from datetime import timedelta

from api_helpers import (
    Api,
    admin_api,
    answer_and_submit,
    assign,
    decide_all,
    expert_api,
    published_version,
    reach_review,
    run_jobs,
    to_units,
)

from app.core.db import utcnow
from app.jobs import handlers
from app.jobs.models import JobKind


async def home(api: Api):
    return await api.ok("GET", "/me/home")


def kinds(feed):
    return Counter(item["kind"] for item in feed["activity"])


async def three_in_review():
    admin = await admin_api()
    e1, e2, e3 = [await expert_api(f"e{i}@example.com") for i in (1, 2, 3)]
    [first, second, third], version = await reach_review(admin, e1, e2, e3)
    return admin, (e1, e2, e3), (first, second, third), version


async def comment(api, assignment_id, unit_id, body, **extra):
    return await api.ok(
        "POST",
        f"/assignments/{assignment_id}/units/{unit_id}/comments",
        201,
        json={"body": body, **extra},
    )


# --- access ---------------------------------------------------------------------------------


async def test_the_home_data_needs_a_login():
    await Api().fails("GET", "/me/home", 401, "not_authenticated")
    await Api().fails("POST", "/me/activity/seen", 401, "not_authenticated")


async def test_a_new_account_has_an_empty_home():
    feed = await home(await expert_api("new@example.com"))
    assert feed == {
        "next_up": [],
        "next_up_total": 0,
        "reviews_waiting": [],
        "recent_reviews": [],
        "activity": [],
        "unread_activity": 0,
    }


# --- what to do next ------------------------------------------------------------------------


async def test_next_up_for_an_expert_follows_their_cases_most_recent_first():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [a] = await assign(admin, await published_version(admin), expert)
    [b] = await assign(admin, await published_version(admin), expert)
    feed = await home(expert)
    assert [(i["assignment_id"], i["action"]) for i in feed["next_up"]] == [
        (b, "start"),
        (a, "start"),
    ]
    assert all(i["expert_pseudonym"] is None for i in feed["next_up"])

    await expert.ok("POST", f"/assignments/{a}/start")
    feed = await home(expert)
    assert [(i["assignment_id"], i["action"]) for i in feed["next_up"]] == [
        (a, "continue"),
        (b, "start"),
    ]
    assert feed["next_up"][0]["state"] == "in_progress"
    assert feed["next_up"][0]["vignette_code"] and feed["next_up"][0]["vignette_version"] == 1


async def test_a_submitted_case_waits_for_the_check_and_then_leaves_the_list():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [a] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, a)
    assert (await home(expert))["next_up"] == [], "being processed: nothing for the expert to do"
    await run_jobs()
    [item] = (await home(expert))["next_up"]
    assert (item["assignment_id"], item["action"]) == (a, "check")
    await expert.ok("POST", f"/assignments/{a}/expert-check/skip")
    assert (await home(expert))["next_up"] == []


async def test_next_up_shows_five_and_counts_all():
    admin, expert = await admin_api(), await expert_api("e@example.com")
    for _ in range(7):
        await assign(admin, await published_version(admin), expert)
    feed = await home(expert)
    assert len(feed["next_up"]) == 5 and feed["next_up_total"] == 7


async def test_next_up_for_the_admin_is_what_needs_a_retry(monkeypatch):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [a] = await assign(admin, await published_version(admin), expert)
    [other] = await assign(admin, await published_version(admin), expert)
    assert (await home(admin))["next_up"] == [], "an assigned case is not the admin's to do"
    await answer_and_submit(expert, a)

    async def broken(db, assignment, prepared):
        raise RuntimeError("boom")

    monkeypatch.setitem(handlers.HANDLERS, JobKind.PROCESS, broken)
    await run_jobs()
    feed = await home(admin)
    [item] = feed["next_up"]
    assert (item["assignment_id"], item["action"], item["state"]) == (
        a,
        "retry",
        "processing_failed",
    )
    assert item["expert_pseudonym"] == expert.pseudonym
    expert_items = (await home(expert))["next_up"]
    assert [i["assignment_id"] for i in expert_items] == [other], "a failed job isn't theirs"
    assert [i["kind"] for i in feed["activity"]] == ["job_failed"]


# --- reviews --------------------------------------------------------------------------------


async def test_reviews_waiting_are_the_open_ones_the_viewer_has_not_voted_on():
    admin, (e1, e2, e3), (first, second, third), _ = await three_in_review()
    waiting = (await home(e2))["reviews_waiting"]
    assert {r["assignment_id"] for r in waiting} == {first, third}, "never one's own submission"
    assert all(r["relation"] == "reviewer" and r["my_vote"] is None for r in waiting)

    await e2.ok("POST", f"/assignments/{first}/review/open", 204)
    await e2.ok("PUT", f"/assignments/{first}/vote", json={"vote": "accept", "review_round": 1})
    feed = await home(e2)
    assert {r["assignment_id"] for r in feed["reviews_waiting"]} == {third}
    recent = {r["assignment_id"]: r for r in feed["recent_reviews"]}
    assert set(recent) == {first, second, third}
    assert (recent[first]["my_vote"], recent[first]["accepts"]) == ("accept", 1)
    assert (recent[second]["relation"], recent[second]["opened"]) == ("author", True)
    assert recent[third]["opened"] is False


async def test_the_admin_sees_every_open_review_waiting():
    admin, (e1, e2, e3), (first, second, third), _ = await three_in_review()
    feed = await home(admin)
    assert {r["assignment_id"] for r in feed["reviews_waiting"]} == {first, second, third}
    assert {r["author_pseudonym"] for r in feed["reviews_waiting"]} == {
        e1.pseudonym,
        e2.pseudonym,
        e3.pseudonym,
    }
    await decide_all(admin, first)
    feed = await home(admin)
    assert {r["assignment_id"] for r in feed["reviews_waiting"]} == {second, third}
    assert first in {r["assignment_id"] for r in feed["recent_reviews"]}, "closed ones stay recent"


async def test_recent_reviews_are_cut_off_and_the_newest_come_first(monkeypatch):
    monkeypatch.setattr("app.home.service.RECENT", 2)
    admin, expert = await admin_api(), await expert_api("e@example.com")
    ids = []
    for _ in range(3):
        [assignment_id], _ = await reach_review(admin, expert)
        ids.append(assignment_id)
    recent = (await home(expert))["recent_reviews"]
    assert [r["assignment_id"] for r in recent] == ids[::-1][:2]


# --- what changed ---------------------------------------------------------------------------


async def test_the_activity_of_a_finished_case_for_its_author_and_the_admin():
    admin, (e1, e2, e3), (first, second, third), _ = await three_in_review()
    # e1 was assigned, had the check ready, and sees the three submissions come into review.
    assert kinds(await home(e1)) == {
        "case_assigned": 1,
        "check_ready": 1,
        "review_opened": 3,
    }
    assert kinds(await home(admin)) == {"review_opened": 3}


async def test_a_comment_on_my_case_a_reply_to_my_comment_and_a_comment_of_the_admin():
    admin, (e1, e2, e3), (first, second, third), _ = await three_in_review()
    await e2.ok("POST", f"/assignments/{first}/review/open", 204)
    unit = (await e2.ok("GET", f"/assignments/{first}/units"))[0]

    top = await comment(e2, first, unit["id"], "Why this passage?", stance="question")
    item = next(i for i in (await home(e1))["activity"] if i["kind"] == "comment_on_mine")
    assert item["assignment_id"] == first and item["unit_id"] == unit["id"]
    assert item["unit_ordinal"] == unit["ordinal"] and item["comment_id"] == top["id"]
    assert item["speaker"] == {"kind": "reviewer", "pseudonym": e2.pseudonym}
    assert item["excerpt"] == "Why this passage?" and item["vignette_code"]
    assert "comment_on_mine" not in kinds(await home(e2)), "not told about one's own comment"
    assert "comment_on_mine" not in kinds(await home(e3))

    reply = await comment(e1, first, unit["id"], "Because of the desk.", parent_id=top["id"])
    mine = [i for i in (await home(e2))["activity"] if i["comment_id"] == reply["id"]]
    assert [i["kind"] for i in mine] == ["reply"]
    assert mine[0]["speaker"] == {"kind": "author", "pseudonym": None}
    assert not [i for i in (await home(e1))["activity"] if i["comment_id"] == reply["id"]]

    note = await comment(admin, first, unit["id"], "Thanks both.", parent_id=top["id"])
    for api in (e1, e2):  # both took part in the thread
        [seen] = [i for i in (await home(api))["activity"] if i["comment_id"] == note["id"]]
        assert seen["kind"] == "reply"
        assert seen["speaker"] == {"kind": "admin", "pseudonym": None}
    assert not [i for i in (await home(e3))["activity"] if i["comment_id"] == note["id"]]
    # A top-level comment by someone else is not news to the admin: it is not their thread.
    assert not [i for i in (await home(admin))["activity"] if i["comment_id"] == top["id"]]


async def test_the_admin_hears_about_replies_to_their_own_comments_with_names():
    admin, (e1, e2, e3), (first, second, third), _ = await three_in_review()
    await e2.ok("POST", f"/assignments/{first}/review/open", 204)
    unit = (await e2.ok("GET", f"/assignments/{first}/units"))[0]
    top = await comment(admin, first, unit["id"], "A question for the author.")
    await comment(e1, first, unit["id"], "An answer.", parent_id=top["id"])
    [item] = [i for i in (await home(admin))["activity"] if i["kind"] == "reply"]
    assert item["speaker"] == {"kind": "author", "pseudonym": e1.pseudonym}
    assert item["excerpt"] == "An answer."


async def test_a_long_comment_is_cut_for_the_feed():
    admin, (e1, e2, e3), (first, *_), _ = await three_in_review()
    await e2.ok("POST", f"/assignments/{first}/review/open", 204)
    unit = (await e2.ok("GET", f"/assignments/{first}/units"))[0]
    await comment(e2, first, unit["id"], "word " * 100)
    item = next(i for i in (await home(e1))["activity"] if i["kind"] == "comment_on_mine")
    assert len(item["excerpt"]) == 140 and item["excerpt"].endswith("…")


async def test_the_admins_decision_reaches_the_author_and_those_who_read():
    admin, (e1, e2, e3), (first, second, third), _ = await three_in_review()
    await e2.ok("POST", f"/assignments/{first}/review/open", 204)
    await decide_all(admin, first)
    closed = lambda feed: [i for i in feed["activity"] if i["kind"] == "review_closed"]  # noqa: E731
    [for_author] = closed(await home(e1))
    assert (for_author["assignment_id"], for_author["outcome"]) == (first, "accepted")
    [for_reader] = closed(await home(e2))
    assert for_reader["assignment_id"] == first
    assert closed(await home(e3)) == [], "e3 never opened it"
    assert closed(await home(admin)) == [], "the admin's own decision is not news"


async def test_each_outcome_is_told_apart():
    admin, (e1, e2, e3), (first, second, third), _ = await three_in_review()
    await decide_all(admin, first, "reject")
    second_units = await admin.ok("GET", f"/assignments/{second}/units")
    await admin.ok(
        "POST",
        f"/assignments/{second}/unit-decisions",
        json={
            "decisions": [
                {"unit_id": u["id"], "decision": "request_changes", "comment": "again"}
                for u in second_units
            ]
        },
    )
    outcomes = {
        i["assignment_id"]: i["outcome"]
        for i in (await home(e3))["activity"]
        if i["kind"] == "review_closed"
    }
    assert outcomes == {}, "e3 read neither"
    own = {
        i["assignment_id"]: i["outcome"]
        for api in (e1, e2)
        for i in (await home(api))["activity"]
        if i["kind"] == "review_closed"
    }
    assert own == {first: "rejected", second: "sent_back"}


async def test_someone_still_answering_does_not_hear_about_the_reviews_of_their_vignette():
    admin, (e1, e2, e3), (first, *_), version = await three_in_review()
    mid = await expert_api("mid@example.com")
    [theirs] = await assign(admin, version, mid)
    feed = await home(mid)
    assert kinds(feed) == {"case_assigned": 1}, "no news of colleagues' answers to their case"
    assert [i["assignment_id"] for i in feed["activity"]] == [theirs]
    assert feed["reviews_waiting"] == [] and feed["recent_reviews"] == []

    await answer_and_submit(mid, theirs)
    await to_units(admin, mid, theirs, skip=True)
    assert kinds(await home(mid))["review_opened"] == 4, "now they may read all four"


async def test_a_reviewer_who_joins_later_sees_the_review():
    admin, (e1, e2, e3), (first, *_), _ = await three_in_review()
    late = await expert_api("late@example.com")
    feed = await home(late)
    assert kinds(feed) == {"review_opened": 3}
    assert first in {r["assignment_id"] for r in feed["reviews_waiting"]}


# --- unread ---------------------------------------------------------------------------------


async def test_unread_counts_what_is_newer_than_the_last_look():
    admin, (e1, e2, e3), (first, *_), _ = await three_in_review()
    feed = await home(e1)
    assert feed["unread_activity"] == len(feed["activity"]) == 5
    assert all(i["unread"] for i in feed["activity"])

    newest = max(i["at"] for i in feed["activity"])
    await e1.ok("POST", "/me/activity/seen", 204, json={"until": newest})
    feed = await home(e1)
    assert feed["unread_activity"] == 0 and not any(i["unread"] for i in feed["activity"])

    await e2.ok("POST", f"/assignments/{first}/review/open", 204)
    unit = (await e2.ok("GET", f"/assignments/{first}/units"))[0]
    await comment(e2, first, unit["id"], "New.")
    feed = await home(e1)
    assert feed["unread_activity"] == 1
    assert [i["kind"] for i in feed["activity"] if i["unread"]] == ["comment_on_mine"]

    await e1.ok("POST", "/me/activity/seen", 204)  # no time given: everything up to now
    assert (await home(e1))["unread_activity"] == 0


async def test_marking_seen_never_goes_back_or_ahead():
    admin, (e1, e2, e3), (first, *_), _ = await three_in_review()
    before = utcnow() - timedelta(days=1)
    await e1.ok("POST", "/me/activity/seen", 204, json={"until": before.isoformat()})
    assert (await home(e1))["unread_activity"] == 5, "a day ago is before all of it"

    ahead = (utcnow() + timedelta(days=1)).isoformat()
    await e1.ok("POST", "/me/activity/seen", 204, json={"until": ahead})
    assert (await home(e1))["unread_activity"] == 0
    await e1.ok("POST", "/me/activity/seen", 204, json={"until": before.isoformat()})
    assert (await home(e1))["unread_activity"] == 0, "it does not move backwards"

    for bad in ({"until": "2026-01-01T00:00:00"}, {"until": "yesterday"}, {"other": 1}):
        response = await e1.request("POST", "/me/activity/seen", json=bad)
        assert response.status_code == 422, bad


async def test_each_person_has_their_own_last_look():
    admin, (e1, e2, e3), *_ = await three_in_review()
    await e1.ok("POST", "/me/activity/seen", 204)
    assert (await home(e1))["unread_activity"] == 0
    assert (await home(e2))["unread_activity"] > 0
