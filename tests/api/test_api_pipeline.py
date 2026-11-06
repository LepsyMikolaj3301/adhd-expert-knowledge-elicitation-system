"""The answer pipeline: processing, the expert check, building units, review routing, ingestion.

Ollama is replaced by `models` (tests/api/conftest.py): a classifier that files everything under
`case` unless told otherwise, and deterministic embeddings.
"""

from typing import Any
from uuid import UUID

from api_helpers import (
    CONFOUNDER,
    CUE,
    FULL_PAYLOAD,
    GATE_ANSWERS,
    Q4_WHY,
    Q5_ANSWER,
    admin_api,
    answer_and_submit,
    assign,
    decide_all,
    expert_api,
    highlight,
    published_version,
    run_jobs,
    save,
    to_units,
    two_experts,
)
from conftest import FakeModels
from sqlalchemy import delete, select, text, update

from app.assignments.models import Assignment
from app.assignments.state_machine import lock_assignment
from app.core.db import session_factory
from app.jobs.handlers import unit_content_hash
from app.jobs.models import Job, JobKind
from app.jobs.queue import MAX_ATTEMPTS
from app.knowledge.models import AnswerFindings, KnowledgeUnit
from app.reviews.models import ReviewRequest
from app.settings import settings

# Every open answer cites a highlight, so the classifier has nothing to do.
CITED_GATE = {
    "Q1": (
        "⟦h1⟧ reads as avoidance of the task rather than ordinary tidiness, "
        "and the exact wording suggests it quite clearly."
    ),
    "Q2": "⟦h2⟧ could equally be sleep loss after the recent move, not a trait at all.",
    "Q3": "⟦h1⟧ How often does this happen, and what was the baseline before the move?",
}
CITED_PAYLOAD: dict[str, Any] = {
    "answers": {
        **CITED_GATE,
        "Q4": Q4_WHY,
        "Q5": "A junior clinician would over-read ⟦h1⟧ as a clear sign of a lasting trait.",
    },
    "highlights": [highlight(1), highlight(2, CONFOUNDER, "away")],
    "q4": FULL_PAYLOAD["q4"],
    "rating": 2,
}


async def submit_with(expert, assignment_id: str, gate: dict, payload: dict) -> None:
    """Like answer_and_submit, for answers whose gate part needs citations."""
    await expert.ok("POST", f"/assignments/{assignment_id}/start")
    await save(expert, assignment_id, {"answers": gate, "highlights": payload["highlights"]})
    await expert.ok("POST", f"/assignments/{assignment_id}/pass-gate")
    await save(expert, assignment_id, payload)
    await expert.ok("POST", f"/assignments/{assignment_id}/submit")


async def findings_of(assignment_id: str) -> AnswerFindings:
    async with session_factory()() as db:
        row = await db.get(AnswerFindings, UUID(assignment_id))
    assert row is not None, "processing left no findings"
    return row


async def setup_one(models=None):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    [assignment_id] = await assign(admin, await published_version(admin), expert)
    return admin, expert, assignment_id


# --- processing ----------------------------------------------------------------------------


async def test_processing_files_the_sentences_and_asks_the_model_only_about_the_rest(models):
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    assert await run_jobs() == 1

    view = await expert.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "expert_check"
    row = await findings_of(assignment_id)
    sentences = {s["id"]: s for s in row.record["sentences"]}
    # Q1 quotes the citation, so code files it; Q2, Q3 and Q5 name nothing, so the model does.
    assert sentences["Q1.1"]["assigned_by"] == "quote" and sentences["Q1.1"]["targets"] == ["h1"]
    assert sentences["Q2.1"]["assigned_by"] == "llm" and sentences["Q2.1"]["targets"] == ["case"]
    assert len(models.classifier_calls) == 1
    assert "Sentences to file: Q2.1, Q3.1, Q5.1" in models.classifier_calls[0]
    assert row.classifier == settings.classifier_model
    assert row.prompt == "Expert_sentence_targets.v1"
    assert row.check_outcome is None and row.version == 1


async def test_q4_is_not_filed():
    _, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    row = await findings_of(assignment_id)
    assert {s["question_id"] for s in row.record["sentences"]} == {"Q1", "Q2", "Q3", "Q5"}


async def test_answers_that_cite_everything_never_call_the_model(models):
    _, expert, assignment_id = await setup_one()
    await submit_with(expert, assignment_id, CITED_GATE, CITED_PAYLOAD)
    await run_jobs()
    assert models.classifier_calls == []
    row = await findings_of(assignment_id)
    assert row.classifier is None
    assert {s["assigned_by"] for s in row.record["sentences"]} == {"chip"}


