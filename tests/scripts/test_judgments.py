"""Judgment parsing and loading, shared by the generation evals and the judge scripts."""

import json

import pytest
from eval_expert_generation import load_judgments
from rag_common import parse_sample_judgment

ROW = {
    "key_points": 4, "fidelity": 4, "attribution": 4, "usefulness": 4, "citation_quality": 4,
    "unsupported_claims": False, "abstention_ok": None, "pass": True, "rationale": "fine",
}  # fmt: skip


def test_a_valid_expert_row_is_kept_as_it_is():
    assert parse_sample_judgment(ROW, expert=True) == ROW


def test_a_zero_for_key_points_counts_as_the_bottom_of_the_scale():
    assert parse_sample_judgment({**ROW, "key_points": 0}, expert=True)["key_points"] == 1


def test_fidelity_and_citation_quality_may_be_null_when_the_answer_saw_no_notes():
    row = {**ROW, "fidelity": None, "citation_quality": None}
    assert parse_sample_judgment(row, expert=True)["fidelity"] is None


@pytest.mark.parametrize(
    "bad",
    [{"key_points": 6}, {"usefulness": None}, {"attribution": "4"}, {"pass": "yes"}],
)
def test_a_malformed_row_is_refused(bad):
    with pytest.raises(ValueError):
        parse_sample_judgment({**ROW, **bad}, expert=True)


def test_judgments_are_loaded_by_the_tag_of_their_file(tmp_path):
    (tmp_path / "judgments.json").write_text(json.dumps({"judgments": [ROW]}))
    (tmp_path / "judgments_j2.json").write_text(json.dumps({"judgments": [ROW, ROW]}))
    loaded = load_judgments(tmp_path)
    assert {k: len(v) for k, v in loaded.items()} == {"main": 1, "j2": 2}
