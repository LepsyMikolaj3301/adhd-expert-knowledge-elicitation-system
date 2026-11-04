import asyncio
from dataclasses import replace

import pytest
from api_helpers import (
    CUE,
    DESIGN_SECRET,
    FULL_PAYLOAD,
    GATE_ANSWERS,
    HYPOTHESIS,
    Q4_WHY,
    Q5_ANSWER,
    WHATIF,
    admin_api,
    assign,
    expert_api,
    published_version,
    save,
)
from sqlalchemy import select

from app.assignments.answers import count_words
from app.assignments.models import Submission
from app.core.db import session_factory
from app.vignettes.questions import QUESTIONS


async def _started(**version_overrides):
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    version = await published_version(admin, **version_overrides)
    [assignment_id] = await assign(admin, version, expert)
    await expert.ok("POST", f"/assignments/{assignment_id}/start")
    return admin, expert, assignment_id


async def _past_gate(**version_overrides):
    admin, expert, assignment_id = await _started(**version_overrides)
    await save(expert, assignment_id, {"answers": GATE_ANSWERS})
    await expert.ok("POST", f"/assignments/{assignment_id}/pass-gate")
    return admin, expert, assignment_id


async def test_only_the_gate_questions_are_sent_before_the_gate():
    _, expert, assignment_id = await _started()
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["audience"] == "expert"
    assert [q["id"] for q in view["vignette"]["questions"]] == ["Q1", "Q2", "Q3"]
    assert view["allowed_actions"] == ["pass_gate", "save_draft"]
    text = str(view)
    assert "the-whatif-secret" not in text
    assert "less experienced clinician" not in text
    assert DESIGN_SECRET not in text
    assert "planted_cues" not in text
    assert "q4_whatif" not in text


async def test_all_questions_are_sent_after_the_gate_with_exact_wording():
    _, expert, assignment_id = await _past_gate()
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    questions = {q["id"]: q for q in view["vignette"]["questions"]}
    assert list(questions) == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
    assert questions["Q4"]["text"] == (
        f"Given your hypothesis about this person so far: how would it change if {WHATIF}?"
    )
    assert questions["Q4"]["wording"]["shift_labels"]["0"] == "is unchanged"
    assert [q["min_words"] for q in questions.values()] == [15, 10, 10, 5, 10, None]
    assert questions["Q4"]["wording"]["hypothesis_min_words"] == 3
    assert view["gate_passed_at"]
    assert view["allowed_actions"] == ["save_draft", "submit"]
    assert DESIGN_SECRET not in str(view)


@pytest.mark.parametrize(
    "payload",
    [
        {"answers": {"Q4": "why"}},
        {"answers": {"Q5": "text"}},
        {"q4": {"shift": 1}},
        {"rating": 3},
        {"insufficient_information": True},
    ],
)
async def test_later_answers_are_refused_before_the_gate(payload):
    _, expert, assignment_id = await _started()
    await expert.fails(
        "PUT",
        f"/assignments/{assignment_id}/draft",
        422,
        "gate_not_passed",
        json={"version": 1, "payload": payload},
    )


async def test_gate_requires_every_answer():
    _, expert, assignment_id = await _started()
    await save(expert, assignment_id, {"answers": {"Q1": "x", "Q2": "   "}})
    body = await expert.fails(
        "POST", f"/assignments/{assignment_id}/pass-gate", 422, "gate_not_passed"
    )
    assert body["details"]["missing"] == ["Q2", "Q3"]


async def test_passing_the_gate_locks_the_gate_answers_and_is_idempotent():
    _, expert, assignment_id = await _past_gate()
    first = (await expert.ok("GET", f"/assignments/{assignment_id}"))["gate_passed_at"]
    again = await expert.ok("POST", f"/assignments/{assignment_id}/pass-gate")
    assert again["gate_passed_at"] == first

    for changed in (
        {"answers": {**GATE_ANSWERS, "Q1": "rewritten"}},
        {"answers": {"Q2": GATE_ANSWERS["Q2"], "Q3": GATE_ANSWERS["Q3"]}},
    ):
        current = await expert.ok("GET", f"/assignments/{assignment_id}")
        await expert.fails(
            "PUT",
            f"/assignments/{assignment_id}/draft",
            422,
            "gate_locked",
            json={"version": current["draft"]["version"], "payload": changed},
        )
    await save(expert, assignment_id, {"answers": {**GATE_ANSWERS, "Q5": "fine"}})


async def test_stale_autosave_from_a_second_tab_conflicts():
    _, expert, assignment_id = await _started()
    url = f"/assignments/{assignment_id}/draft"
    first = await expert.ok(
        "PUT", url, json={"version": 1, "payload": {"answers": {"Q1": "tab 1"}}}
    )
    assert first["version"] == 2
    body = await expert.fails(
        "PUT",
        url,
        409,
        "draft_conflict",
        json={"version": 1, "payload": {"answers": {"Q1": "tab 2"}}},
    )
    assert body["details"]["current_version"] == 2
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["draft"]["payload"]["answers"]["Q1"] == "tab 1"


