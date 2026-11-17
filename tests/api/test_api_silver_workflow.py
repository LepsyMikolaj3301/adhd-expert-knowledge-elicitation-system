"""The silver answers through the whole platform: two synthetic experts answer seven cases, two
more review them, the admin decides, and the approved answers are ingested into the RAG tables.

It runs the development seeder (scripts/db/seed_silver_reviews.py) in process on a committed copy of
the silver fixtures (tests/fixtures/silver_chips), with the models faked as in every API test. The
copy of platform_seed.json has a patient summary for V001, which the one under data/ lacks: a case
cannot be published without one, so the seeder only works there because V001 was imported by hand
first. What
it checks is the plumbing between the stages, on real data: the ingested rows, the shared cue keys,
the search and the removal of one expert's knowledge.
"""

import argparse
import json
from pathlib import Path

import pytest
import seed_silver_reviews as seeder
from api_helpers import admin_api, decide_all, run_jobs
from sqlalchemy import text

from app.assignments.answers import AnswerPayload, clean_submission
from app.core.db import session_factory

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "silver_chips"
PLAN = json.loads((FIXTURES / "platform_seed.json").read_text())
SUBMISSIONS = len(PLAN["authors"]) * len(PLAN["vignettes"])


@pytest.fixture(autouse=True)
def committed_fixtures(monkeypatch):
    monkeypatch.setattr(seeder, "SILVER", FIXTURES)
    monkeypatch.setenv("SEED_PASSWORD", "a long development password")


async def chips(query: str, **params):
    async with session_factory()() as db:
        return (await db.execute(text(query), params)).all()


async def seed_and_review():
    """The admin account, the seeder's data, and every assignment in peer review."""
    admin = await admin_api("admin@example.com")
    await seeder.main(
        argparse.Namespace(
            admin_email="admin@example.com", password_env="SEED_PASSWORD", no_run_jobs=False
        )
    )
    assignments = await admin.ok("GET", "/assignments")
    return admin, assignments


def test_every_silver_answer_passes_the_rules_of_a_submission():
    pairs = json.loads((FIXTURES / "platform_pairs.json").read_text())
    payloads = seeder.build_payloads(PLAN, pairs)
    assert len(payloads) == SUBMISSIONS
    for (author, code), payload in payloads.items():
        text_of = seeder.fixture_vignette(code)["text"]
        cleaned = clean_submission(
            AnswerPayload.model_validate(payload), seeder.ALL_QUESTIONS, text_of
        )
        assert cleaned.answers and cleaned.q4 is not None, (author, code)


async def test_the_seeded_answers_wait_in_peer_review_with_their_votes_and_comments():
    admin, assignments = await seed_and_review()
    assert len(assignments) == SUBMISSIONS
    assert {a["state"] for a in assignments} == {"peer_review"}
    assert {a["vignette_code"] for a in assignments} == set(PLAN["vignettes"])

    comments = disapprovals = 0
    for assignment in assignments:
        view = await admin.ok("GET", f"/assignments/{assignment['id']}/answers")
        for answer in view["answers"]:
            comments += len(answer["comments"])
            disapprovals += answer["disapprovals"]
            # every reviewer voted on every answer
            assert answer["approvals"] + answer["disapprovals"] == len(PLAN["reviewers"])
    planned = sum(len(plan.get("comments", [])) for plan in PLAN["reviews"].values())
    planned_no = sum(
        len(questions)
        for plan in PLAN["reviews"].values()
        for questions in plan.get("disapprove", {}).values()
    )
    assert comments == planned
    assert disapprovals == planned_no


async def test_approved_silver_answers_are_ingested_searchable_and_removable():
    admin, assignments = await seed_and_review()
    for assignment in assignments:
        await decide_all(admin, assignment["id"])
    await run_jobs()
    states = {a["state"] for a in await admin.ok("GET", "/assignments")}
    assert states == {"ingested"}

    # what was written
    (sessions,) = await chips("SELECT count(*) FROM chips.elicitation_sessions")
    assert sessions[0] == SUBMISSIONS
    assert (await chips("SELECT DISTINCT tier FROM chips.vignettes")) == [("app",)]
    (cases, whole) = (
        (await chips("SELECT count(*) FROM chips.finding_units WHERE kind = 'case'"))[0][0],
        (await chips("SELECT count(*) FROM chips.finding_units"))[0][0],
    )
    assert cases == SUBMISSIONS and whole > cases  # every answer has its whole-case unit and quotes
    assert (await chips("SELECT count(*) FROM chips.finding_units WHERE sparse IS NULL"))[0][0] == 0

    # the cue keys are shared: one per distinct span of a case, however many experts cited it
    keys = (await chips("SELECT count(*) FROM chips.cue_keys"))[0][0]
    spans = (
        await chips(
            "SELECT count(*) FROM (SELECT DISTINCT vignette_id, vignette_version, span "
            "FROM chips.highlights) s"
        )
    )[0][0]
    assert keys == spans < (await chips("SELECT count(*) FROM chips.highlights"))[0][0]

    # a search over it finds units of the case the words come from
    hits = (
        await admin.ok(
            "POST",
            "/knowledge-units/search",
            json={"query": "deadline", "mode": "question", "k": 8},
        )
    )["hits"]
    assert hits and all(h["unit"]["status"] == "ingested" for h in hits)

    # one expert's knowledge is withdrawn: their units go, the other expert's stay
    experts = await chips("SELECT id FROM chips.experts ORDER BY id")
    assert len(experts) == len(PLAN["authors"])
    gone, kept = experts[0][0], experts[1][0]
    removed = await admin.ok("DELETE", f"/knowledge-units/by-expert/{gone}")
    assert removed["removed"] > 0
    await run_jobs()  # the refit
    assert (await admin.ok("GET", "/knowledge-units/index"))["state"] == "up_to_date"
    assert (await chips("SELECT count(*) FROM chips.finding_units WHERE expert_id = :e", e=gone))[
        0
    ][0] == 0
    assert (await chips("SELECT count(*) FROM chips.finding_units WHERE expert_id = :e", e=kept))[
        0
    ][0] > 0
    orphans = await chips(
        "SELECT count(*) FROM chips.cue_keys c WHERE NOT EXISTS "
        "(SELECT 1 FROM chips.highlights h WHERE h.cue_key_id = c.id)"
    )
    assert orphans[0][0] == 0
