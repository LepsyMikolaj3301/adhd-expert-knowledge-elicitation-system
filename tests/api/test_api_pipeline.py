"""The answer pipeline: proofreading and linking, the proofread check, review routing, cutting the
approved answers into units, ingestion.

Ollama and LanguageTool are replaced by `models` (tests/api/conftest.py): a classifier that files
everything under `case` unless told otherwise, deterministic embeddings, a grammar checker that
finds nothing unless told otherwise, and an enhancement that changes nothing unless told otherwise.
"""

from typing import Any
from uuid import UUID

from api_helpers import (
    CONFOUNDER,
    CUE,
    FULL_PAYLOAD,
    OPEN_ANSWERS,
    Q4_WHY,
    Q5_ANSWER,
    admin_api,
    answer_and_submit,
    assign,
    decide_all,
    expert_api,
    highlight,
    proofread,
    published_version,
    run_jobs,
    save_proofread,
    to_review,
    two_experts,
)
from conftest import FakeModels
from sqlalchemy import select, text, update

from app.assignments.models import Assignment
from app.assignments.state_machine import lock_assignment
from app.assignments.states import State
from app.core.db import session_factory
from app.jobs.handlers import unit_content_hash
from app.jobs.models import Job, JobKind
from app.jobs.queue import MAX_ATTEMPTS
from app.knowledge.models import AnswerFindings, KnowledgeUnit
from app.proofread.models import ProofreadRound
from app.reviews.models import ReviewParticipant
from app.settings import settings

# Every open answer cites a highlight, so the classifier has nothing to do.
CITED_OPEN = {
    "Q1": (
        "⟦h1⟧ reads as avoidance of the task rather than ordinary tidiness, "
        "and the exact wording suggests it quite clearly."
    ),
    "Q2": "⟦h2⟧ could equally be sleep loss after the recent move, not a trait at all.",
    "Q3": "⟦h1⟧ How often does this happen, and what was the baseline before the move?",
}
CITED_PAYLOAD: dict[str, Any] = {
    "answers": {
        **CITED_OPEN,
        "Q4": Q4_WHY,
        "Q5": "A junior clinician would over-read ⟦h1⟧ as a clear sign of a lasting trait.",
    },
    "highlights": [highlight(1), highlight(2, CONFOUNDER, "away")],
    "q4": FULL_PAYLOAD["q4"],
    "rating": 2,
}


async def findings_of(assignment_id: str) -> AnswerFindings:
    async with session_factory()() as db:
        row = await db.get(AnswerFindings, UUID(assignment_id))
    assert row is not None, "processing left no findings"
    return row


async def round_of(assignment_id: str, review_round: int = 1) -> ProofreadRound:
    async with session_factory()() as db:
        row = await db.get(ProofreadRound, (UUID(assignment_id), review_round))
    assert row is not None, "proofreading left no round"
    return row


async def setup_one(models=None):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    return admin, expert, assignment_id


def items(view: dict) -> dict[str, dict]:
    return {item["question_id"]: item for item in view["items"]}


# --- proofreading and linking --------------------------------------------------------------


async def test_proofreading_links_the_lines_and_asks_the_model_only_about_the_rest(models):
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    assert await run_jobs() == 1

    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "proofread_check"
    assert view["allowed_actions"] == ["edit_proofread", "submit_for_review"]
    checked = await expert.ok("GET", f"/assignments/{assignment_id}/proofread")
    assert checked["editable"] is True and checked["version"] == 1
    by_question = items(checked)
    assert list(by_question) == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    # Q1 quotes the citation, so code links it; Q2, Q3 and Q5 name nothing, so the model does.
    [q1] = by_question["Q1"]["lines"]
    assert q1["assigned_by"] == "quote" and q1["targets"] == ["h1"]
    [q2] = by_question["Q2"]["lines"]
    assert q2["assigned_by"] == "llm" and q2["targets"] == ["case"]
    assert len(models.classifier_calls) == 1
    assert "Sentences to file: Q2.1, Q3.1, Q5.1" in models.classifier_calls[0]
    row = await round_of(assignment_id)
    assert row.classifier == settings.classifier_model
    assert row.prompt == "Expert_sentence_targets.v1"
    assert row.submitted_at is None