async def test_simultaneous_autosaves_never_lose_a_conflict():
    _, expert, assignment_id = await _started()
    url = f"/assignments/{assignment_id}/draft"
    responses = await asyncio.gather(
        *(
            expert.request("PUT", url, json={"version": 1, "payload": {"answers": {"Q1": str(i)}}})
            for i in range(4)
        )
    )
    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409]


async def test_draft_needs_in_progress():
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    version = await published_version(admin)
    [assignment_id] = await assign(admin, version, expert)
    await expert.fails(
        "PUT",
        f"/assignments/{assignment_id}/draft",
        409,
        "not_editable",
        json={"version": 1, "payload": {}},
    )


SUBMIT_PROBLEMS = [
    ({"q4": None}, "submission_incomplete"),
    ({"q4": {"hypothesis": HYPOTHESIS}}, "submission_incomplete"),
    ({"q4": {"shift": 1, "toward": "less_adhd"}}, "submission_incomplete"),
    ({"q4": {"hypothesis": "  ", "shift": 1, "toward": "less_adhd"}}, "submission_incomplete"),
    ({"q4": {"hypothesis": HYPOTHESIS, "shift": 1}}, "submission_incomplete"),
    ({"rating": None}, "submission_incomplete"),
    (
        {"answers": {**GATE_ANSWERS, "Q5": Q5_ANSWER}},  # no why for a non-zero shift
        "submission_incomplete",
    ),
    (
        {"q4": {"hypothesis": HYPOTHESIS, "shift": 0}},  # a why at zero (from FULL_PAYLOAD)
        "q4_why_without_shift",
    ),
    (
        {"q4": {"hypothesis": HYPOTHESIS, "shift": -1, "toward": "less_adhd"}},
        "toward_without_change",
    ),
    (
        {"q4": {"hypothesis": HYPOTHESIS, "shift": 1, "toward": "other"}},
        "other_without_name",
    ),
    (
        {
            "q4": {
                "hypothesis": HYPOTHESIS,
                "shift": 1,
                "toward": "less_adhd",
                "other_explanation": "x",
            }
        },
        "other_without_name",
    ),
    ({"rating": 3, "insufficient_information": True}, "rating_conflict"),
    ({"quoted_fragments": ["   "]}, "empty_answer"),
    ({"quoted_fragments": ["never written"]}, "quote_not_in_vignette"),
]


@pytest.mark.parametrize(("change", "code"), SUBMIT_PROBLEMS)
async def test_submit_problems_have_stable_codes(change, code):
    _, expert, assignment_id = await _past_gate()
    await save(expert, assignment_id, {**FULL_PAYLOAD, **change})
    await expert.fails("POST", f"/assignments/{assignment_id}/submit", 422, code)
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "in_progress", "a refused submit must keep the draft editable"


@pytest.mark.parametrize(
    ("question_ids", "payload"),
    [
        (["Q1", "Q2", "Q3"], {"answers": {"Q5": "not asked"}}),
        (["Q1", "Q2", "Q3"], {"answers": GATE_ANSWERS, "q4": {"shift": 0}}),
        (["Q1", "Q2", "Q3"], {"answers": GATE_ANSWERS, "rating": 1}),
    ],
)
async def test_answers_to_questions_not_asked_are_refused(question_ids, payload):
    _, expert, assignment_id = await _started(question_ids=question_ids, q4_whatif=None)
    await expert.fails(
        "PUT",
        f"/assignments/{assignment_id}/draft",
        422,
        "question_not_asked",
        json={"version": 1, "payload": payload},
    )


async def test_q6_is_answered_with_a_rating_not_text():
    _, expert, assignment_id = await _started()
    await expert.fails(
        "PUT",
        f"/assignments/{assignment_id}/draft",
        422,
        "answer_to_rating_question",
        json={"version": 1, "payload": {"answers": {"Q6": "3"}}},
    )


async def test_submit_before_the_gate_is_refused():
    _, expert, assignment_id = await _started()
    await expert.fails("POST", f"/assignments/{assignment_id}/submit", 422, "gate_not_passed")


async def test_shift_of_zero_needs_only_the_hypothesis():
    _, expert, assignment_id = await _past_gate()
    answers = {**GATE_ANSWERS, "Q5": Q5_ANSWER}
    await save(
        expert,
        assignment_id,
        {"answers": answers, "q4": {"hypothesis": HYPOTHESIS, "shift": 0}, "rating": 3},
    )
    await expert.ok("POST", f"/assignments/{assignment_id}/submit")


async def test_answers_are_trimmed():
    _, expert, assignment_id = await _past_gate()
    payload = {
        **FULL_PAYLOAD,
        "answers": {**GATE_ANSWERS, "Q4": f"  {Q4_WHY}  ", "Q5": f"  {Q5_ANSWER}  "},
        "quoted_fragments": [f"  {CUE}  "],
    }
    await save(expert, assignment_id, payload)
    await expert.ok("POST", f"/assignments/{assignment_id}/submit")
    submission = await expert.ok("GET", f"/assignments/{assignment_id}/submission")
    stored = submission["payload"]
    assert stored["answers"]["Q4"] == Q4_WHY
    assert stored["answers"]["Q5"] == Q5_ANSWER
    assert stored["quoted_fragments"] == [CUE]


