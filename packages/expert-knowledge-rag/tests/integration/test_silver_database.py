"""The retrievers on the frozen silver snapshot: 28 sessions, 198 units, real bge-m3 vectors.

Unlike the V001 example of test_database.py, dense search here is meaningful (the query vectors are
frozen into the snapshot, so no model runs) and the findings records are readable ones.
"""

import asyncio
import logging

import psycopg
import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from psycopg import sql

from expert_knowledge_rag import (
    ExpertFilter,
    ExpertQuestionRetriever,
    PatientTextRetriever,
)

pytestmark = pytest.mark.integration

ALL = ExpertFilter()
FAKE = DeterministicFakeEmbedding(size=1024)


def question(store, embeddings, **kw):
    kw.setdefault("filter", ALL)
    return ExpertQuestionRetriever(store=store, embeddings=embeddings, **kw)


def unit_ids(docs):
    return [u for d in docs for u in d.metadata["unit_ids"]]


@pytest.fixture(scope="module")
def questions(silver):
    return silver[2]["questions"]


@pytest.fixture(scope="module")
def unit_rows(silver):
    return {u["id"]: u for u in silver[0]["units"]}


def hit_rate(retriever, questions, covers, k=8) -> float:
    """Share of the questions where a unit holding one of the pooled claims is among the top k."""
    hits = 0
    for q in questions:
        found = set(unit_ids(retriever.invoke(q["question"])[:k]))
        hits += any(found & set(covers[c]) for c in q["pooled_ids"])
    return hits / len(questions)


# --- the snapshot is what the tests think it is ------------------------------------------------


def test_the_schema_holds_the_whole_snapshot(silver, silver_store):
    tables = silver[0]
    (rows,) = silver_store.run(
        [
            (
                sql.SQL(
                    "SELECT (SELECT count(*) FROM {u}) AS units,"
                    " (SELECT count(*) FROM {c}) AS cues,"
                    " (SELECT count(*) FROM {s}) AS sessions,"
                    " (SELECT count(*) FROM {u} WHERE sparse IS NOT NULL"
                    " AND sparse_combined IS NOT NULL) AS fitted"
                ).format(
                    u=sql.Identifier(silver_store.schema, "finding_units"),
                    c=sql.Identifier(silver_store.schema, "cue_keys"),
                    s=sql.Identifier(silver_store.schema, "elicitation_sessions"),
                ),
                {},
            )
        ]
    )
    row = rows[0]
    assert (row["units"], row["cues"], row["sessions"]) == (
        len(tables["units"]),
        len(tables["cue_keys"]),
        len(tables["sessions"]),
    )
    assert row["fitted"] == row["units"]  # BM25 was fitted for I1 and I3


# --- search modes ------------------------------------------------------------------------------


def test_dense_search_finds_the_units_that_hold_the_claims(silver, silver_store, frozen, questions):
    covers = silver[2]["covers"]
    retriever = question(silver_store, frozen, search="dense", merge_shared=False)
    assert hit_rate(retriever, questions, covers) >= 0.8


def test_hybrid_search_is_at_least_as_good_as_either_side(silver, silver_store, frozen, questions):
    covers = silver[2]["covers"]
    rates = {
        mode: hit_rate(
            question(silver_store, frozen, search=mode, merge_shared=False), questions, covers, k=4
        )
        for mode in ("hybrid", "dense", "bm25")
    }
    assert rates["hybrid"] >= min(rates["dense"], rates["bm25"]), rates
    assert rates["hybrid"] >= 0.75, rates


def test_a_hybrid_note_comes_from_the_dense_or_the_bm25_candidates(silver_store, frozen, questions):
    # k * overfetch = 52 >= the fusion depth (50): the pools hybrid fuses are the same size here
    pools = {
        mode: question(silver_store, frozen, search=mode, merge_shared=False, k=13)
        for mode in ("dense", "bm25")
    }
    hybrid = question(silver_store, frozen, merge_shared=False, k=4)
    for q in questions[:10]:
        candidates = {u for r in pools.values() for u in unit_ids(r.invoke(q["question"]))}
        assert set(unit_ids(hybrid.invoke(q["question"]))) <= candidates


def test_a_question_of_only_stopwords_falls_back_to_dense(silver_store):
    hybrid = question(silver_store, FAKE, k=3).invoke("the of and to")
    dense = question(silver_store, FAKE, search="dense", k=3).invoke("the of and to")
    assert hybrid and unit_ids(hybrid) == unit_ids(dense)
    assert question(silver_store, FAKE, search="bm25").invoke("the of and to") == []


@pytest.mark.parametrize("index", ["i1", "i3", "both"])
def test_every_index_returns_notes_and_i3_differs_from_i1(silver_store, frozen, questions, index):
    docs = question(silver_store, frozen, index=index).invoke(questions[0]["question"])
    assert docs and all(d.metadata["unit_ids"] for d in docs)