async def test_a_model_that_answers_nonsense_files_the_sentences_under_case(models):
    admin, expert, assignment_id = await setup_one()
    models.classifier_reply = "this is not json"
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    assert (await expert.ok("GET", f"/assignments/{assignment_id}"))["state"] == "expert_check"
    row = await findings_of(assignment_id)
    assert row.record["fallback"] == ["Q2.1", "Q3.1", "Q5.1"]
    assert {
        s["targets"][0] for s in row.record["sentences"] if s["id"] in row.record["fallback"]
    } == {"case"}
    assert len(models.classifier_calls) == 4, "one try and three retries"


async def test_an_unreachable_model_fails_the_job_and_an_admin_retry_recovers(models, caplog):
    admin, expert, assignment_id = await setup_one()
    models.down = True
    await answer_and_submit(expert, assignment_id)
    assert await run_jobs() == MAX_ATTEMPTS
    view = await admin.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "processing_failed"
    assert "ConnectionError" in caplog.text
    assert Q5_ANSWER not in caplog.text and GATE_ANSWERS["Q2"] not in caplog.text

    models.down = False
    await admin.ok("POST", f"/assignments/{assignment_id}/retry")
    await run_jobs()
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "expert_check"
    assert (await findings_of(assignment_id)).record["fallback"] == []


async def test_the_findings_say_whose_they_are_without_naming_anyone():
    _, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    record = (await findings_of(assignment_id)).record
    assert record["session_id"] == assignment_id
    assert record["expert_id"] == expert.user_id
    assert "example.com" not in str(record)
    assert CUE in record["highlights"][0]["text"]


# --- the expert check ----------------------------------------------------------------------


async def checkable():
    """An assignment waiting in expert_check, with default answers (one citation, h1)."""
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    return admin, expert, assignment_id


async def test_the_expert_sees_the_filing_without_raw_chip_tokens():
    _, expert, assignment_id = await checkable()
    view = await expert.ok("GET", f"/assignments/{assignment_id}/findings")
    assert view["version"] == 1 and view["editable"] is True and view["check_outcome"] is None
    assert [h["id"] for h in view["highlights"]] == ["h1"]
    assert view["highlights"][0] | {"direction": "toward"} == view["highlights"][0]
    by_id = {s["id"]: s for s in view["sentences"]}
    assert set(by_id) == {"Q1.1", "Q2.1", "Q3.1", "Q5.1"}
    assert by_id["Q1.1"]["targets"] == ["h1"] and by_id["Q1.1"]["assigned_by"] == "quote"
    assert by_id["Q2.1"]["targets"] == ["case"] and by_id["Q2.1"]["assigned_by"] == "llm"
    assert all("⟦" not in s["text"] for s in view["sentences"])
    # "rather than" in a sentence about a citation marked "toward" asks the expert to confirm it.
    assert [(f["kind"], f["highlight"]) for f in view["flags"]] == [("direction", "h1")]
    actions = (await expert.ok("GET", f"/assignments/{assignment_id}"))["allowed_actions"]
    assert actions == ["complete_expert_check", "correct_findings", "skip_expert_check"]


async def test_correcting_a_filing_moves_sentences_and_changes_a_direction():
    admin, expert, assignment_id = await checkable()
    saved = await expert.ok(
        "PUT",
        f"/assignments/{assignment_id}/findings",
        json={"version": 1, "sentences": {"Q2.1": ["h1", "case"]}, "directions": {"h1": "unclear"}},
    )
    assert saved["version"] == 2
    by_id = {s["id"]: s for s in saved["sentences"]}
    assert by_id["Q2.1"]["targets"] == ["h1", "case"] and by_id["Q2.1"]["assigned_by"] == "expert"
    assert by_id["Q3.1"]["assigned_by"] == "llm", (
        "sentences that were not touched stay as they were"
    )
    assert saved["highlights"][0]["direction"] == "unclear"
    assert saved["flags"] == [], "no longer toward, so the mismatch is gone"

    record = (await findings_of(assignment_id)).record
    assert [c["kind"] for c in record["corrections"]] == ["sentence_moved", "toggle_changed"]
    assert record["highlights"][0]["direction_changed_after_flag"] is True
    # The units follow the correction: Q2.1 is now in the fragment unit of h1 as well.
    fragment = next(u for u in record["units"] if u["highlight"] == "h1")
    assert "Q2.1" in fragment["sentences"]
    # The log has ids and kinds, never what the expert wrote.
    assert "sleep loss" not in str(record["corrections"])

    events = await admin.ok("GET", f"/assignments/{assignment_id}/events")
    corrected = [e for e in events if e["action"] == "findings_corrected"]
    assert [e["meta"] for e in corrected] == [{"version": 2, "sentences": 1, "directions": 1}]


