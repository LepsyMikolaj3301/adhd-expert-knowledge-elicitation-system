import asyncio

import pytest
from alembic import command
from api_helpers import (
    CONFOUNDER,
    CUE,
    DESIGN_SECRET,
    FULL_PAYLOAD,
    HYPOTHESIS,
    OPEN_ANSWERS,
    Q4_WHY,
    Q5_ANSWER,
    VIGNETTE_TEXT,
    WHATIF,
    admin_api,
    answer_and_submit,
    assign,
    decide_all,
    expert_api,
    highlight,
    published_version,
    run_jobs,
    save,
    to_review,
)
from conftest import alembic_config
from sqlalchemy import select, text

from app.assignments.answers import count_words, render_chips
from app.assignments.models import Submission
from app.core.db import session_factory
from app.knowledge.models import KnowledgeUnit


async def _started(**version_overrides):
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    version = await published_version(admin, **version_overrides)
    [assignment_id] = await assign(admin, version, expert)
    await expert.ok("POST", f"/assignments/{assignment_id}/start")
    return admin, expert, assignment_id


async def test_every_question_is_sent_at_once_with_exact_wording():
    """No lock: Q1-Q6 are all there from the start and can be answered in any order."""
    _, expert, assignment_id = await _started()
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["audience"] == "expert"
    questions = {q["id"]: q for q in view["vignette"]["questions"]}
    assert list(questions) == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
    assert questions["Q4"]["text"] == (
        f"Given your hypothesis about this person so far: how would it change if {WHATIF}?"
    )
    assert questions["Q4"]["wording"]["shift_labels"]["0"] == "is unchanged"
    assert all("min_words" not in q for q in questions.values()), "length is nobody's gate"
    assert "hypothesis_min_words" not in questions["Q4"]["wording"]
    assert view["allowed_actions"] == ["save_draft", "submit"]
    assert "gate_passed_at" not in view and "locked_highlights" not in view
    text = str(view)
    assert DESIGN_SECRET not in text
    assert "planted_cues" not in text
    assert "q4_whatif" not in text


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
async def test_any_question_can_be_answered_first(payload):
    _, expert, assignment_id = await _started()
    await save(expert, assignment_id, payload)


async def test_every_answer_stays_editable_until_submitted():
    _, expert, assignment_id = await _started()
    await save(expert, assignment_id, {"answers": OPEN_ANSWERS, "highlights": [highlight(1)]})
    for changed in (
        {"answers": {**OPEN_ANSWERS, "Q1": "rewritten"}},
        {"answers": {"Q2": OPEN_ANSWERS["Q2"]}},
        {"answers": {**OPEN_ANSWERS, "Q5": "fine"}, "highlights": []},
        {"answers": OPEN_ANSWERS, "highlights": [highlight(1, CONFOUNDER, "away")]},
    ):
        await save(expert, assignment_id, changed)


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
        {"answers": {**OPEN_ANSWERS, "Q5": Q5_ANSWER}},  # no why for a non-zero shift
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
    ({"highlights": [highlight(1, direction=None)]}, "highlight_no_direction"),
    (
        {"answers": {**OPEN_ANSWERS, "Q4": Q4_WHY, "Q5": f"⟦h9⟧ {Q5_ANSWER}"}},
        "unknown_chip",
    ),
]


@pytest.mark.parametrize(("change", "code"), SUBMIT_PROBLEMS)
async def test_submit_problems_have_stable_codes(change, code):
    _, expert, assignment_id = await _started()
    await save(expert, assignment_id, {**FULL_PAYLOAD, **change})
    await expert.fails("POST", f"/assignments/{assignment_id}/submit", 422, code)
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "in_progress", "a refused submit must keep the draft editable"


@pytest.mark.parametrize(
    ("question_ids", "payload"),
    [
        (["Q1", "Q2", "Q3"], {"answers": {"Q5": "not asked"}}),
        (["Q1", "Q2", "Q3"], {"answers": OPEN_ANSWERS, "q4": {"shift": 0}}),
        (["Q1", "Q2", "Q3"], {"answers": OPEN_ANSWERS, "rating": 1}),
    ],
)
async def test_answers_to_questions_not_asked_are_refused(question_ids, payload):
    _, expert, assignment_id = await _started(question_ids=question_ids)
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


async def test_shift_of_zero_needs_only_the_hypothesis():
    _, expert, assignment_id = await _started()
    answers = {**OPEN_ANSWERS, "Q5": Q5_ANSWER}
    await save(
        expert,
        assignment_id,
        {"answers": answers, "q4": {"hypothesis": HYPOTHESIS, "shift": 0}, "rating": 3},
    )
    await expert.ok("POST", f"/assignments/{assignment_id}/submit")


