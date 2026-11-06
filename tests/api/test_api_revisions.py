"""The admin can ask for changes after reading the discussion: the units go back to the author, who
corrects how the answers were filed, and a new round of units is reviewed. Ollama is faked
(tests/api/conftest.py)."""

from api_helpers import decide_all, run_jobs, two_experts
from sqlalchemy import text

from app.core.db import session_factory

PEER_COMMENT = "Q2 is about this passage too: file it under h1."
ADMIN_COMMENT = "Agree with the reviewer, please look at Q2 again."


def decisions(units, **by_kind):
    """A decision per unit, by its kind: decisions(units, fragment=("request_changes", "x"))."""
    out = []
    for unit in units:
        decision, *comment = by_kind.get(unit["kind"], ("approve",))
        out.append(
            {
                "unit_id": unit["id"],
                "decision": decision,
                "comment": comment[0] if comment else None,
            }
        )
    return {"decisions": out}


async def decide(api, assignment_id, **by_kind):
    units = await api.ok("GET", f"/assignments/{assignment_id}/units")
    return await api.request(
        "POST", f"/assignments/{assignment_id}/unit-decisions", json=decisions(units, **by_kind)
    )


async def state(api, assignment_id) -> str:
    return (await api.ok("GET", f"/assignments/{assignment_id}"))["state"]


async def reviewer_challenges():
    """e2's units are read by e1, who challenges the fragment unit and votes to decline."""
    admin, e1, e2, first, second = await two_experts()
    await e1.ok("POST", f"/assignments/{second}/review/open", 204)
    units = await e1.ok("GET", f"/assignments/{second}/units")
    fragment = next(u for u in units if u["kind"] == "fragment")
    await e1.ok(
        "POST",
        f"/assignments/{second}/units/{fragment['id']}/comments",
        201,
        json={"body": PEER_COMMENT, "stance": "challenge"},
    )
    await e1.ok("PUT", f"/assignments/{second}/vote", json={"vote": "decline", "review_round": 1})
    return admin, e1, e2, second


async def sent_back():
    """The admin has read it and sent it back: e2 (the author) is in the expert check, round 2."""
    admin, e1, e2, second = await reviewer_challenges()
    response = await decide(admin, second, fragment=("request_changes", ADMIN_COMMENT))
    assert response.status_code == 200, response.text
    return admin, e1, e2, second


async def test_a_change_request_needs_a_comment():
    admin, e1, e2, first, second = await two_experts()
    units = await admin.ok("GET", f"/assignments/{second}/units")
    for comment in (None, "   "):
        body = {
            "decisions": [
                {"unit_id": u["id"], "decision": "request_changes", "comment": comment}
                for u in units
            ]
        }
        await admin.fails(
            "POST", f"/assignments/{second}/unit-decisions", 422, "comment_required", json=body
        )
    assert await state(admin, second) == "peer_review", "nothing was recorded"


async def test_a_reviewers_challenge_is_a_comment_for_the_admin_not_a_change_request():
    admin, e1, e2, second = await reviewer_challenges()
    assert await state(admin, second) == "peer_review", "a challenge does not move anything"
    units = await admin.ok("GET", f"/assignments/{second}/units")
    fragment = next(u for u in units if u["kind"] == "fragment")
    [comment] = fragment["comments"]
    assert (comment["stance"], comment["body"]) == ("challenge", PEER_COMMENT)
    assert comment["speaker"] == {"kind": "reviewer", "pseudonym": e1.pseudonym}
    assert fragment["decisions"] == [], "reviewers record no decision on a unit"
    findings = await e2.ok("GET", f"/assignments/{second}/findings")
    assert findings["review_round"] == 1 and findings["feedback"] == []


async def test_the_admin_sends_the_units_back_to_the_author():
    admin, e1, e2, second = await sent_back()
    view = await admin.ok("GET", f"/assignments/{second}")
    assert view["state"] == "expert_check" and view["review_round"] == 2
    assert view["allowed_actions"] == ["skip_expert_check"]
    author_view = await e2.ok("GET", f"/assignments/{second}")
    assert author_view["allowed_actions"] == [
        "complete_expert_check",
        "correct_findings",
        "skip_expert_check",
    ]

    assert await admin.ok("GET", f"/assignments/{second}/units") == [], (
        "no units until they are cut"
    )
    old = await admin.ok("GET", f"/assignments/{second}/units", params={"review_round": 1})
    assert {u["status"] for u in old} == {"superseded"}
    fragment = next(u for u in old if u["kind"] == "fragment")
    assert [(d["stage"], d["decision"]) for d in fragment["decisions"]] == [
        ("admin", "request_changes"),
    ]
    assert [c["body"] for c in fragment["comments"]] == [PEER_COMMENT], "the talk is kept too"


