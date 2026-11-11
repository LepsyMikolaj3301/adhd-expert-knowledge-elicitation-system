"""The admin can ask for changes after reading the discussion: the answers go back to the author,
who edits them (and how their lines are linked), and a new round is reviewed. Ollama and
LanguageTool are faked (tests/api/conftest.py)."""

from api_helpers import OPEN_ANSWERS, decide_all, run_jobs, save_proofread, two_experts
from sqlalchemy import text

from app.core.db import session_factory

PEER_COMMENT = "Q2 is about this passage too: link it to h1."
ADMIN_COMMENT = "Agree with the reviewer, please look at Q2 again."
EVERY_ANSWER = ("Q1", "Q2", "Q3", "Q4", "Q5")


async def decide(api, assignment_id, **by_question):
    """A decision per answer: decide(api, id, Q2=("request_changes", "x")); the rest approve."""
    decisions = []
    for question_id in EVERY_ANSWER:
        decision, *comment = by_question.get(question_id, ("approve",))
        decisions.append(
            {
                "question_id": question_id,
                "decision": decision,
                "comment": comment[0] if comment else None,
            }
        )
    return await api.request(
        "POST", f"/assignments/{assignment_id}/answer-decisions", json={"decisions": decisions}
    )


async def state(api, assignment_id) -> str:
    return (await api.ok("GET", f"/assignments/{assignment_id}"))["state"]


async def reviewer_challenges():
    """e2's answers are read by e1, who challenges Q2 and disapproves of it."""
    admin, e1, e2, first, second = await two_experts()
    await e1.ok("POST", f"/assignments/{second}/review/open", 204)
    await e1.ok(
        "POST",
        f"/assignments/{second}/answers/Q2/comments",
        201,
        json={"body": PEER_COMMENT, "stance": "challenge"},
    )
    await e1.ok(
        "PUT",
        f"/assignments/{second}/answers/Q2/vote",
        json={"vote": "disapprove", "review_round": 1},
    )
    return admin, e1, e2, second


async def sent_back():
    """The admin has read it and sent it back: e2 (the author) checks it again, round 2."""
    admin, e1, e2, second = await reviewer_challenges()
    response = await decide(admin, second, Q2=("request_changes", ADMIN_COMMENT))
    assert response.status_code == 200, response.text
    return admin, e1, e2, second


async def test_a_change_request_needs_a_comment():
    admin, e1, e2, first, second = await two_experts()
    for comment in (None, "   "):
        response = await decide(admin, second, Q1=("request_changes", comment))
        assert response.status_code == 422 and response.json()["code"] == "comment_required"
    assert await state(admin, second) == "peer_review", "nothing was recorded"


async def test_a_reviewers_challenge_is_a_comment_for_the_admin_not_a_change_request():
    admin, e1, e2, second = await reviewer_challenges()
    assert await state(admin, second) == "peer_review", "a challenge does not move anything"
    review = await admin.ok("GET", f"/assignments/{second}/answers")
    q2 = next(a for a in review["answers"] if a["question_id"] == "Q2")
    [comment] = q2["comments"]
    assert (comment["stance"], comment["body"]) == ("challenge", PEER_COMMENT)
    assert comment["speaker"] == {"kind": "reviewer", "pseudonym": e1.pseudonym}
    assert q2["decision"] is None, "reviewers record no decision on an answer"
    checked = await e2.ok("GET", f"/assignments/{second}/proofread")
    assert checked["review_round"] == 1 and checked["feedback"] == []


async def test_the_admin_sends_the_answers_back_to_the_author():
    admin, e1, e2, second = await sent_back()
    view = await admin.ok("GET", f"/assignments/{second}")
    assert view["state"] == "proofread_check" and view["review_round"] == 2
    assert view["allowed_actions"] == ["cancel"]
    author_view = await e2.ok("GET", f"/assignments/{second}")
    assert author_view["allowed_actions"] == ["edit_proofread", "submit_for_review"]

    old = await admin.ok("GET", f"/assignments/{second}/answers")
    assert old["review_round"] == 1 and old["rounds"] == [1], "round 2 is not submitted yet"
    q2 = next(a for a in old["answers"] if a["question_id"] == "Q2")
    assert q2["decision"]["decision"] == "request_changes"
    assert [c["body"] for c in q2["comments"]] == [PEER_COMMENT], "the talk is kept too"


