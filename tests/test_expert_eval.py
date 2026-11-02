"""Retrieval metrics, intervals and the lean unit context, on hand-made rankings (no models)."""

import numpy as np
import pytest
from expert_metrics import Item, bootstrap, ceiling, paired_bootstrap, score_query, tokens

from app.elicitation.units import _context_sentence


def items(*ids: str, shown: str = "x" * 40) -> list[Item]:
    return [Item([i], shown, [shown]) for i in ids]


COVERS = {"c1": {"u1"}, "c2": {"u2"}, "c3": {"u3", "u4"}, "c4": set()}


def test_recall_hit_mrr_for_a_known_ranking():
    s = score_query(items("x", "u2", "x2", "u1"), ["c1", "c2", "c3", "c4"], COVERS)
    assert s["recall@1"] == 0 and s["hit@1"] == 0
    assert s["recall@4"] == pytest.approx(2 / 3)  # c4 is held by no unit and is not counted
    assert s["mrr"] == 0.5
    assert 0 < s["ndcg@10"] < 1


def test_query_with_no_reachable_claim_is_skipped():
    assert score_query(items("u1"), ["c4"], COVERS) == {}


def test_ceiling_is_the_best_k_units_can_do():
    wanted = {"c1": {"u1"}, "c2": {"u1", "u2"}, "c3": {"u3"}}
    assert ceiling(wanted, 1) == pytest.approx(2 / 3)  # u1 holds c1 and c2
    assert ceiling(wanted, 4) == 1.0


def test_token_budget_fill_skips_items_that_do_not_fit():
    long, short = "x" * 4000, "x" * 40  # 1000 and 10 tokens
    ranked = [Item(["u1"], long, [long]), Item(["u2"], short, [short])]
    s = score_query(ranked, ["c1", "c2"], COVERS)
    assert s["recall@300t"] == 0.5  # the long item does not fit, the short one does
    assert tokens(short) == 10


def test_bootstrap_interval_contains_the_mean_and_paired_difference_is_detected():
    a = np.array([0.6, 0.7, 0.8, 0.7, 0.6, 0.9, 0.7, 0.8])
    mean, lo, hi = bootstrap(a)
    assert lo <= mean <= hi
    m, lo, hi = paired_bootstrap(a, a - 0.2)
    assert m == pytest.approx(0.2) and lo > 0
    _, lo, hi = paired_bootstrap(a, a[::-1])  # same values, shuffled pairing: no clear gap
    assert lo < 0 < hi


def test_lean_context_is_shorter_and_never_drops_the_quote():
    sentence = " ".join(f"w{i}" for i in range(80))
    quote = "w40 w41 w42"
    start = sentence.index(quote)
    span = (start, start + len(quote))
    full = _context_sentence(sentence, span, 60)
    lean = _context_sentence(sentence, span, 30)
    assert len(lean.split()) < len(full.split()) <= 70
    assert quote in lean
    # a quote longer than the budget is kept whole instead of looping back to the start
    long_quote = " ".join(f"w{i}" for i in range(10, 50))
    s2 = sentence.index(long_quote)
    assert long_quote in _context_sentence(sentence, (s2, s2 + len(long_quote)), 30)


def _searcher(unit_ids: list[str], vectors):
    from expert_retrieval import Searcher

    s = Searcher.__new__(Searcher)  # skip embedding and BM25: only the re-ranking is under test
    s.items = [Item([u], "t", ["t"]) for u in unit_ids]
    s.dense = np.array(vectors, dtype=float)
    s.first_rep = np.arange(len(unit_ids))
    return s


def test_cap_puts_one_result_per_vignette_and_question_first():
    s = _searcher(["D1:V1:Q1:1", "D2:V1:Q1:1", "D1:V1:Q1:2", "D1:V2:Q1:1"], np.eye(4).tolist())
    assert s._cap([0, 1, 2, 3]) == [0, 3, 1, 2]


def test_mmr_prefers_a_different_point_over_a_near_duplicate():
    s = _searcher(["a:V1:Q1:1", "b:V1:Q1:1", "c:V2:Q2:1"], [[1, 0], [0.99, 0.14], [0, 1]])
    fused = {0: 1.0, 1: 0.95, 2: 0.7}
    assert s._mmr([0, 1, 2], fused)[:2] == [0, 2]


def test_weighted_kappa_is_one_for_agreement_and_low_for_opposite_scores():
    from expert_metrics import weighted_kappa

    scores = [1, 2, 3, 4, 5, 3, 2, 4]
    assert weighted_kappa(scores, scores) == pytest.approx(1.0)
    assert weighted_kappa(scores, [6 - s for s in scores]) < 0


EXPERT_SAMPLE = {
    "key_points": 4, "fidelity": 5, "attribution": 4, "usefulness": 4, "citation_quality": 4,
    "unsupported_claims": False, "abstention_ok": None, "pass": True, "rationale": "ok",
}  # fmt: skip


def test_expert_judgment_parser_accepts_null_fidelity_only_without_notes_fields():
    from rag_common import parse_judgment

    systems = {"A": ["answer"]}
    reply = {"A": {"samples": [EXPERT_SAMPLE], "consistency": None}}
    assert parse_judgment(reply, systems, expert=True)["A"]["samples"][0]["pass"] is True
    no_notes = {**EXPERT_SAMPLE, "fidelity": None, "citation_quality": None}
    parse_judgment({"A": {"samples": [no_notes]}}, systems, expert=True)
    with pytest.raises(ValueError, match="key_points"):
        parse_judgment({"A": {"samples": [{**EXPERT_SAMPLE, "key_points": None}]}}, systems, True)
    with pytest.raises(ValueError, match="unsupported_claims"):
        bad = {k: v for k, v in EXPERT_SAMPLE.items() if k != "unsupported_claims"}
        parse_judgment({"A": {"samples": [bad]}}, systems, expert=True)
    with pytest.raises(ValueError, match="attribution"):
        parse_judgment({"A": {"samples": [{**EXPERT_SAMPLE, "attribution": 7}]}}, systems, True)


def test_expert_judge_prompt_shows_notes_points_and_the_no_notes_case():
    from rag_common import expert_judge_prompt

    q = {
        "question": "How?",
        "reference_points": ["main point (lowers)"],
        "optional_points": ["extra"],
    }
    prompt = expert_judge_prompt(q, [{"id": "u1", "text": "note text"}], {"A": ["the answer"]})
    assert "[E1] note text" in prompt and "main point" in prompt
    assert "(no notes were given)" in expert_judge_prompt(q, [], {"A": ["x"]})


def test_expert_judge_zero_key_points_counts_as_the_lowest_score():
    from rag_common import parse_sample_judgment

    assert parse_sample_judgment({**EXPERT_SAMPLE, "key_points": 0}, expert=True)["key_points"] == 1
    with pytest.raises(ValueError, match="fidelity"):
        parse_sample_judgment({**EXPERT_SAMPLE, "fidelity": 0}, expert=True)
