"""The filled vignettes of tests/fixtures/scale_answers build into consistent rows, with no model
and no database (the vectors are made by the integration tests, never stored)."""

import chips_fixture as cf
import numpy as np
import pytest


@pytest.fixture(scope="module")
def silver():
    answers = cf.load(experts=cf.SILVER_EXPERTS)
    built = cf.build(answers)
    tables, local_of = cf.tables_of(answers, built)
    return answers, built, tables, local_of


def fake_vectors(tables: dict) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(0)
    out = {}
    for name, rows in (("i1", tables["units"]), ("cues", tables["cue_keys"])):
        m = rng.normal(size=(len(rows), 1024)).astype(np.float32)
        out[name] = m / np.linalg.norm(m, axis=1, keepdims=True)
    return out


def test_the_fixture_is_consistent():
    assert cf.check() == []


def test_the_fixture_holds_answers_and_labels_only():
    names = {p.name for p in cf.FIXTURE.iterdir()}
    assert names == {
        "documents",
        "claims",
        "labels",
        "experts.json",
        "questions.json",
        "manifest.json",
    }
    assert not list(cf.FIXTURE.rglob("*.npz"))


def test_all_32_experts_answer_and_every_response_has_its_labels():
    answers = cf.load()
    assert len(answers.docs) == 32
    for doc in answers.docs:
        assert {r.vignette_id for r in doc.responses} <= set(answers.labels[doc.session_id])
        assert doc.session_id in answers.roles


def test_the_silver_experts_give_28_sessions_and_the_40_labelled_questions(silver):
    answers, built, tables, _ = silver
    assert answers.experts == list(cf.SILVER_EXPERTS)
    assert len(tables["sessions"]) == 28 and len(answers.questions) == 40
    assert len(tables["units"]) == sum(len(r["units"]) for r in built["records"])


def test_every_row_points_at_a_row_that_exists(silver):
    _, _, tables, _ = silver
    units = {u["id"] for u in tables["units"]}
    sentences = {s["id"] for s in tables["sentences"]}
    highlights = {h["id"] for h in tables["highlights"]}
    sessions = {s["id"] for s in tables["sessions"]}
    assert all(u["session_id"] in sessions for u in tables["units"])
    assert all(u["highlight_id"] in highlights for u in tables["units"] if u["highlight_id"])
    assert all(u in units and s in sentences for u, s, _ in tables["unit_sentences"])
    assert all(u in units and 0 <= k < len(tables["cue_keys"]) for u, k, _ in tables["unit_cues"])
    assert all(0 <= h["cue_key"] < len(tables["cue_keys"]) for h in tables["highlights"])


def test_every_sentence_is_filed(silver):
    _, built, _, _ = silver
    for rec in built["records"]:
        assert all(s["targets"] for s in rec["sentences"]), rec["session_id"]


def test_the_findings_records_are_readable_and_their_unit_ids_are_local(silver):
    from expert_knowledge_core.records import is_readable

    _, _, tables, _ = silver
    for session in tables["sessions"]:
        assert is_readable(session["document"])
        assert {u["id"] for u in session["document"]["units"]} <= {
            "case",
            *(h["id"] for h in session["document"]["highlights"]),
        }


def test_crowding_adds_near_identical_copies_of_every_expert(silver):
    _, _, tables, _ = silver
    vectors = fake_vectors(tables)
    crowd, moved = cf.crowded(tables, vectors, copies=2)
    n = len(tables["units"])
    assert len(crowd["units"]) == 3 * n and moved["i1"].shape == (3 * n, 1024)
    assert len(crowd["experts"]) == 3 * len(tables["experts"])
    assert len({u["id"] for u in crowd["units"]}) == 3 * n
    assert crowd["cue_keys"] == tables["cue_keys"]  # the cue keys stay shared
    assert len(tables["units"]) == n  # the tables themselves are not changed

    copy = crowd["units"][n]
    assert copy["id"].startswith(f"{copy['session_id']}-") and copy["expert_id"].endswith("~1")
    assert copy["embed_text"] == tables["units"][0]["embed_text"]
    cosine = np.sum(moved["i1"][:n] * moved["i1"][n : 2 * n], axis=1)
    assert cosine.min() > 0.99


def test_crowding_is_repeatable(silver):
    _, _, tables, _ = silver
    vectors = fake_vectors(tables)
    first = cf.crowded(tables, vectors, copies=1)[1]["i1"]
    assert np.array_equal(first, cf.crowded(tables, vectors, copies=1)[1]["i1"])