async def test_the_original_is_kept_next_to_the_proposal():
    _, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    by_question = items(await proofread(expert, assignment_id))
    for question_id, answer in FULL_PAYLOAD["answers"].items():
        assert by_question[question_id]["original"] == answer
        assert by_question[question_id]["final"] == by_question[question_id]["proposed"]


async def test_q4_is_proofread_but_not_linked():
    _, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    q4 = items(await proofread(expert, assignment_id))["Q4"]
    assert q4["linked"] is False and q4["lines"] == []
    assert q4["final"] == Q4_WHY


async def test_answers_that_cite_everything_never_call_the_model(models):
    _, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id, CITED_PAYLOAD)
    view = await proofread(expert, assignment_id)
    assert models.classifier_calls == []
    assert (await round_of(assignment_id)).classifier is None
    lines = [line for item in view["items"] for line in item["lines"]]
    assert {line["assigned_by"] for line in lines} == {"chip"}


async def test_a_model_that_answers_nonsense_links_the_lines_to_the_case(models):
    _, expert, assignment_id = await setup_one()
    models.classifier_reply = "this is not json"
    await answer_and_submit(expert, assignment_id)
    view = await proofread(expert, assignment_id)
    by_question = items(view)
    for question_id in ("Q2", "Q3", "Q5"):
        assert [line["targets"] for line in by_question[question_id]["lines"]] == [["case"]]
    assert len(models.classifier_calls) == 4, "one try and three retries"


async def test_an_unreachable_classifier_fails_the_job_and_an_admin_retry_recovers(models, caplog):
    admin, expert, assignment_id = await setup_one()
    models.down = True
    await answer_and_submit(expert, assignment_id)
    assert await run_jobs() == MAX_ATTEMPTS
    view = await admin.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "processing_failed"
    assert "ConnectionError" in caplog.text
    assert Q5_ANSWER not in caplog.text and OPEN_ANSWERS["Q2"] not in caplog.text

    models.down = False
    await admin.ok("POST", f"/assignments/{assignment_id}/retry")
    await run_jobs()
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "proofread_check"


def typo(text: str, word: str, fix: str, category: str = "TYPOS") -> dict:
    """A LanguageTool match for `word` in `text`."""
    return {
        "offset": text.index(word),
        "length": len(word),
        "replacements": [{"value": fix}],
        "rule": {"id": "RULE", "category": {"id": category}},
    }


async def test_grammar_fixes_are_proposed_and_style_is_left_alone(models):
    _, expert, assignment_id = await setup_one()
    q5 = "A junior clinician would over-read teh desk story as a clear sign"
    models.grammar_matches[q5] = [
        typo(q5, "teh", "the"),
        typo(q5, "clear", "obvious", "STYLE"),
        typo(q5, "sign", "sign.", "PUNCTUATION"),
    ]
    payload = {**FULL_PAYLOAD, "answers": {**FULL_PAYLOAD["answers"], "Q5": q5}}
    await answer_and_submit(expert, assignment_id, payload)
    q5_item = items(await proofread(expert, assignment_id))["Q5"]
    assert q5_item["original"] == q5
    assert (
        q5_item["proposed"] == "A junior clinician would over-read the desk story as a clear sign."
    )
    assert (await round_of(assignment_id)).passes["Q5"]["grammar"] == 2


async def test_a_grammar_checker_that_is_down_leaves_the_text_as_written(models):
    _, expert, assignment_id = await setup_one()
    models.grammar_down = True
    await answer_and_submit(expert, assignment_id)
    view = await proofread(expert, assignment_id)
    assert (await expert.ok("GET", f"/assignments/{assignment_id}"))["state"] == "proofread_check"
    assert items(view)["Q5"]["proposed"] == Q5_ANSWER
    assert view["passes"]["Q5"]["grammar"] == "unavailable"