async def test_a_correction_that_changes_nothing_is_not_a_new_version():
    _, expert, assignment_id = await checkable()
    same = await expert.ok(
        "PUT",
        f"/assignments/{assignment_id}/findings",
        json={"version": 1, "sentences": {"Q2.1": ["case"]}, "directions": {"h1": "toward"}},
    )
    assert same["version"] == 1


async def test_a_stale_tab_cannot_overwrite_a_newer_correction():
    _, expert, assignment_id = await checkable()
    path = f"/assignments/{assignment_id}/findings"
    await expert.ok("PUT", path, json={"version": 1, "sentences": {"Q2.1": ["h1"]}})
    body = await expert.fails(
        "PUT", path, 409, "findings_conflict", json={"version": 1, "sentences": {"Q3.1": ["h1"]}}
    )
    assert body["details"] == {"current_version": 2}


async def test_corrections_must_name_real_sentences_and_targets():
    _, expert, assignment_id = await checkable()
    path = f"/assignments/{assignment_id}/findings"
    for correction, code in [
        ({"sentences": {"Q9.9": ["case"]}}, "unknown_sentence"),
        ({"sentences": {"Q2.1": ["h9"]}}, "unknown_target"),
        ({"sentences": {"Q2.1": []}}, "no_target"),
        ({"directions": {"h9": "away"}}, "unknown_highlight"),
    ]:
        await expert.fails("PUT", path, 422, code, json={"version": 1, **correction})
    assert (await findings_of(assignment_id)).version == 1


async def test_only_the_author_corrects_and_only_while_the_check_is_open():
    admin, expert, assignment_id = await checkable()
    path = f"/assignments/{assignment_id}/findings"
    await admin.fails("PUT", path, 403, "forbidden", json={"version": 1})
    assert (await admin.ok("GET", path))["editable"] is False

    other = await expert_api("other@example.com")
    await other.fails("GET", path, 404, "not_found")
    await other.fails("PUT", path, 404, "not_found", json={"version": 1})

    await expert.ok("POST", f"/assignments/{assignment_id}/expert-check/complete")
    body = await expert.fails("PUT", path, 409, "not_editable", json={"version": 1})
    assert body["details"] == {"state": "building_units"}
    assert (await expert.ok("GET", path))["editable"] is False


async def test_completing_or_skipping_the_check_is_remembered():
    admin, expert, done = await checkable()
    await expert.ok("POST", f"/assignments/{done}/expert-check/complete")
    assert (await findings_of(done)).check_outcome == "completed"

    [skipped] = await assign(admin, await published_version(admin), expert)
    await answer_and_submit(expert, skipped)
    await run_jobs()
    await admin.ok("POST", f"/assignments/{skipped}/expert-check/skip")
    assert (await findings_of(skipped)).check_outcome == "skipped"


# --- building units and routing them to review --------------------------------------------


async def test_units_are_cut_by_citation_and_keep_the_experts_own_sentences():
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await to_units(admin, expert, assignment_id)
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "admin_review"

    units = await admin.ok("GET", f"/assignments/{assignment_id}/units")
    assert [(u["ordinal"], u["kind"], u["direction"]) for u in units] == [
        (1, "fragment", "toward"),
        (2, "case", None),
    ]
    fragment, case = units
    assert fragment["patient_words"] == CUE and case["patient_words"] is None
    assert fragment["text"].startswith("Q1: ") and "avoidance" in fragment["text"]
    assert case["text"].splitlines()[0].startswith("Q2: ") and "Q5: " in case["text"]
    assert all(u["status"] == "pending" for u in units)

    expert_view = await expert.ok("GET", f"/assignments/{assignment_id}/units")
    assert [u["text"] for u in expert_view] == [u["text"] for u in units]


async def test_what_is_reviewed_is_what_will_be_embedded():
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await to_units(admin, expert, assignment_id)
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


