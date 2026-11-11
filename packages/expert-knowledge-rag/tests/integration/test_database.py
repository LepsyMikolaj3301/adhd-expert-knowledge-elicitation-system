"""The retrievers against a real Postgres with pgvector (see conftest.py)."""

import psycopg
import pytest
from psycopg import sql

from expert_knowledge_core.example import example_record
from expert_knowledge_rag import (
    ExpertFilter,
    ExpertKnowledgeStore,
    ExpertQuestionRetriever,
    PatientTextRetriever,
)

pytestmark = pytest.mark.integration

H3_CUE = "every time I try to type a formula my hand starts shaking slightly"


def question(store, embeddings, **kw):
    return ExpertQuestionRetriever(store=store, embeddings=embeddings, **kw)


def ids(docs):
    return [d.metadata["unit_ids"] for d in docs]


def test_bm25_finds_the_units_that_use_the_word_and_merges_them(store, embeddings):
    docs = question(store, embeddings, search="bm25").invoke("parsimoniously")
    assert len(docs) == 1  # h1, h2, h3 share Q2.1: one note, each sentence once
    assert set(docs[0].metadata["unit_ids"]) == {"S1-V001-h1", "S1-V001-h2", "S1-V001-h3"}
    assert docs[0].page_content.count("explains most of this more parsimoniously") == 1
    assert docs[0].metadata["merged"] and not docs[0].metadata["is_synthetic"]


def test_dense_search_puts_the_unit_with_the_same_text_first(store, embeddings):
    target = example_record("S1", "X1")["units"][3]  # h4's reviewed text
    docs = question(store, embeddings, search="dense", merge_shared=False, k=3).invoke(target["i1"])
    assert docs[0].id == "S1-V001-h4"


def test_hybrid_is_the_default_and_returns_notes(store, embeddings):
    docs = question(store, embeddings).invoke(
        "How do I tell sleep deprivation from attention problems?"
    )
    assert docs and all(d.metadata["source"] == "expert" for d in docs)
    assert docs[0].page_content.startswith("Teaching case V001: an adult's journal entry")


def test_synthetic_units_are_excluded_unless_asked_for(store, embeddings):
    plain = question(store, embeddings, search="bm25", k=10).invoke("insomnia")
    assert {d.metadata["session_id"] for d in plain} == {"S1"}
    both = question(
        store, embeddings, search="bm25", k=10, filter=ExpertFilter(include_synthetic=True)
    ).invoke("insomnia")
    assert {d.metadata["session_id"] for d in both} == {"S1", "S2"}


def test_filters_narrow_the_search(store, embeddings):
    f = ExpertFilter(include_synthetic=True, populations=["child"])
    assert question(store, embeddings, search="bm25", filter=f).invoke("insomnia") == []
    f = ExpertFilter(include_synthetic=True, exclude_vignettes=["V001"])
    assert question(store, embeddings, search="hybrid", filter=f).invoke("insomnia") == []
    f = ExpertFilter(include_synthetic=True, populations=["adult"], framings=["personal_journal"])
    assert question(store, embeddings, search="bm25", filter=f).invoke("insomnia")


def test_notes_of_two_experts_stay_separate(store, embeddings):
    docs = question(
        store, embeddings, search="bm25", k=10, filter=ExpertFilter(include_synthetic=True)
    ).invoke("parsimoniously")
    assert sorted(d.metadata["session_id"] for d in docs) == ["S1", "S2"]


def test_sync_and_async_agree(store, embeddings):
    retriever = question(store, embeddings, k=3)
    q = "sleep deprivation or attention problems"
    import asyncio

    sync = retriever.invoke(q)
    asynchronous = asyncio.run(retriever.ainvoke(q))
    assert ids(sync) == ids(asynchronous)
    assert [d.page_content for d in sync] == [d.page_content for d in asynchronous]


def test_patient_text_finds_the_units_of_the_matching_highlight(store, embeddings):
    docs = PatientTextRetriever(
        store=store, embeddings=embeddings, search="bm25", merge_shared=False
    ).invoke("My hand starts shaking slightly.")
    assert ids(docs) == [["S1-V001-h3"]]
    assert docs[0].metadata["patient_words"] == [{"text": H3_CUE, "direction": "unclear"}]


def test_patient_text_prefers_a_unit_whose_co_cited_highlights_also_match(store, embeddings):
    text = f"{H3_CUE}. I haven't slept well since moving into this new flat two months ago."
    docs = PatientTextRetriever(store=store, embeddings=embeddings, merge_shared=False, k=4).invoke(
        text
    )
    assert docs[0].metadata["unit_ids"] in (["S1-V001-h3"], ["S1-V001-h2"])
    assert {u for d in docs for u in d.metadata["unit_ids"]} <= {
        f"S1-V001-{x}" for x in ("h1", "h2", "h3", "h4")
    }


def test_the_case_being_read_can_be_excluded(store, embeddings):
    retriever = PatientTextRetriever(
        store=store, embeddings=embeddings, search="bm25",
        filter=ExpertFilter(exclude_vignettes=["V001"]),
    )  # fmt: skip
    assert retriever.invoke(H3_CUE) == []


def test_the_connection_is_read_only(store):
    delete = sql.SQL("DELETE FROM {}").format(sql.Identifier(store.schema, "finding_units"))
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        store.run([(delete, {})])
    (count,) = store.run(
        [
            (
                sql.SQL("SELECT count(*) AS n FROM {}").format(
                    sql.Identifier(store.schema, "finding_units")
                ),
                {},
            )
        ]
    )
    assert count[0]["n"] > 0


def test_a_store_needs_a_way_to_connect():
    with pytest.raises(ValueError):
        ExpertKnowledgeStore()