async def test_unreadable_sentences_are_dropped_and_listed(models):
    _, expert, assignment_id = await setup_one()
    q5 = f"{Q5_ANSWER} afdoafgja qwrtzlk sdfjhsk."
    payload = {**FULL_PAYLOAD, "answers": {**FULL_PAYLOAD["answers"], "Q5": q5}}
    await answer_and_submit(expert, assignment_id, payload)
    q5_item = items(await proofread(expert, assignment_id))["Q5"]
    assert q5_item["proposed"] == Q5_ANSWER
    assert q5_item["dropped"] == ["afdoafgja qwrtzlk sdfjhsk."]


async def test_the_enhancement_is_used_only_when_it_keeps_every_chip(models):
    _, expert, assignment_id = await setup_one()
    answers = {**CITED_PAYLOAD["answers"]}
    models.enhance_reply = {
        answers["Q2"]: "⟦h2⟧ could equally reflect sleep loss after the recent move. "
        "It need not be a trait.",
        answers["Q3"]: "How often does this happen?",  # the chip is gone: refused
    }
    await answer_and_submit(expert, assignment_id, CITED_PAYLOAD)
    by_question = items(await proofread(expert, assignment_id))
    assert by_question["Q2"]["proposed"] == (
        "⟦h2⟧ could equally reflect sleep loss after the recent move.\nIt need not be a trait."
    )
    assert by_question["Q3"]["proposed"] == answers["Q3"]
    passes = (await round_of(assignment_id)).passes
    assert passes["Q2"]["enhanced"] is True and passes["Q3"]["enhanced"] is False
    assert [(line["targets"], line["assigned_by"]) for line in by_question["Q2"]["lines"]] == [
        (["h2"], "chip"),
        (["case"], "llm"),
    ]


async def test_an_enhancement_model_that_is_down_is_skipped(models):
    _, expert, assignment_id = await setup_one()
    models.enhance_down = True
    await answer_and_submit(expert, assignment_id)
    view = await proofread(expert, assignment_id)
    assert view["passes"]["Q5"]["enhanced"] == "unavailable"
    assert items(view)["Q5"]["proposed"] == Q5_ANSWER


# --- the proofread check -------------------------------------------------------------------


async def checkable():
    """An assignment waiting in proofread_check, with default answers (one citation, h1)."""
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    return admin, expert, assignment_id


async def test_editing_a_line_links_it_again_and_keeps_the_others(models):
    _, expert, assignment_id = await checkable()
    q2 = f'"{CUE}" is not the point. {OPEN_ANSWERS["Q2"]}'
    saved = await save_proofread(expert, assignment_id, {"Q2": q2.replace(". ", ".\n")})
    assert saved["version"] == 2
    lines = items(saved)["Q2"]["lines"]
    assert [(line["targets"], line["assigned_by"]) for line in lines] == [
        (["h1"], "quote"),  # new, and quotes the citation
        (["case"], "llm"),  # unchanged: keeps what the model said
    ]
    assert not models.classifier_calls[1:], "saving never calls the model"


async def test_a_new_line_with_nothing_to_go_on_needs_the_author(models):
    _, expert, assignment_id = await checkable()
    q3 = f"{OPEN_ANSWERS['Q3']}\nNothing more to say here really."
    saved = await save_proofread(expert, assignment_id, {"Q3": q3})
    assert [line["targets"] for line in items(saved)["Q3"]["lines"]] == [["case"], []]
    body = await expert.fails(
        "POST", f"/assignments/{assignment_id}/submit-for-review", 422, "links_missing"
    )
    assert body["details"] == {"lines": {"Q3": [1]}}

    saved = await save_proofread(
        expert, assignment_id, {}, {"Q3": {"Nothing more to say here really.": ["h1", "case"]}}
    )
    assert items(saved)["Q3"]["lines"][1] == {
        "text": "Nothing more to say here really.",
        "targets": ["h1", "case"],
        "assigned_by": "expert",
    }
    view = await expert.ok("POST", f"/assignments/{assignment_id}/submit-for-review")
    assert view["state"] == "peer_review"