async def test_building_units_without_findings_fails_at_once(caplog):
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    async with session_factory()() as db:
        await db.execute(delete(AnswerFindings))
        await db.commit()
    await expert.ok("POST", f"/assignments/{assignment_id}/expert-check/complete")
    assert await run_jobs() == 1, "retrying can't help"
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "processing_failed"
    async with session_factory()() as db:
        job = await db.scalar(select(Job).where(Job.kind == JobKind.BUILD_UNITS))
    assert job is not None and job.last_error == "NoFindings"


async def test_units_go_to_every_colleague_who_can_review_them():
    admin, e1, e2, first, second = await two_experts()
    assert (await admin.ok("GET", f"/assignments/{first}"))["state"] == "admin_review"
    assert (await admin.ok("GET", f"/assignments/{second}"))["state"] == "peer_review"

    queue = await e1.ok("GET", "/review-requests")
    assert [(q["assignment_id"], q["stage"], q["unit_count"]) for q in queue] == [
        (second, "peer", 2)
    ]
    assert await e2.ok("GET", "/review-requests") == [], "nobody reviews their own units"

    async with session_factory()() as db:
        [request] = list(await db.scalars(select(ReviewRequest)))
    assert str(request.reviewer_id) == e1.user_id and request.requested_by is None
    assert request.completed_at is None

    units = await e1.ok("GET", f"/assignments/{second}/units")
    assert {u["audience"] for u in units} == {"peer"}
    assert units[0]["kind"] == "fragment" and units[0]["patient_words"] == CUE
    assert all("status" not in u and u["my_decision"] is None for u in units)
    # A peer reads units, not the filing or the raw answers.
    await e1.fails("GET", f"/assignments/{second}/findings", 404, "not_found")
    await e1.fails("GET", f"/assignments/{second}/submission", 404, "not_found")


async def test_a_colleague_who_has_not_answered_yet_is_not_asked():
    admin = await admin_api()
    e1, e2, e3 = [await expert_api(f"e{i}@example.com") for i in (1, 2, 3)]
    version = await published_version(admin)
    first, second, _third = await assign(admin, version, e1, e2, e3)
    await answer_and_submit(e1, first)
    await to_units(admin, e1, first, skip=True)
    await answer_and_submit(e2, second)
    await to_units(admin, e2, second)
    async with session_factory()() as db:
        reviewers = {str(r) for r in await db.scalars(select(ReviewRequest.reviewer_id))}
    assert reviewers == {e1.user_id}, "e3 still has to form their own reading"


async def test_one_peer_approval_ingests_without_the_admin():
    admin, e1, e2, first, second = await two_experts()
    await decide_all(e1, second)
    assert (await admin.ok("GET", f"/assignments/{second}"))["state"] == "ingesting"


async def test_the_admin_can_decide_while_peers_are_still_looking():
    admin, e1, e2, first, second = await two_experts()
    queue = await admin.ok("GET", "/review-requests")
    assert second in [q["assignment_id"] for q in queue], "admins see units in peer review too"
    view = await admin.ok("GET", f"/assignments/{second}")
    assert "decide_units" in view["allowed_actions"]

    await decide_all(admin, second)
    assert (await admin.ok("GET", f"/assignments/{second}"))["state"] == "ingesting"
    assert await e1.ok("GET", "/review-requests") == [], "the request is closed"
    await e1.fails(
        "POST",
        f"/assignments/{second}/unit-decisions",
        409,
        "illegal_transition",
        json={"decisions": []},
    )


async def test_the_admin_rejecting_everything_during_peer_review_ends_it():
    admin, e1, e2, first, second = await two_experts()
    await decide_all(admin, second, "reject")
    assert (await admin.ok("GET", f"/assignments/{second}"))["state"] == "rejected"


async def test_a_peer_rejection_hands_the_decision_to_the_admin():
    admin, e1, e2, first, second = await two_experts()
    await decide_all(e1, second, "reject")
    assert (await admin.ok("GET", f"/assignments/{second}"))["state"] == "admin_review"
    # Peers were used up, so the admin can't ask again: they decide.
    view = await admin.ok("GET", f"/assignments/{second}")
    assert "request_peers" not in view["allowed_actions"]


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
    await to_units(admin, expert, assignment_id, skip=True)
    await (decide or decide_all)(admin, assignment_id)
    await run_jobs()
    return admin, expert, assignment_id


async def test_approved_units_land_in_chips_with_their_embeddings(models):
    admin, expert, assignment_id = await ingested_single(models)
    view = await admin.ok("GET", f"/assignments/{assignment_id}")
    assert view["state"] == "ingested"
    units = await admin.ok("GET", f"/assignments/{assignment_id}/units")
    assert {u["status"] for u in units} == {"ingested"}

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