async def test_answers_are_trimmed():
    _, expert, assignment_id = await _started()
    payload = {
        **FULL_PAYLOAD,
        "answers": {**OPEN_ANSWERS, "Q4": f"  {Q4_WHY}  ", "Q5": f"  {Q5_ANSWER}  "},
    }
    await save(expert, assignment_id, payload)
    await expert.ok("POST", f"/assignments/{assignment_id}/submit")
    submission = await expert.ok("GET", f"/assignments/{assignment_id}/submission")
    stored = submission["payload"]
    assert stored["answers"]["Q4"] == Q4_WHY
    assert stored["answers"]["Q5"] == Q5_ANSWER


# --- citations ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("highlights", "code"),
    [
        ([{**highlight(1), "text": "not what the span holds"}], "highlight_not_in_vignette"),
        ([{**highlight(1), "span": [-5, 10]}], "highlight_not_in_vignette"),
        ([{**highlight(1), "span": [5, 5], "text": "x"}], "highlight_not_in_vignette"),
        ([highlight(2)], "chip_numbers"),
        ([highlight(1), highlight(3, CONFOUNDER)], "chip_numbers"),
    ],
)
async def test_a_draft_with_a_broken_citation_is_refused(highlights, code):
    _, expert, assignment_id = await _started()
    await expert.fails(
        "PUT",
        f"/assignments/{assignment_id}/draft",
        422,
        code,
        json={"version": 1, "payload": {"highlights": highlights}},
    )


async def test_a_citation_may_be_saved_before_its_direction_is_chosen():
    _, expert, assignment_id = await _started()
    await save(expert, assignment_id, {"highlights": [highlight(1, direction=None)]})
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["draft"]["payload"]["highlights"][0]["direction"] is None
    assert view["draft"]["payload"]["highlights"][0]["span"] == highlight(1)["span"]


async def test_spans_count_characters_the_way_python_does_not_utf16():
    """An emoji is one character here and two in the browser, which must convert."""
    emoji_text = f"😀 {VIGNETTE_TEXT}"
    _, expert, assignment_id = await _started(text=emoji_text)
    start = emoji_text.index(CUE)
    assert start == 2
    citation = {"chip": 1, "text": CUE, "span": [start, start + len(CUE)], "direction": "away"}
    await save(expert, assignment_id, {"highlights": [citation]})
    await expert.fails(
        "PUT",
        f"/assignments/{assignment_id}/draft",
        422,
        "highlight_not_in_vignette",
        json={"version": 2, "payload": {"highlights": [{**citation, "span": [3, 3 + len(CUE)]}]}},
    )


async def test_submit_needs_a_direction_on_every_citation():
    _, expert, assignment_id = await _started()
    await save(
        expert,
        assignment_id,
        {**FULL_PAYLOAD, "highlights": [highlight(1), highlight(2, CONFOUNDER, None)]},
    )
    body = await expert.fails(
        "POST", f"/assignments/{assignment_id}/submit", 422, "highlight_no_direction"
    )
    assert body["details"]["chips"] == [2]
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "in_progress"


async def test_submit_refuses_a_chip_without_a_citation():
    _, expert, assignment_id = await _started()
    answers = {**FULL_PAYLOAD["answers"], "Q2": f"⟦h7⟧ {OPEN_ANSWERS['Q2']}"}
    await save(expert, assignment_id, {**FULL_PAYLOAD, "answers": answers})
    body = await expert.fails("POST", f"/assignments/{assignment_id}/submit", 422, "unknown_chip")
    assert body["details"] == {"question_id": "Q2", "chip": 7}


async def test_the_submission_keeps_citations_and_chips():
    _, expert, assignment_id = await _started()
    answers = {**FULL_PAYLOAD["answers"], "Q5": f"⟦h2⟧ {Q5_ANSWER}"}
    citations = [highlight(1), highlight(2, CONFOUNDER, "away")]
    await save(expert, assignment_id, {**FULL_PAYLOAD, "answers": answers, "highlights": citations})
    await expert.ok("POST", f"/assignments/{assignment_id}/submit")
    submission = await expert.ok("GET", f"/assignments/{assignment_id}/submission")
    assert submission["payload_format"] == 2
    stored = submission["payload"]
    assert stored["highlights"] == citations
    assert stored["answers"]["Q5"].startswith("⟦h2⟧ ")
    assert "locked_highlights" not in stored and "gate_passed_at" not in stored


def test_chips_render_as_the_first_eight_words_of_their_citation():
    citations = [
        {"chip": 1, "text": "one two three four five six seven eight nine"},
        {"chip": 2, "text": "short quote"},
    ]
    assert render_chips("⟦h1⟧ and ⟦h2⟧.", citations) == (
        "«one two three four five six seven eight…» and «short quote»."
    )
    assert render_chips("No chips here.", []) == "No chips here."