async def test_the_flags_follow_the_links(models):
    _, expert, assignment_id = await checkable()
    view = await expert.ok("GET", f"/assignments/{assignment_id}/proofread")
    # "rather than" in a line about a citation marked "toward" asks the author to look again.
    assert [(f["kind"], f["highlight"]) for f in view["flags"]] == [("direction", "h1")]
    q1 = items(view)["Q1"]["final"]
    saved = await save_proofread(expert, assignment_id, {}, {"Q1": {q1: ["case"]}})
    assert [(f["kind"], f["highlight"]) for f in saved["flags"]] == [("coverage", "h1")]


async def test_edits_are_checked(models):
    _, expert, assignment_id = await checkable()
    path = f"/assignments/{assignment_id}/proofread"
    for body, status, code in [
        ({"answers": {"Q1": "⟦h9⟧ cites nothing"}}, 422, "unknown_chip"),
        ({"answers": {"Q6": "a rating"}}, 422, "question_not_answered"),
        ({"answers": {}, "overrides": {"Q1": {"x": ["h9"]}}}, 422, "unknown_target"),
        ({"answers": {}, "overrides": {"Q1": {"x": []}}}, 422, "no_target"),
    ]:
        await expert.fails("PUT", path, status, code, json={"version": 1, **body})
    await expert.ok("PUT", path, json={"version": 1, "answers": {}})
    body = await expert.fails(
        "PUT", path, 409, "proofread_conflict", json={"version": 1, "answers": {}}
    )
    assert body["details"] == {"current_version": 2}


async def test_an_emptied_answer_cannot_go_to_review(models):
    _, expert, assignment_id = await checkable()
    await save_proofread(expert, assignment_id, {"Q5": "   "})
    body = await expert.fails(
        "POST", f"/assignments/{assignment_id}/submit-for-review", 422, "empty_answer"
    )
    assert body["details"] == {"question_ids": ["Q5"]}


async def test_only_the_author_edits_and_only_while_checking(models):
    admin, expert, assignment_id = await checkable()
    path = f"/assignments/{assignment_id}/proofread"
    await admin.fails("PUT", path, 403, "forbidden", json={"version": 1, "answers": {}})
    assert (await admin.ok("GET", path))["editable"] is False

    other = await expert_api("other@example.com")
    await other.fails("GET", path, 404, "not_found")

    await expert.ok("POST", f"/assignments/{assignment_id}/submit-for-review")
    body = await expert.fails("PUT", path, 409, "not_editable", json={"version": 1, "answers": {}})
    assert body["details"] == {"state": "peer_review"}
    view = await expert.ok("GET", path)
    assert view["editable"] is False and view["submitted_at"]


# --- review routing ------------------------------------------------------------------------


async def test_answers_go_to_every_colleague_who_can_read_them():
    admin, e1, e2, first, second = await two_experts()
    for assignment_id in (first, second):
        assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "peer_review"

    def summary(queue):
        return {q["assignment_id"]: (q["relation"], q["opened"], q["answer_count"]) for q in queue}

    assert summary(await e1.ok("GET", "/reviews")) == {
        first: ("author", True, 5),
        second: ("reviewer", False, 5),
    }
    assert summary(await e2.ok("GET", "/reviews")) == {
        first: ("reviewer", False, 5),
        second: ("author", True, 5),
    }

    await e1.ok("POST", f"/assignments/{second}/review/open", 204)
    view = await e1.ok("GET", f"/assignments/{second}/answers")
    q1 = view["answers"][0]
    assert q1["question_id"] == "Q1" and q1["lines"][0]["targets"] == ["h1"]
    assert q1["comments"] == [] and q1["decision"] is None
    assert view["highlights"][0]["text"] == CUE
    # A peer reads the edited answers, not the proofread check or the raw answers.
    await e1.fails("GET", f"/assignments/{second}/proofread", 404, "not_found")
    await e1.fails("GET", f"/assignments/{second}/findings", 404, "not_found")
    await e1.fails("GET", f"/assignments/{second}/submission", 404, "not_found")
    async with session_factory()() as db:
        [reader] = list(await db.scalars(select(ReviewParticipant)))
    assert str(reader.expert_id) == e1.user_id and str(reader.assignment_id) == second