async def test_the_author_reads_the_request_and_the_discussion_of_the_round_sent_back():
    admin, e1, e2, second = await sent_back()
    checked = await e2.ok("GET", f"/assignments/{second}/proofread")
    assert checked["review_round"] == 2 and checked["editable"] is True
    assert checked["feedback"] == [{"question_id": "Q2", "comment": ADMIN_COMMENT}]
    by_question = {item["question_id"]: item for item in checked["items"]}
    assert by_question["Q2"]["final"] == OPEN_ANSWERS["Q2"], "round 2 starts where round 1 ended"
    everything = str(checked)
    for secret in (e1.user_id, e1.pseudonym, admin.user_id, admin.pseudonym):
        assert secret not in everything

    old = await e2.ok("GET", f"/assignments/{second}/answers", params={"review_round": 1})
    q2 = next(a for a in old["answers"] if a["question_id"] == "Q2")
    [comment] = q2["comments"]
    assert comment["body"] == PEER_COMMENT
    assert comment["speaker"] == {"kind": "reviewer", "pseudonym": e1.pseudonym}

    events = await e2.ok("GET", f"/assignments/{second}/events")
    sent = [e for e in events if e["action"] == "request_changes"]
    assert [e["actor"] for e in sent] == ["admin"]
    assert e1.user_id not in str(events) and e1.pseudonym not in str(events)


async def test_nothing_can_be_decided_on_answers_that_were_sent_back():
    admin, e1, e2, second = await sent_back()
    await e1.fails(
        "POST",
        f"/assignments/{second}/answer-decisions",
        409,
        "illegal_transition",
        json={"decisions": []},
    )
    await e1.fails(
        "PUT",
        f"/assignments/{second}/answers/Q1/vote",
        409,
        "review_closed",
        json={"vote": "approve", "review_round": 1},
    )
    await admin.fails(
        "POST",
        f"/assignments/{second}/answer-decisions",
        409,
        "illegal_transition",
        json={"decisions": []},
    )


async def test_the_admin_can_send_back_without_waiting_for_the_reviewers():
    admin, e1, e2, first, second = await two_experts()
    assert await state(admin, second) == "peer_review"
    response = await decide(admin, second, Q2=("request_changes", ADMIN_COMMENT))
    assert response.status_code == 200
    assert await state(admin, second) == "proofread_check"
    listed = await e1.ok("GET", "/reviews", params={"status": "open"})
    assert second not in [q["assignment_id"] for q in listed], "no longer under review"


async def resubmitted():
    """The author edited Q2, linked it to h1 and submitted round 2."""
    admin, e1, e2, second = await sent_back()
    q2 = OPEN_ANSWERS["Q2"]
    await save_proofread(e2, second, {}, {"Q2": {q2: ["h1"]}})
    await e2.ok("POST", f"/assignments/{second}/submit-for-review")
    return admin, e1, e2, second


async def test_a_second_round_is_judged_afresh():
    admin, e1, e2, second = await resubmitted()
    assert await state(admin, second) == "peer_review"
    [item] = [q for q in await e1.ok("GET", "/reviews") if q["assignment_id"] == second]
    assert item["answer_count"] == 5 and item["review_round"] == 2
    assert (item["approvals"], item["disapprovals"], item["my_votes"], item["comment_count"]) == (
        0,
        0,
        0,
        0,
    ), "a new round is judged afresh"
    review = await e1.ok("GET", f"/assignments/{second}/answers")
    assert review["review_round"] == 2
    assert all(a["comments"] == [] and a["votes"] == [] for a in review["answers"])
    q2 = next(a for a in review["answers"] if a["question_id"] == "Q2")
    assert q2["lines"][0]["targets"] == ["h1"]
    await e1.fails(
        "PUT",
        f"/assignments/{second}/answers/Q2/vote",
        409,
        "stale_round",
        json={"vote": "approve", "review_round": 1},
    )
    history = await admin.ok("GET", f"/assignments/{second}/answers", params={"review_round": 1})
    assert history["rounds"] == [1, 2] and history["review_round"] == 1
    await admin.fails(
        "GET", f"/assignments/{second}/answers", 404, "not_found", params={"review_round": 3}
    )
    as_reviewer = await e1.ok("GET", f"/assignments/{second}/answers", params={"review_round": 1})
    assert as_reviewer["review_round"] == 2, "reviewers read the round under review only"


async def test_only_the_last_round_reaches_the_rag_tables():
    admin, e1, e2, second = await resubmitted()
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
    assert len(rows) == 2, "one copy of each unit"
    fragment = next(text_ for id_, text_ in rows if id_.endswith("-h1"))
    assert "sleep loss" in fragment, "the round-2 link"
    case = next(text_ for id_, text_ in rows if id_.endswith("-case"))
    assert "sleep loss" not in case