async def test_units_show_quotes_instead_of_chip_tokens():
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    answers = {**FULL_PAYLOAD["answers"], "Q5": f"⟦h1⟧ {Q5_ANSWER}"}
    await answer_and_submit(expert, assignment_id, {**FULL_PAYLOAD, "answers": answers})
    await to_review(expert, assignment_id)
    await decide_all(admin, assignment_id)
    await run_jobs()
    async with session_factory()() as db:
        units = list(await db.scalars(select(KnowledgeUnit)))
    text = "\n".join(unit.text for unit in units)
    assert "⟦" not in text
    assert f"Q5: «I reorganised my entire desk instead of starting…» {Q5_ANSWER}" in text


async def test_the_admin_can_list_the_assignments_of_one_version():
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    first = await published_version(admin)
    second = await published_version(admin)
    [wanted] = await assign(admin, first, expert)
    await assign(admin, second, expert)
    rows = await admin.ok("GET", "/assignments", params={"vignette_version_id": first["id"]})
    assert [row["id"] for row in rows] == [wanted]
    assert rows[0]["vignette_version_id"] == first["id"]


async def test_the_migration_clears_old_fragments_so_old_drafts_still_load():
    _, expert, assignment_id = await _started()
    async with session_factory()() as db:
        await db.execute(
            text(
                "UPDATE app.answer_drafts SET payload = "
                """'{"answers": {"Q1": "kept"}, "quoted_fragments": ["old"]}'::jsonb"""
            )
        )
        await db.commit()
    await asyncio.to_thread(command.downgrade, alembic_config(), "0001")
    await asyncio.to_thread(command.upgrade, alembic_config(), "head")
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["draft"]["payload"]["answers"] == {"Q1": "kept"}
    assert view["draft"]["payload"]["highlights"] == []


async def test_q1_asks_for_fragments_in_either_direction():
    _, expert, assignment_id = await _started()
    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    q1 = view["vignette"]["questions"][0]["text"]
    assert "in either direction" in q1
    assert "Quote" not in q1


def _with_answers(**answers):
    return {**FULL_PAYLOAD, "answers": {**FULL_PAYLOAD["answers"], **answers}}


async def test_an_empty_answer_cannot_be_submitted():
    _, expert, assignment_id = await _started()
    await save(expert, assignment_id, _with_answers(Q5="   "))
    await expert.fails("POST", f"/assignments/{assignment_id}/submit", 422, "empty_answer")
    assert (await expert.ok("GET", f"/assignments/{assignment_id}"))["state"] == "in_progress"


async def test_short_answers_are_accepted_on_submit():
    _, expert, assignment_id = await _started()
    short = {"Q1": "Sleep.", "Q2": "Mood.", "Q3": "No."}
    payload = {
        **FULL_PAYLOAD,
        "answers": {**FULL_PAYLOAD["answers"], **short, "Q4": "Exam.", "Q5": "Over-reading."},
        "q4": {"hypothesis": "tired", "shift": 1, "toward": "less_adhd"},
    }
    await save(expert, assignment_id, payload)
    await expert.ok("POST", f"/assignments/{assignment_id}/submit")


@pytest.mark.parametrize("missing", ["Q1", "Q2", "Q3", "Q5"])
async def test_every_open_question_needs_an_answer(missing):
    _, expert, assignment_id = await _started()
    answers = {q: a for q, a in FULL_PAYLOAD["answers"].items() if q != missing}
    await save(expert, assignment_id, {**FULL_PAYLOAD, "answers": answers})
    await expert.fails("POST", f"/assignments/{assignment_id}/submit", 422, "empty_answer")


async def test_a_vignette_asking_only_q5_cannot_be_submitted_empty():
    _, expert, assignment_id = await _started(question_ids=["Q5"])
    await expert.fails("POST", f"/assignments/{assignment_id}/submit", 422, "empty_answer")


def test_count_words_counts_different_words():
    assert count_words("test Test TEST, test!") == 1
    assert count_words("... --- !!!") == 0
    assert count_words("Pacjent nie śpi dobrze") == 4
    assert count_words("⟦h1⟧ ⟦h2⟧ ⟦h3⟧ word") == 1


async def test_submitting_freezes_the_answers():
    _, expert, assignment_id = await _started()
    await save(expert, assignment_id, FULL_PAYLOAD)
    view = await expert.ok("POST", f"/assignments/{assignment_id}/submit")
    assert view["state"] == "proofreading"
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
    assert submission["payload_format"] == 2
    assert submission["vignette_hash"] == view["vignette"]["content_hash"]
    async with session_factory()() as db:
        assert len(list(await db.scalars(select(Submission)))) == 1


async def test_a_vignette_asking_only_q6():
    _, expert, assignment_id = await _started(question_ids=["Q6"])
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