async def test_a_colleague_who_has_not_answered_yet_cannot_read_but_a_new_one_can():
    admin = await admin_api()
    e1, e2, e3 = [await expert_api(f"e{i}@example.com") for i in (1, 2, 3)]
    version = await published_version(admin)
    first, second, third = await assign(admin, version, e1, e2, e3)
    await answer_and_submit(e1, first)
    await to_review(e1, first)
    assert await e3.ok("GET", "/reviews") == [], "e3 still has to form their own reading"
    await e3.fails("GET", f"/assignments/{first}", 404, "not_found")

    await answer_and_submit(e3, third)
    assert await e3.ok("GET", "/reviews") == [], "e3 can still edit their answers"
    await to_review(e3, third)
    assert first in [q["assignment_id"] for q in await e3.ok("GET", "/reviews")]
    # e2 has not started, and e1's review was already open: someone new joins it all the same.
    late = await expert_api("late@example.com")
    assert {q["assignment_id"] for q in await late.ok("GET", "/reviews")} == {first, third}
    await e2.fails("GET", f"/assignments/{first}", 404, "not_found")


async def test_a_proofread_that_failed_is_not_a_review(models):
    admin, expert, assignment_id = await setup_one()
    models.down = True
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "processing_failed"
    late = await expert_api("late@example.com")
    assert await late.ok("GET", "/reviews") == []
    assert await admin.ok("GET", "/reviews") == []


async def test_the_admin_closes_a_review_whatever_the_reviewers_think():
    admin, e1, e2, first, second = await two_experts()
    await e1.ok("POST", f"/assignments/{second}/review/open", 204)
    await e1.ok(
        "PUT",
        f"/assignments/{second}/answers/Q1/vote",
        json={"vote": "disapprove", "review_round": 1},
    )
    view = await admin.ok("GET", f"/assignments/{second}")
    assert "decide_answers" in view["allowed_actions"]
    queue = await admin.ok("GET", "/reviews", params={"status": "open"})
    assert second in [q["assignment_id"] for q in queue]

    await decide_all(admin, second)
    assert (await admin.ok("GET", f"/assignments/{second}"))["state"] == "processing"
    assert await e1.ok("GET", "/reviews", params={"status": "open"}) != [], "his own is still open"
    assert [
        q["assignment_id"] for q in await e1.ok("GET", "/reviews", params={"status": "closed"})
    ] == [second]
    await e1.fails(
        "POST",
        f"/assignments/{second}/answer-decisions",
        409,
        "illegal_transition",
        json={"decisions": []},
    )


async def test_the_admin_rejecting_everything_during_review_ends_it():
    admin, e1, e2, first, second = await two_experts()
    await decide_all(admin, second, "reject")
    assert (await admin.ok("GET", f"/assignments/{second}"))["state"] == "rejected"


# --- cutting the approved answers into units -----------------------------------------------


async def approved(models=None, decide=None):
    """One expert, every answer approved, cut into units but not ingested yet."""
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await to_review(expert, assignment_id)
    await (decide or decide_all)(admin, assignment_id)
    from app.jobs.worker import run_once

    await run_once()  # the process job only
    return admin, expert, assignment_id


async def test_units_are_cut_by_citation_from_the_approved_answers():
    admin, _, assignment_id = await approved()
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "ingesting"
    async with session_factory()() as db:
        units = list(await db.scalars(select(KnowledgeUnit).order_by(KnowledgeUnit.ordinal)))
    assert [(u.ordinal, u.kind, u.direction) for u in units] == [
        (1, "fragment", "toward"),
        (2, "case", None),
    ]
    fragment, case = units
    assert fragment.patient_words == CUE and case.patient_words is None
    assert fragment.text.startswith("Q1: ") and "avoidance" in fragment.text
    assert case.text.splitlines()[0].startswith("Q2: ") and "Q5: " in case.text
    assert all(u.status == "approved" for u in units), "approved with their answers"
    record = (await findings_of(assignment_id)).record
    assert record["session_id"] == assignment_id and "example.com" not in str(record)


