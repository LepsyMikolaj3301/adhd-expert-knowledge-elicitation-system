"""The frozen silver snapshot is consistent, and `crowded` makes the copies it promises."""

import chips_snapshot as cs
import numpy as np
import pytest


@pytest.fixture(scope="module")
def snapshot():
    if not (cs.SNAPSHOT / "tables.json").exists():
        pytest.skip("no snapshot: python scripts/db/chips_snapshot.py freeze")
    return cs.load_snapshot()


def test_the_vectors_match_the_rows_they_belong_to(snapshot):
    tables, vectors, queries = snapshot
    assert vectors["i1"].shape == vectors["i3"].shape == (len(tables["units"]), 1024)
    assert vectors["cues"].shape == (len(tables["cue_keys"]), 1024)
    assert vectors["queries"].shape == (len(queries["embedded_texts"]), 1024)
    assert len(set(queries["embedded_texts"])) == len(queries["embedded_texts"])


@pytest.mark.parametrize("name", ["i1", "i3", "cues", "queries"])
def test_the_vectors_are_unit_length_within_half_precision(snapshot, name):
    norms = np.linalg.norm(snapshot[1][name], axis=1)
    assert np.allclose(norms, 1.0, atol=0.01)


def test_every_unit_and_label_points_at_a_row_that_exists(snapshot):
    tables, _, queries = snapshot
    units = {u["id"] for u in tables["units"]}
    sessions = {s["id"] for s in tables["sessions"]}
    assert len(units) == len(tables["units"])
    for u in tables["units"]:
        assert u["session_id"] in sessions and u["id"].startswith(f"{u['session_id']}-")
    for unit, sentence, _ in tables["unit_sentences"]:
        assert unit in units and sentence in {s["id"] for s in tables["sentences"]}
    claimed = {c for q in queries["questions"] for c in q["pooled_ids"]}
    assert claimed <= set(queries["covers"])
    assert all(set(held) <= units and held for held in queries["covers"].values())


def test_the_questions_carry_their_labels_and_the_vignettes_they_come_from(snapshot):
    questions = snapshot[2]["questions"]
    assert len(questions) == 40
    for q in questions:
        assert set(q["claim_ids"]) <= set(q["pooled_ids"]) and q["vignettes"]


def test_the_findings_records_are_readable_and_their_unit_ids_are_local(snapshot):
    from expert_knowledge_core.records import is_readable

    tables = snapshot[0]
    for session in tables["sessions"]:
        assert is_readable(session["document"])
        assert {u["id"] for u in session["document"]["units"]} <= {
            "case",
            *(h["id"] for h in session["document"]["highlights"]),
        }


def test_crowding_adds_near_identical_copies_of_every_expert(snapshot):
    tables, vectors, _ = snapshot
    crowd, moved = cs.crowded(tables, vectors, copies=2)
    n = len(tables["units"])
    assert len(crowd["units"]) == 3 * n and moved["i1"].shape == (3 * n, 1024)
    assert len(crowd["experts"]) == 3 * len(tables["experts"])
    assert len({u["id"] for u in crowd["units"]}) == 3 * n
    assert crowd["cue_keys"] == tables["cue_keys"]  # the cue keys stay shared
    assert len(tables["units"]) == n  # the snapshot itself is not changed

    copy = crowd["units"][n]
    assert copy["id"].startswith(f"{copy['session_id']}-") and copy["expert_id"].endswith("~1")
    assert copy["embed_text"] == tables["units"][0]["embed_text"]
    for name in ("i1", "i3"):
        cosine = np.sum(moved[name][:n] * moved[name][n : 2 * n], axis=1)
        assert cosine.min() > 0.99


def test_crowding_is_repeatable(snapshot):
    tables, vectors, _ = snapshot
    first = cs.crowded(tables, vectors, copies=1)[1]["i1"]
    assert np.array_equal(first, cs.crowded(tables, vectors, copies=1)[1]["i1"])
