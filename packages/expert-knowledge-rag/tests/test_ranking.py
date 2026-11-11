import numpy as np

from expert_knowledge_core.retrieval import CONTEXT_BONUS, RRF_K
from expert_knowledge_rag.ranking import (
    UnitHit,
    cue_scores,
    downweight_duplicate_cases,
    rank_by_cues,
)


def case(uid: str, vector) -> UnitHit:
    return UnitHit(
        uid,
        "S",
        "X",
        "V",
        1,
        "case",
        None,
        None,
        False,
        "t",
        1.0,
        np.array(vector, dtype=np.float32),
    )


def fragment(uid: str) -> UnitHit:
    return UnitHit(uid, "S", "X", "V", 1, "fragment", "h1", None, False, "t", 1.0)


def test_near_duplicate_case_units_go_last_and_fragments_stay():
    hits = [case("c1", [1, 0]), fragment("f1"), case("c2", [0.99, 0.05]), case("c3", [0, 1])]
    assert [h.id for h in downweight_duplicate_cases(hits)] == ["c1", "f1", "c3", "c2"]


def test_different_case_units_keep_their_order():
    hits = [case("c1", [1, 0]), case("c2", [0, 1])]
    assert [h.id for h in downweight_duplicate_cases(hits)] == ["c1", "c2"]


def test_cue_scores_sum_reciprocal_ranks_over_sentences():
    score = cue_scores([[7, 8], [8]], RRF_K)
    assert score[7] == 1 / (RRF_K + 1)
    assert score[8] == 1 / (RRF_K + 2) + 1 / (RRF_K + 1)


def row(uid: str, cue: int, context: list[int] | None) -> dict:
    return {
        "id": uid, "session_id": "S", "expert_id": "X", "vignette_id": "V", "vignette_version": 1,
        "kind": "fragment", "highlight_id": uid, "direction": None, "is_synthetic": False,
        "embed_text": "t", "cue_id": cue, "context_ids": context, "vector": None,
    }  # fmt: skip


def test_a_unit_scores_its_cue_plus_a_bonus_for_matching_context_cues():
    score = {1: 0.10, 2: 0.05, 3: 0.02}
    hits = rank_by_cues([row("a", 1, None), row("b", 2, [1, 3]), row("c", 9, [1])], score)
    assert [h.id for h in hits] == ["b", "a"]  # c's own cue did not match: not a hit
    assert hits[0].score == 0.05 + CONTEXT_BONUS * (0.10 + 0.02)
    assert hits[1].score == 0.10


def test_context_cues_that_did_not_match_add_nothing():
    hits = rank_by_cues([row("a", 1, [5, 6])], {1: 0.1})
    assert hits[0].score == 0.1


def test_from_row_parses_the_case_vector():
    r = row("a", 1, None) | {"score": 0.5, "vector": "[0.5,-1,2]"}
    h = UnitHit.from_row(r)
    assert h.vector is not None
    assert h.score == 0.5 and h.vector.tolist() == [0.5, -1.0, 2.0]