async def test_what_is_cut_is_what_will_be_embedded():
    await approved()
    async with session_factory()() as db:
        rows = list(await db.scalars(select(KnowledgeUnit).order_by(KnowledgeUnit.ordinal)))
    fragment = rows[0]
    assert fragment.embed_text is not None and fragment.embed_text_combined is not None
    assert fragment.embed_text.splitlines()[0].startswith("Clinician on an adult's journal entry")
    assert fragment.embed_text.endswith(fragment.text)
    assert fragment.embed_text_combined.splitlines()[1] == f'Patient: "{CUE}"'
    assert fragment.content_hash == unit_content_hash(
        fragment.embed_text, fragment.embed_text_combined
    )
    assert fragment.sentence_ids == ["Q1.1"] and fragment.highlight_id == "h1"


async def test_each_line_is_cut_into_sentences_that_keep_its_links(models):
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    two = "The desk story is avoidance of the task. It is also a classic sign of it."
    await save_proofread(expert, assignment_id, {"Q3": two}, {"Q3": {two: ["h1"]}})
    await expert.ok("POST", f"/assignments/{assignment_id}/submit-for-review")
    await decide_all(admin, assignment_id)
    await run_jobs()
    record = (await findings_of(assignment_id)).record
    q3 = [s for s in record["sentences"] if s["question_id"] == "Q3"]
    assert [(s["id"], s["targets"], s["assigned_by"]) for s in q3] == [
        ("Q3.1", ["h1"], "expert"),
        ("Q3.2", ["h1"], "expert"),
    ]


# --- ingestion into the RAG tables ---------------------------------------------------------


async def chips(query: str, **params):
    async with session_factory()() as db:
        return (await db.execute(text(query), params)).all()


async def count(table: str) -> int:
    return (await chips(f"SELECT count(*) FROM chips.{table}"))[0][0]


async def ingested_single(models, decide=None):
    """One expert, one fully approved assignment, ingested."""
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await to_review(expert, assignment_id)
    await (decide or decide_all)(admin, assignment_id)
    await run_jobs()
    return admin, expert, assignment_id


async def units_of(assignment_id: str) -> list[KnowledgeUnit]:
    async with session_factory()() as db:
        return list(
            await db.scalars(
                select(KnowledgeUnit)
                .where(KnowledgeUnit.assignment_id == UUID(assignment_id))
                .order_by(KnowledgeUnit.ordinal)
            )
        )


async def test_approved_units_land_in_chips_with_their_embeddings(models):
    admin, expert, assignment_id = await ingested_single(models)
    view = await admin.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "ingested"
    assert {u.status for u in await units_of(assignment_id)} == {"ingested"}

    session = assignment_id
    [vignette_code] = [v["code"] for v in await admin.ok("GET", "/vignettes")]
    assert await chips("SELECT id, is_synthetic FROM chips.experts") == [(expert.user_id, False)]
    assert (await chips("SELECT id, version, tier FROM chips.vignettes"))[0][2] == "app"
    [(sid, expert_id)] = await chips("SELECT id, expert_id FROM chips.elicitation_sessions")
    assert (sid, expert_id) == (session, expert.user_id)

    rows = await chips(
        "SELECT id, kind, direction, highlight_id, embed_text, embedding IS NOT NULL, "
        "sparse IS NOT NULL, embedding_combined IS NOT NULL, sparse_combined IS NOT NULL "
        "FROM chips.finding_units ORDER BY id"
    )
    ids = [r[0] for r in rows]
    assert ids == sorted([f"{session}-{vignette_code}-case", f"{session}-{vignette_code}-h1"])
    fragment = next(r for r in rows if r[1] == "fragment")
    assert fragment[2:4] == ("toward", f"{session}-{vignette_code}-h1")
    assert all(all(r[5:]) for r in rows), "dense and sparse vectors for both texts"
    assert await count("highlights") == 1 and await count("cue_keys") == 1
    assert await count("answer_sentences") == 4
    assert await count("finding_unit_sentences") == 4
    assert {r[0] for r in await chips("SELECT role FROM chips.unit_cues")} == {"cue"}
    assert (await chips("SELECT count(*) FROM chips.cue_keys WHERE sparse IS NULL"))[0][0] == 0


