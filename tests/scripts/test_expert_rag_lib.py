"""Tests for expert_rag_lib.py (the try-out shared by the script and the notebook): no database."""

import expert_rag_lib as lib
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from expert_knowledge_core.prompts import NOT_IN_SOURCES
from expert_knowledge_rag import (
    ExpertFilter,
    ExpertKnowledgeStore,
    ExpertQuestionRetriever,
    PatientTextRetriever,
)


def doc(unit: str, expert: str = "E1", vignette: str = "V001") -> Document:
    return Document(
        page_content=f"note {unit}",
        metadata={"unit_ids": [unit], "expert_id": expert, "vignette_id": vignette, "score": 0.03},
    )


def test_cited_reads_every_note_number_in_brackets():
    assert lib.cited("A [E1] and [E2, E3]; not E4 or [5].") == [1, 2, 3]


def test_checks_separates_valid_and_invalid_citations():
    docs = [doc("u1", "X"), doc("u2", "Y")]
    c = lib.checks("Both agree [E1][E2], and [E7] says more.", docs)
    assert c["n_cited"] == 2 and c["invalid_citations"] == [7]
    assert c["experts_cited"] == ["X", "Y"] and not c["abstained"]
    assert lib.checks(NOT_IN_SOURCES, docs)["abstained"]


def test_retrieval_record_hit_and_claim_recall():
    item = {
        "id": "L01",
        "suite": "labelled",
        "relevant_units": ["u1"],
        "covers": {"c1": ["u1"], "c2": ["u9"]},
    }
    rec = lib.retrieval_record(item, [doc("u1"), doc("u2", "E2")], {})
    assert rec["hit"] is True and rec["claim_recall"] == 0.5
    assert rec["experts_retrieved"] == ["E1", "E2"] and rec["n_notes"] == 2
    miss = lib.retrieval_record(item, [doc("u2")], {})
    assert miss["hit"] is False and miss["claim_recall"] == 0.0


def test_retrieval_record_vignette_lists_experts_of_the_case():
    item = {"id": "V001-readings", "suite": "vignette", "vignette": "V001", "relevant_units": []}
    rec = lib.retrieval_record(item, [doc("u1")], {"V001": ["E1", "E2"]})
    assert rec["experts_in_vignette"] == ["E1", "E2"] and "hit" not in rec


def test_summarise_per_suite():
    records = {
        "a": {"suite": "labelled", "hit": True, "claim_recall": 1.0, "vignettes_retrieved": ["V1"]},
        "b": {"suite": "labelled", "hit": False, "claim_recall": 0.0, "vignettes_retrieved": []},
        "c": {
            "suite": "vignette",
            "experts_retrieved": ["E1", "E2"],
            "experts_in_vignette": ["E1", "E2"],
            "vignettes_retrieved": ["V1"],
        },
    }
    s = lib.summarise(records)
    assert s["labelled"] == {
        "items": 2,
        "hit_rate": 0.5,
        "claim_recall": 0.5,
        "mean_vignettes_retrieved": 0.5,
    }
    assert s["vignette"]["all_experts_retrieved"] == 1.0 and "patient" not in s


def test_build_items_on_silver():
    items = lib.build_items(lib.SILVER_SCHEMA, ["labelled", "patient"], 4, None, {})
    labelled = [i for i in items if i["suite"] == "labelled"]
    patients = [i for i in items if i["suite"] == "patient"]
    assert (len(labelled), len(patients)) == (40, 9)
    assert labelled[0]["id"] == "L01" and labelled[0]["relevant_units"]
    assert patients[0]["patient_text"] and patients[0]["question"] == lib.PATIENT_QUESTION
    assert lib.judge_question(patients[0]).startswith("Patient text:")
    assert len(lib.silver_examples()) == 49


def test_build_items_vignette_suite_asks_three_questions_per_case():
    items = lib.build_items("chips", ["vignette"], 4, 2, {"V001": ["E1"], "V002": ["E1"], "V3": []})
    assert [i["id"] for i in items][:3] == [
        "V001-readings",
        "V001-agreement",
        "V001-alternatives",
    ]
    assert len(items) == 6 and all(i["k"] == lib.VIGNETTE_K for i in items)
    # without the silver snapshot (live schema) the labelled and patient suites give nothing
    assert lib.build_items("chips", ["labelled", "patient"], 4, None, {}) == []


def test_make_retriever_picks_class_and_passes_options():
    store = ExpertKnowledgeStore("postgresql://unused")
    emb = DeterministicFakeEmbedding(size=1024)
    flt = ExpertFilter(vignettes=["V001"])
    q = lib.make_retriever(
        store, emb, patient=False, k=6, search="dense", filter=flt, group_fragments=True
    )
    assert isinstance(q, ExpertQuestionRetriever)
    assert (q.k, q.search, q.filter, q.group_fragments, q.merge_shared) == (
        6, "dense", flt, True, True,
    )  # fmt: skip
    p = lib.make_retriever(store, emb, patient=True, k=4, merge_shared=False)
    assert isinstance(p, PatientTextRetriever) and not p.merge_shared and p.search == "hybrid"