async def reject_the_case_unit(admin, assignment_id):
    units = await admin.ok("GET", f"/assignments/{assignment_id}/units")
    await admin.ok(
        "POST",
        f"/assignments/{assignment_id}/unit-decisions",
        json={
            "decisions": [
                {"unit_id": u["id"], "decision": "reject" if u["kind"] == "case" else "approve"}
                for u in units
            ]
        },
    )


async def test_rejected_units_never_reach_the_rag_tables(models):
    admin, _, assignment_id = await ingested_single(models, decide=reject_the_case_unit)
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "ingested"
    assert await count("finding_units") == 1 and await count("answer_sentences") == 1

    parts = []
    for table in ("elicitation_sessions", "finding_units", "review_events", "answer_sentences"):
        parts += [row[0] for row in await chips(f"SELECT t::text FROM chips.{table} t")]
    everything = " ".join(parts)
    assert "avoidance" in everything, "the approved unit's own words are stored"
    # The rejected unit held exactly these answers; the approved one cites only Q1.
    for rejected in (GATE_ANSWERS["Q2"], GATE_ANSWERS["Q3"], Q5_ANSWER):
        assert rejected not in everything
        assert rejected.split(".")[0][:30] not in everything
    assert "Q2." not in everything and "Q5." not in everything
    units = await admin.ok("GET", f"/assignments/{assignment_id}/units")
    assert sorted(u["status"] for u in units) == ["ingested", "rejected"]


async def test_events_hold_ids_and_kinds_never_what_the_expert_wrote(models):
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await run_jobs()
    await expert.ok(
        "PUT",
        f"/assignments/{assignment_id}/findings",
        json={"version": 1, "sentences": {"Q2.1": ["h1"]}, "directions": {"h1": "unclear"}},
    )
    await expert.ok("POST", f"/assignments/{assignment_id}/expert-check/complete")
    await run_jobs()
    await decide_all(admin, assignment_id)
    await run_jobs()

    events = await chips("SELECT kind, payload::text FROM chips.review_events ORDER BY kind")
    kinds = [e[0] for e in events]
    assert "flag_shown" in kinds and "sentence_moved" in kinds and "toggle_changed" in kinds
    blob = " ".join(e[1] for e in events)
    assert "avoidance" not in blob and "sleep loss" not in blob and "reorganised" not in blob
    [(changed,)] = await chips("SELECT direction_changed_after_flag FROM chips.highlights")
    assert changed is True
    [(direction,)] = await chips("SELECT direction FROM chips.highlights")
    assert direction == "unclear"


async def test_a_failure_while_ingesting_leaves_chips_untouched(models, monkeypatch):
    from app.knowledge import ingest

    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await to_units(admin, expert, assignment_id, skip=True)

    async def boom(db):
        raise RuntimeError("fails after the rows were written")

    monkeypatch.setattr(ingest, "refresh_sparse", boom)
    await decide_all(admin, assignment_id)
    await run_jobs()
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "ingestion_failed"
    for table in ("experts", "elicitation_sessions", "finding_units", "cue_keys", "highlights"):
        assert await count(table) == 0, table
    units = await admin.ok("GET", f"/assignments/{assignment_id}/units")
    assert {u["status"] for u in units} == {"approved"}, "not marked ingested"

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
    await decide_all(e1, second)
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
    await to_units(admin, expert, assignment_id, skip=True)
    await decide_all(admin, assignment_id)
    monkeypatch.setattr(settings, "environment", "production")
    assert await run_jobs() == 1
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "ingestion_failed"
    assert models.embedded == [] and await count("finding_units") == 0


async def test_units_from_before_the_pipeline_cannot_be_ingested(models):
    admin, expert, assignment_id = await setup_one()
    await answer_and_submit(expert, assignment_id)
    await to_units(admin, expert, assignment_id, skip=True)
    async with session_factory()() as db:
        await db.execute(update(KnowledgeUnit).values(embed_text=None, embed_text_combined=None))
        await db.commit()
    await decide_all(admin, assignment_id)
    assert await run_jobs() == 1, "retrying can't help"
    assert (await admin.ok("GET", f"/assignments/{assignment_id}"))["state"] == "ingestion_failed"
    async with session_factory()() as db:
        job = await db.scalar(select(Job).where(Job.kind == JobKind.INGEST))
    assert job is not None and job.last_error == "UnitsNotEmbeddable"