async def test_a_unit_searched_with_its_own_text_comes_back_first(models):
    await ingested_single(models)
    for column, vector_column in (
        ("embed_text", "embedding"),
        ("embed_text_combined", "embedding_combined"),
    ):
        rows = await chips(f"SELECT id, {column} FROM chips.finding_units ORDER BY id")
        assert len(rows) == 2, "nothing to search yet"
        for unit_id, embed_text in rows:
            vector = "[" + ",".join(map(str, FakeModels.vector(embed_text))) + "]"
            [(nearest,)] = await chips(
                f"SELECT id FROM chips.finding_units "
                f"ORDER BY {vector_column} <=> CAST(CAST(:v AS text) AS vector) LIMIT 1",
                v=vector,
            )
            assert nearest == unit_id


async def test_the_stored_text_is_exactly_what_the_reviewers_approved(models):
    admin, _, assignment_id = await ingested_single(models)
    async with session_factory()() as db:
        reviewed = {
            u.highlight_id or "case": (u.embed_text, u.embed_text_combined)
            for u in await db.scalars(select(KnowledgeUnit))
        }
    rows = await chips(
        "SELECT highlight_id, kind, embed_text, embed_text_combined FROM chips.finding_units"
    )
    stored = {(r[0].rsplit("-", 1)[-1] if r[0] else "case"): (r[2], r[3]) for r in rows}
    assert stored == reviewed


async def approve_only_q1(admin, assignment_id):
    answers = await admin.ok("GET", f"/assignments/{assignment_id}/answers")
    await admin.ok(
        "POST",
        f"/assignments/{assignment_id}/answer-decisions",
        json={
            "decisions": [
                {
                    "question_id": a["question_id"],
                    "decision": "approve" if a["question_id"] == "Q1" else "reject",
                }
                for a in answers["answers"]
            ]
        },
    )


async def test_rejected_answers_never_reach_the_rag_tables(models):
    admin, _, assignment_id = await ingested_single(models, decide=approve_only_q1)
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "ingested"
    assert await count("finding_units") == 1 and await count("answer_sentences") == 1

    parts = []
    for table in ("elicitation_sessions", "finding_units", "review_events", "answer_sentences"):
        parts += [row[0] for row in await chips(f"SELECT t::text FROM chips.{table} t")]
    everything = " ".join(parts)
    assert "avoidance" in everything, "the approved answer's own words are stored"
    for rejected in (OPEN_ANSWERS["Q2"], OPEN_ANSWERS["Q3"], Q5_ANSWER):
        assert rejected not in everything
        assert rejected.split(".")[0][:30] not in everything
    assert "Q2." not in everything and "Q5." not in everything
    assert [u.kind for u in await units_of(assignment_id)] == ["fragment"]


async def test_approving_only_the_q4_why_leaves_nothing_to_ingest(models):
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await to_review(expert, assignment_id)
    await admin.ok(
        "POST",
        f"/assignments/{assignment_id}/answer-decisions",
        json={
            "decisions": [
                {"question_id": q, "decision": "approve" if q == "Q4" else "reject"}
                for q in ("Q1", "Q2", "Q3", "Q4", "Q5")
            ]
        },
    )
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "rejected"


async def test_events_hold_ids_and_kinds_never_what_the_expert_wrote(models):
    await ingested_single(models)
    events = await chips("SELECT kind, payload::text FROM chips.review_events ORDER BY kind")
    assert [e[0] for e in events] == ["flag_shown"]
    blob = " ".join(e[1] for e in events)
    assert "avoidance" not in blob and "sleep loss" not in blob and "reorganised" not in blob
    [(direction,)] = await chips("SELECT direction FROM chips.highlights")
    assert direction == "toward"