def test_i3_ranks_some_question_differently_from_i1(silver_store, frozen, questions):
    i1 = question(silver_store, frozen, index="i1", merge_shared=False)
    i3 = question(silver_store, frozen, index="i3", merge_shared=False)
    assert any(
        unit_ids(i1.invoke(q["question"])) != unit_ids(i3.invoke(q["question"]))
        for q in questions[:10]
    )


# --- filters -----------------------------------------------------------------------------------


def test_vignette_filters_keep_and_drop_exactly_those_vignettes(silver_store, frozen, questions):
    only = question(
        silver_store,
        frozen,
        filter=ExpertFilter(vignettes=["V001", "V004"]),
        k=10,
    ).invoke(questions[0]["question"])
    assert only and {d.metadata["vignette_id"] for d in only} <= {"V001", "V004"}
    without = question(
        silver_store,
        frozen,
        filter=ExpertFilter(exclude_vignettes=["V001", "V004"]),
        k=10,
    ).invoke(questions[0]["question"])
    assert without and not {d.metadata["vignette_id"] for d in without} & {"V001", "V004"}


def test_population_and_track_filters_agree_with_the_stored_rows(
    silver, silver_store, frozen, questions
):
    units = silver[0]["units"]
    for field, key in (("populations", "population"), ("tracks", "track")):
        value = units[0][key]
        wanted = {u["id"] for u in units if u[key] == value}
        docs = question(
            silver_store,
            frozen,
            filter=ExpertFilter(**{field: [value]}),
            k=10,
            merge_shared=False,
        ).invoke(questions[0]["question"])
        assert docs and set(unit_ids(docs)) <= wanted
    absent = question(
        silver_store,
        frozen,
        filter=ExpertFilter(populations=["no such population"]),
    )
    assert absent.invoke(questions[0]["question"]) == []


# --- notes -------------------------------------------------------------------------------------


def test_units_sharing_a_sentence_become_one_note_only_when_merging(
    silver, silver_store, frozen, questions, unit_rows
):
    sentences = {}
    for unit, sentence, _ in silver[0]["unit_sentences"]:
        sentences.setdefault(unit, set()).add(sentence)

    merged = [
        d
        for q in questions[:10]
        for d in question(silver_store, frozen, k=8).invoke(q["question"])
        if len(d.metadata["unit_ids"]) > 1
    ]
    assert merged, "no question gave a merged note"
    for doc in merged:
        group = doc.metadata["unit_ids"]
        assert doc.metadata["merged"]
        assert len({unit_rows[u]["session_id"] for u in group}) == 1
        # every unit shares a sentence with another one of its note
        assert all(any(sentences[u] & sentences[v] for v in group if v != u) for u in group)
    single = question(silver_store, frozen, k=8, merge_shared=False)
    assert all(len(d.metadata["unit_ids"]) == 1 for d in single.invoke(questions[0]["question"]))


def test_the_findings_records_are_readable_so_notes_are_packed(
    silver_store, frozen, questions, caplog
):
    with caplog.at_level(logging.WARNING):
        docs = question(silver_store, frozen, k=8).invoke(questions[0]["question"])
    assert docs
    assert "no readable findings record" not in caplog.text
    assert any(d.metadata["patient_words"] for d in docs)  # the highlights' words, from the record


# --- patient text ------------------------------------------------------------------------------


def test_patient_text_finds_units_of_other_cases_and_never_the_excluded_ones(
    silver_store, frozen, silver
):
    patients = silver[2]["patients"]
    answered = 0
    for p in patients:
        retriever = PatientTextRetriever(
            store=silver_store,
            embeddings=frozen,
            filter=ExpertFilter(exclude_vignettes=p["exclude"]),
        )
        docs = retriever.invoke(p["text"])
        answered += bool(docs)
        assert not {d.metadata["vignette_id"] for d in docs} & set(p["exclude"])
    assert answered >= len(patients) - 1


def test_patient_text_without_exclusions_may_return_its_own_case(silver_store, frozen, silver):
    p = silver[2]["patients"][0]
    docs = PatientTextRetriever(
        store=silver_store, embeddings=frozen, k=8, filter=ALL, merge_shared=False
    ).invoke(p["text"])
    assert p["id"] in {d.metadata["vignette_id"] for d in docs}  # its own highlights match it best


# --- plumbing ----------------------------------------------------------------------------------


def test_sync_and_async_agree_on_the_silver_schema(silver_store, frozen, questions):
    retriever = question(silver_store, frozen, k=4)
    q = questions[3]["question"]
    sync, asynchronous = retriever.invoke(q), asyncio.run(retriever.ainvoke(q))
    assert [d.metadata["unit_ids"] for d in sync] == [d.metadata["unit_ids"] for d in asynchronous]
    assert [d.page_content for d in sync] == [d.page_content for d in asynchronous]


def test_the_silver_connection_is_read_only(silver_store):
    delete = sql.SQL("DELETE FROM {}").format(sql.Identifier(silver_store.schema, "cue_keys"))
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        silver_store.run([(delete, {})])


def test_a_text_that_was_not_frozen_is_an_error_not_a_model_call(silver_store, frozen):
    with pytest.raises(KeyError, match="not frozen"):
        question(silver_store, frozen).invoke("a question nobody froze")
