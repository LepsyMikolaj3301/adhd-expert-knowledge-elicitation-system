"""Many experts answer one vignette, and the answers are alike: what the top k then holds.

The silver answers have only two experts per vignette, and their case units are not near-duplicates
(cosine 0.70-0.90 against the 0.9 of `downweight_duplicate_cases`), so on the real answers neither
the crowding nor the down-weighting can be seen. Here every expert has four synthetic copies, in the
same words with vectors moved a little (chips_fixture.crowded): ten answers to each vignette, the
copies cosine > 0.99 from their original. That says nothing about quality; it shows how the
retrievers treat a vignette whose answers fill the top k.
"""

import pytest

from expert_knowledge_rag import ExpertFilter, ExpertQuestionRetriever

pytestmark = pytest.mark.integration

K = 8


@pytest.fixture(scope="module")
def questions(silver):
    return silver[2]["questions"]


def retriever(store, embedder, vignette: str, **options):
    flt = ExpertFilter(vignettes=[vignette])
    return ExpertQuestionRetriever(
        store=store, embeddings=embedder, filter=flt, k=K, merge_shared=False, **options
    )


def results(store, embedder, questions, **options):
    """Per question, the notes of a search limited to the first vignette its labels come from."""
    return [
        retriever(store, embedder, q["vignettes"][0], **options).invoke(q["question"])
        for q in questions
    ]


def distinct_texts(docs) -> int:
    return len({d.page_content for d in docs})


def case_notes(docs) -> list:
    return [d for d in docs if d.metadata["kinds"][0] == "case"]


def test_the_vignette_has_ten_answers_and_the_top_k_is_filled_from_it(
    crowd_store, embedder, questions
):
    for docs in results(crowd_store, embedder, questions[:10]):
        assert len(docs) == K
        assert len({d.metadata["vignette_id"] for d in docs}) == 1
        ids = [u for d in docs for u in d.metadata["unit_ids"]]
        assert len(ids) == len(set(ids))  # the same unit is never returned twice


def test_without_down_weighting_one_answer_repeated_by_many_experts_can_fill_the_top_k(
    crowd_store, embedder, questions
):
    filled = [
        docs
        for docs in results(crowd_store, embedder, questions, downweight_duplicate_cases=False)
        if len(case_notes(docs)) >= K - 2
        and len({d.metadata["expert_id"] for d in case_notes(docs)}) >= K - 2
    ]
    assert filled, "no question had the whole-case answer returned once per expert"


def test_down_weighting_gives_the_places_of_repeated_case_answers_to_other_units(
    crowd_store, embedder, questions
):
    without = results(crowd_store, embedder, questions, downweight_duplicate_cases=False)
    with_ = results(crowd_store, embedder, questions)
    for plain, weighted in zip(without, with_, strict=True):
        assert len(case_notes(weighted)) <= len(case_notes(plain))
        assert distinct_texts(weighted) >= distinct_texts(plain)
    assert sum(distinct_texts(d) for d in with_) > sum(distinct_texts(d) for d in without)
    # a case answer is repeated at most once per distinct answer: here the two original experts'
    assert max(len(case_notes(d)) for d in with_) <= 3


@pytest.mark.xfail(
    strict=True,
    reason="down-weighting is for case units only: the same fragment, said by many experts, "
    "takes most of the top k. Grouping fragments (group_fragments, off by default) collapses them: "
    "see the test with grouping below.",
)
def test_the_top_k_does_not_repeat_the_same_finding_for_every_expert(
    crowd_store, embedder, questions
):
    for docs in results(crowd_store, embedder, questions):
        assert distinct_texts(docs) >= K // 2, [d.metadata["unit_ids"] for d in docs]


def test_with_grouping_the_top_k_does_not_repeat_the_same_finding_for_every_expert(
    crowd_store, embedder, questions
):
    for docs in results(crowd_store, embedder, questions, group_fragments=True):
        assert distinct_texts(docs) >= K // 2, [d.metadata["unit_ids"] for d in docs]


def test_notes_never_mix_the_answers_of_different_experts(crowd_store, embedder, questions):
    merged = 0
    for q in questions[:15]:
        flt = ExpertFilter(vignettes=[q["vignettes"][0]])
        docs = ExpertQuestionRetriever(
            store=crowd_store, embeddings=embedder, filter=flt, k=K
        ).invoke(q["question"])
        for d in docs:
            assert len({u.rsplit("-", 2)[0] for u in d.metadata["unit_ids"]}) == 1
            merged += len(d.metadata["unit_ids"]) > 1
    assert merged  # merging happened, within one expert's answer


def passages(docs) -> int:
    """How many different passages of the patient's text the notes are about."""
    return len({tuple(sorted(w["text"] for w in d.metadata["patient_words"])) for d in docs})


def test_grouping_returns_a_passage_once_and_counts_every_clinician(
    crowd_store, embedder, questions
):
    for docs in results(crowd_store, embedder, questions, group_fragments=True):
        group_ids = [d.metadata["group_id"] for d in docs if "group_id" in d.metadata]
        assert len(group_ids) == len(set(group_ids)), "a group is one note"
        for d in docs:
            if "agreement" in d.metadata:
                a = d.metadata["agreement"]
                assert 1 <= a["k"] <= a["n"] and a["line"] in d.page_content


def test_grouping_gives_the_places_of_repeated_fragments_to_other_passages(
    crowd_store, embedder, questions
):
    plain = results(crowd_store, embedder, questions)
    grouped = results(crowd_store, embedder, questions, group_fragments=True)
    assert sum(passages(d) for d in grouped) > sum(passages(d) for d in plain)
    assert all(passages(g) >= passages(p) for g, p in zip(grouped, plain, strict=True))