async def test_a_failure_while_ingesting_leaves_chips_untouched(models, monkeypatch):
    from app.knowledge import ingest

    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await to_review(expert, assignment_id)

    async def boom(db):
        raise RuntimeError("fails after the rows were written")

    monkeypatch.setattr(ingest, "refresh_sparse", boom)
    await decide_all(admin, assignment_id)
    await run_jobs()
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "ingestion_failed"
    for table in ("experts", "elicitation_sessions", "finding_units", "cue_keys", "highlights"):
        assert await count(table) == 0, table
    statuses = {u.status for u in await units_of(assignment_id)}
    assert statuses == {"approved"}, "not marked ingested"

    monkeypatch.undo()
    await admin.ok("POST", f"/assignments/{assignment_id}/retry")
    await run_jobs()
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "ingested"
    assert await count("finding_units") == 2 and await count("elicitation_sessions") == 1


async def test_ingesting_the_same_answers_twice_leaves_one_copy(models):
    from app.jobs import handlers

    await ingested_single(models)
    before = [
        await count(t) for t in ("finding_units", "highlights", "answer_sentences", "cue_keys")
    ]
    async with session_factory()() as db:
        assignment = await db.scalar(select(Assignment))
    assert assignment is not None
    prepared = await handlers.prepare_ingest(assignment.id)
    async with session_factory()() as db:
        locked = await lock_assignment(db, assignment.id)
        await handlers.ingest(db, locked, prepared)
        await db.commit()
    after = [
        await count(t) for t in ("finding_units", "highlights", "answer_sentences", "cue_keys")
    ]
    assert before == after == [2, 1, 4, 1]


async def test_colleagues_answering_the_same_vignette_share_its_cue_keys(models):
    admin, e1, e2, first, second = await two_experts()
    await decide_all(admin, first)
    await decide_all(admin, second)
    await run_jobs()
    assert await count("experts") == 2 and await count("elicitation_sessions") == 2
    assert await count("vignettes") == 1
    assert await count("finding_units") == 4
    assert await count("cue_keys") == 1, "the same passage of the same vignette is one cue key"
    assert await count("highlights") == 2


async def test_synthetic_answers_are_refused_in_production_before_anything_is_embedded(
    models, monkeypatch
):
    admin = await admin_api()
    expert = await expert_api("s@example.com", is_synthetic=True)
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, assignment_id)
    await to_review(expert, assignment_id)
    await decide_all(admin, assignment_id)
    monkeypatch.setattr(settings, "environment", "production")
    assert await run_jobs() == 2, "the units are cut, then ingestion refuses at once"
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "ingestion_failed"
    assert models.embedded == [] and await count("finding_units") == 0


async def test_units_from_before_the_pipeline_cannot_be_ingested(models):
    admin, _, assignment_id = await approved()
    async with session_factory()() as db:
        await db.execute(update(KnowledgeUnit).values(embed_text=None, embed_text_combined=None))
        await db.commit()
    assert await run_jobs() == 1, "retrying can't help"
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "ingestion_failed"
    async with session_factory()() as db:
        job = await db.scalar(select(Job).where(Job.kind == JobKind.INGEST))
    assert job is not None and job.last_error == "UnitsNotEmbeddable"


async def test_cutting_units_with_nothing_proofread_fails_at_once():
    """An assignment from before the migration, say, that reaches processing with no round."""
    admin, _, assignment_id = await setup_one()
    async with session_factory()() as db:
        await db.execute(
            update(Assignment)
            .where(Assignment.id == UUID(assignment_id))
            .values(state=State.PROCESSING)
        )
        db.add(Job(kind=JobKind.PROCESS, assignment_id=UUID(assignment_id)))
        await db.commit()
    assert await run_jobs() == 1, "retrying can't help"
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "processing_failed"
    async with session_factory()() as db:
        job = await db.scalar(select(Job).where(Job.kind == JobKind.PROCESS))
    assert job is not None and job.last_error == "NoFindings"