async def test_the_author_reads_the_request_and_the_discussion_of_the_round_sent_back():
    admin, e1, e2, second = await sent_back()
    findings = await e2.ok("GET", f"/assignments/{second}/findings")
    assert findings["review_round"] == 2 and findings["editable"] is True
    assert [(f["by"], f["comment"]) for f in findings["feedback"]] == [("admin", ADMIN_COMMENT)]
    feedback = findings["feedback"][0]
    assert feedback["kind"] == "fragment" and feedback["patient_words"]
    assert "avoidance" in feedback["unit_text"], "the unit it is about, in the author's own words"
    everything = str(findings)
    for secret in (e1.user_id, e1.pseudonym, admin.user_id, admin.pseudonym):
        assert secret not in everything

    old = await e2.ok("GET", f"/assignments/{second}/units", params={"review_round": 1})
    fragment = next(u for u in old if u["kind"] == "fragment")
    [comment] = fragment["comments"]
    assert comment["body"] == PEER_COMMENT
    assert comment["speaker"] == {"kind": "reviewer", "pseudonym": e1.pseudonym}

    events = await e2.ok("GET", f"/assignments/{second}/events")
    sent = [e for e in events if e["action"] == "request_changes"]
    assert [e["actor"] for e in sent] == ["admin"]
    assert e1.user_id not in str(events) and e1.pseudonym not in str(events)


async def test_decisions_cannot_be_made_on_units_that_were_sent_back():
    admin, e1, e2, second = await sent_back()
    await e1.fails(
        "POST",
        f"/assignments/{second}/unit-decisions",
        409,
        "illegal_transition",
        json={"decisions": []},
    )
    await e1.fails(
        "PUT",
        f"/assignments/{second}/vote",
        409,
        "review_closed",
        json={"vote": "accept", "review_round": 1},
    )
    await admin.fails(
        "POST",
        f"/assignments/{second}/unit-decisions",
        409,
        "illegal_transition",
        json={"decisions": []},
    )


async def test_the_admin_can_send_back_without_waiting_for_the_reviewers():
    admin, e1, e2, first, second = await two_experts()
    assert await state(admin, second) == "peer_review"
    response = await decide(admin, second, fragment=("request_changes", ADMIN_COMMENT))
    assert response.status_code == 200
    assert await state(admin, second) == "expert_check"
    listed = await e1.ok("GET", "/reviews", params={"status": "open"})
    assert second not in [q["assignment_id"] for q in listed], "no longer under review"


async def test_a_second_round_is_cut_from_the_corrected_filing_and_judged_afresh():
    admin, e1, e2, second = await sent_back()
    await e2.ok(
        "PUT",
        f"/assignments/{second}/findings",
        json={"version": 1, "sentences": {"Q2.1": ["h1"]}},
    )
    await e2.ok("POST", f"/assignments/{second}/expert-check/complete")
    await run_jobs()
    assert await state(admin, second) == "peer_review"

    units = await e2.ok("GET", f"/assignments/{second}/units")
    assert [(u["ordinal"], u["kind"], u["status"], u["review_round"]) for u in units] == [
        (1, "fragment", "pending", 2),
        (2, "case", "pending", 2),
    ]
    assert "Q2: " in units[0]["text"], "the sentence moved to the citation, so the unit has it"
    [item] = [q for q in await e1.ok("GET", "/reviews") if q["assignment_id"] == second]
    assert item["unit_count"] == 2 and item["review_round"] == 2
    assert (item["accepts"], item["declines"], item["my_vote"], item["comment_count"]) == (
        0,
        0,
        None,
        0,
    ), "a new round is judged afresh"
    mine = await e1.ok("GET", f"/assignments/{second}/units")
    assert all(u["comments"] == [] for u in mine)
    votes = await e1.ok("GET", f"/assignments/{second}/votes")
    assert (votes["review_round"], votes["votes"]) == (2, [])
    await e1.fails(
        "PUT",
        f"/assignments/{second}/vote",
        409,
        "stale_round",
        json={"vote": "accept", "review_round": 1},
    )

    old = await admin.ok("GET", f"/assignments/{second}/units", params={"review_round": 1})
    assert {u["status"] for u in old} == {"superseded"}, "the history is kept"
    listed = await admin.ok("GET", "/knowledge-units")
    assert sorted(
        (u["review_round"], u["status"]) for u in listed if u["assignment_id"] == second
    ) == [
        (1, "superseded"),
        (1, "superseded"),
        (2, "pending"),
        (2, "pending"),
    ]


async def test_only_the_last_round_reaches_the_rag_tables():
    admin, e1, e2, second = await sent_back()
    await e2.ok(
        "PUT",
        f"/assignments/{second}/findings",
        json={"version": 1, "sentences": {"Q2.1": ["h1"]}},
    )
    await e2.ok("POST", f"/assignments/{second}/expert-check/complete")
    await run_jobs()
    await decide_all(admin, second)
    await run_jobs()
    assert await state(admin, second) == "ingested"

    async with session_factory()() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, embed_text FROM chips.finding_units "
                    "WHERE session_id = :s ORDER BY id"
                ),
                {"s": second},
            )
        ).all()
    assert len(rows) == 2, "one copy of each unit, not one per round"
    fragment = next(text_ for id_, text_ in rows if id_.endswith("-h1"))
    assert "sleep loss" in fragment, "the corrected cut"
    case = next(text_ for id_, text_ in rows if id_.endswith("-case"))
    assert "sleep loss" not in case
