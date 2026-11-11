"""What ingestion stores is what expert-knowledge-rag reads: after a real ingestion (the pipeline
of test_api_pipeline.py), the stored findings record is readable by the package and a retriever
over the same database returns the approved answers as packed notes.
"""

import json

from conftest import TEST_URL, FakeModels
from langchain_core.embeddings import Embeddings
from test_api_pipeline import chips, ingested_single

from expert_knowledge_core.records import is_readable
from expert_knowledge_rag import (
    ExpertFilter,
    ExpertKnowledgeStore,
    ExpertQuestionRetriever,
    PatientTextRetriever,
)
from expert_knowledge_rag.documents import local_id
from expert_knowledge_rag.ranking import UnitHit


class FakeEmbeddings(Embeddings):
    """The vectors `models` stores, so a query equal to a stored text finds it."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [FakeModels.vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return FakeModels.vector(text)


async def test_the_stored_document_is_readable_and_its_unit_ids_map_to_the_rows(models):
    await ingested_single(models)
    [(document,)] = await chips("SELECT document FROM chips.elicitation_sessions")
    document = document if isinstance(document, dict) else json.loads(document)
    assert is_readable(document)
    rows = await chips(
        "SELECT id, session_id, expert_id, vignette_id, vignette_version, kind, highlight_id, "
        "direction, is_synthetic, embed_text FROM chips.finding_units ORDER BY id"
    )
    columns = (
        "id", "session_id", "expert_id", "vignette_id", "vignette_version", "kind",
        "highlight_id", "direction", "is_synthetic", "embed_text",
    )  # fmt: skip
    hits = [UnitHit.from_row({**dict(zip(columns, r, strict=True)), "score": 1.0}) for r in rows]
    assert hits
    assert {local_id(h) for h in hits} == {u["id"] for u in document["units"]}


async def test_a_retriever_over_the_ingested_database_returns_the_approved_notes(models):
    await ingested_single(models)
    rows = await chips(
        "SELECT embed_text FROM chips.finding_units WHERE highlight_id IS NOT NULL ORDER BY id"
    )
    assert rows, "the ingested answers have a fragment unit"
    unit_text = rows[0][0]
    store = ExpertKnowledgeStore(TEST_URL)
    retriever = ExpertQuestionRetriever(
        store=store,
        embeddings=FakeEmbeddings(),
        k=3,
        search="dense",
        filter=ExpertFilter(include_synthetic=True),
    )
    # a query equal to a stored text has the same vector: that unit is the best hit
    docs = await retriever.ainvoke(unit_text)
    assert docs
    first = docs[0]
    assert first.page_content.startswith("Teaching case ")
    assert "Clinician's own words:" in first.page_content
    assert first.metadata["source"] == "expert" and first.metadata["unit_ids"]
    # the application's experts are real users unless marked synthetic: the default filter agrees
    default = await ExpertQuestionRetriever(
        store=store, embeddings=FakeEmbeddings(), search="dense"
    ).ainvoke(unit_text)
    assert [d.metadata["is_synthetic"] for d in default] == [False] * len(default)


async def test_patient_text_matching_a_stored_highlight_finds_its_units(models):
    await ingested_single(models)
    rows = await chips("SELECT text FROM chips.cue_keys ORDER BY id")
    assert rows, "the ingested answers have a highlight"
    cue_text = rows[0][0]
    docs = await PatientTextRetriever(
        store=ExpertKnowledgeStore(TEST_URL),
        embeddings=FakeEmbeddings(),
        search="dense",
        filter=ExpertFilter(include_synthetic=True),
    ).ainvoke(cue_text)
    assert docs and docs[0].metadata["patient_words"]
