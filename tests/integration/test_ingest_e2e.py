"""The indexing side, end to end: answers -> units -> bge-m3 vectors -> schema -> search.

The regression tests measure ranking; these check that what ingestion writes is what search reads:
every built row is in the schema, BM25 and the vectors are there, a unit's own text finds that unit
(the ingestion and the question go through the same embedder), a patient's words find the units of
their highlight, and every labelled claim is held by a unit that exists.
"""

import chips_fixture
import pytest
from psycopg import sql

from expert_knowledge_rag import ExpertFilter, ExpertQuestionRetriever, PatientTextRetriever

pytestmark = [pytest.mark.integration, pytest.mark.regression]

SAMPLE = 25  # units searched by their own text


def count(store, query: str) -> int:
    (rows,) = store.run([(sql.SQL(query).format(s=sql.Identifier(store.schema)), {})])
    return next(iter(rows[0].values()))


def test_the_schema_holds_every_built_row_with_its_vectors_and_bm25(silver, silver_store, embedder):
    tables = silver.tables
    assert count(silver_store, "SELECT count(*) FROM {s}.finding_units") == len(tables["units"])
    assert count(silver_store, "SELECT count(*) FROM {s}.cue_keys") == len(tables["cue_keys"])
    assert count(silver_store, "SELECT count(*) FROM {s}.elicitation_sessions") == len(
        tables["sessions"]
    )
    assert count(silver_store, "SELECT count(*) FROM {s}.answer_sentences") == len(
        tables["sentences"]
    )
    for table in ("finding_units", "cue_keys"):
        missing = count(
            silver_store,
            f"SELECT count(*) FROM {{s}}.{table} WHERE embedding IS NULL OR sparse IS NULL",
        )
        assert missing == 0, table
        width = count(silver_store, f"SELECT max(vector_dims(embedding)) FROM {{s}}.{table}")
        assert width == embedder.dimensions, table


def test_a_unit_found_by_its_own_text_comes_first(silver, silver_store, embedder):
    units = silver.tables["units"]
    sample = units[:: max(1, len(units) // SAMPLE)][:SAMPLE]
    retriever = ExpertQuestionRetriever(
        store=silver_store,
        embeddings=embedder,
        filter=ExpertFilter(),
        k=1,
        search="dense",
        merge_shared=False,
    )
    text_of = {u["id"]: u["embed_text"] for u in units}
    wrong = []
    for unit in sample:
        (doc,) = retriever.invoke(unit["embed_text"])
        (found,) = doc.metadata["unit_ids"]
        if text_of[found] != unit["embed_text"]:  # a twin with the same text may come first
            wrong.append(unit["id"])
    assert not wrong, wrong


def passages(silver, retriever, n: int = 10) -> list[tuple[dict, str]]:
    """(highlight, its cue key's text) for n expert highlights whose words are one sentence."""
    cues = silver.tables["cue_keys"]
    one = [
        (h, cues[h["cue_key"]]["text"])
        for h in silver.tables["highlights"]
        if h["origin"] == "expert" and len(retriever._sentences(cues[h["cue_key"]]["text"])) == 1
    ]
    return one[:: max(1, len(one) // n)][:n]


def test_a_highlighted_passage_finds_its_own_cue_key_first(silver, silver_store, embedder):
    """The cue keys' vectors and BM25 are written so that the patient's exact words match them."""
    retriever = PatientTextRetriever(store=silver_store, embeddings=embedder, filter=ExpertFilter())
    text_of_id = {
        r["id"]: r["text"]
        for r in silver_store.run(
            [
                (
                    sql.SQL("SELECT id, text FROM {}").format(
                        sql.Identifier(silver_store.schema, "cue_keys")
                    ),
                    {},
                )
            ]
        )[0]
    }
    for h, text in passages(silver, retriever):
        (rows,) = silver_store.run(retriever._cue_queries([text], embedder.embed_documents([text])))
        assert text_of_id[rows[0]["cue_id"]] == text, h["id"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="known ranking weakness: RRF scores with RRF_K=60 are nearly flat, so CONTEXT_BONUS "
    "(0.5 per co-cited cue that matched anywhere) outweighs an exact match; a unit of another "
    "vignette with two loosely matching context cues outranks the passage's own units",
)
def test_a_highlighted_passage_ranks_the_units_of_its_vignette_in_the_top_4(
    silver, silver_store, embedder
):
    retriever = PatientTextRetriever(
        store=silver_store, embeddings=embedder, filter=ExpertFilter(), k=4, merge_shared=False
    )
    for h, text in passages(silver, retriever):
        docs = retriever.invoke(text)
        assert h["vignette_id"] in {d.metadata["vignette_id"] for d in docs}, h["id"]


def test_every_labelled_claim_is_held_by_a_unit_that_exists(silver):
    ids = {u["id"] for u in silver.tables["units"]}
    covers = silver.queries["covers"]
    for q in silver.queries["questions"]:
        for claim in q["pooled_ids"]:
            assert covers[claim], claim
            assert set(covers[claim]) <= ids, claim


def test_building_again_gives_the_same_rows():
    answers = chips_fixture.load(experts=chips_fixture.SILVER_EXPERTS)
    first = chips_fixture.tables_of(answers, chips_fixture.build(answers))
    again = chips_fixture.tables_of(answers, chips_fixture.build(answers))
    assert first == again