def _with_answers(**answers):
    return {**FULL_PAYLOAD, "answers": {**FULL_PAYLOAD["answers"], **answers}}


@pytest.mark.parametrize(
    ("payload", "code", "question"),
    [
        (_with_answers(Q5="   "), "empty_answer", None),
        (_with_answers(Q5="Too short to count."), "answer_too_short", "Q5"),
        (_with_answers(Q5="test " * 40), "answer_too_short", "Q5"),
        (_with_answers(Q5=". " * 40), "answer_too_short", "Q5"),
        (_with_answers(Q4="Exam."), "answer_too_short", "Q4"),
        (
            {**FULL_PAYLOAD, "q4": {"hypothesis": "tired", "shift": 1, "toward": "less_adhd"}},
            "answer_too_short",
            "Q4 hypothesis",
        ),
    ],
)
async def test_poorly_filled_answers_cannot_be_submitted(payload, code, question):
    _, expert, assignment_id = await _past_gate()
    await save(expert, assignment_id, payload)
    body = await expert.fails("POST", f"/assignments/{assignment_id}/submit", 422, code)
    if question:
        assert body["details"]["answers"][0]["question_id"] == question
    assert (await expert.ok("GET", f"/assignments/{assignment_id}"))["state"] == "in_progress"


async def test_short_gate_answers_are_stopped_at_the_gate_where_they_can_still_be_fixed():
    _, expert, assignment_id = await _started()
    await save(expert, assignment_id, {"answers": {**GATE_ANSWERS, "Q2": "Sleep.", "Q3": "No."}})
    body = await expert.fails(
        "POST", f"/assignments/{assignment_id}/pass-gate", 422, "answer_too_short"
    )
    assert [a["question_id"] for a in body["details"]["answers"]] == ["Q2", "Q3"]
    assert body["details"]["answers"][0] == {"question_id": "Q2", "words": 1, "min_words": 10}
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["gate_passed_at"] is None, "the answers must stay editable"
    await save(expert, assignment_id, {"answers": GATE_ANSWERS})
    await expert.ok("POST", f"/assignments/{assignment_id}/pass-gate")


async def test_a_raised_minimum_does_not_strand_answers_already_locked(monkeypatch):
    _, expert, assignment_id = await _past_gate()
    await save(expert, assignment_id, FULL_PAYLOAD)
    monkeypatch.setitem(QUESTIONS, "Q1", replace(QUESTIONS["Q1"], min_words=1000))
    await expert.ok("POST", f"/assignments/{assignment_id}/submit")


async def test_a_vignette_asking_only_q5_cannot_be_submitted_empty():
    _, expert, assignment_id = await _started(question_ids=["Q5"], q4_whatif=None)
    await expert.fails("POST", f"/assignments/{assignment_id}/submit", 422, "empty_answer")


def test_count_words_counts_different_words():
    assert count_words("test Test TEST, test!") == 1
    assert count_words("... --- !!!") == 0
    assert count_words("Pacjent nie śpi dobrze") == 4


async def test_submitting_freezes_the_answers():
    _, expert, assignment_id = await _past_gate()
    await save(expert, assignment_id, FULL_PAYLOAD)
    view = await expert.ok("POST", f"/assignments/{assignment_id}/submit")
    assert view["state"] == "processing"
    assert view["allowed_actions"] == []
    assert view["submitted_at"]
    await expert.fails(
        "PUT",
        f"/assignments/{assignment_id}/draft",
        409,
        "not_editable",
        json={"version": view["draft"]["version"], "payload": FULL_PAYLOAD},
    )
    await expert.fails("POST", f"/assignments/{assignment_id}/submit", 409, "illegal_transition")

    submission = await expert.ok("GET", f"/assignments/{assignment_id}/submission")
    assert submission["payload"]["expert_pseudonym"] == expert.pseudonym
    assert submission["payload"]["gate_passed_at"]
    assert submission["payload_format"] == 1
    assert submission["vignette_hash"] == view["vignette"]["content_hash"]
    async with session_factory()() as db:
        assert len(list(await db.scalars(select(Submission)))) == 1


async def test_vignette_without_gate_questions_starts_open():
    _, expert, assignment_id = await _started(question_ids=["Q6"], q4_whatif=None)
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert [q["id"] for q in view["vignette"]["questions"]] == ["Q6"]
    assert view["allowed_actions"] == ["save_draft", "submit"]
    await save(expert, assignment_id, {"rating": 3})
    await expert.ok("POST", f"/assignments/{assignment_id}/submit")


async def test_expert_list_keeps_a_stable_order():
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    for _ in range(4):
        await assign(admin, await published_version(admin), expert)
    first = await expert.ok("GET", "/assignments")
    assert len(first) == 4
    await expert.ok("POST", f"/assignments/{first[2]['id']}/start")
    second = await expert.ok("GET", "/assignments")
    assert [a["id"] for a in second] == [a["id"] for a in first]
    assert second[2]["state"] == "in_progress"
