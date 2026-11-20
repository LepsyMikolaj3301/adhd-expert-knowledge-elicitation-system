"""LangChain retrievers over the expert knowledge database (notes/new-chips-knowledge.md, steps 8-9).

Two ways in, as in the evaluations:
  * ExpertQuestionRetriever  a clinician's question -> units (dense + BM25 over what was reviewed)
  * PatientTextRetriever     a new patient's text -> the cue keys of the highlights it resembles
                             -> the units about them

Both return packed notes: one Document per note, each sentence of an expert once, citations
rendered as short quotes, the patient's words and the expert's direction labels next to them.
"""

from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from expert_knowledge_core import bm25
from expert_knowledge_core.bm25 import Bm25Config
from expert_knowledge_core.notes import split_sentences
from expert_knowledge_core.retrieval import FUSION_DEPTH, RRF_K
from expert_knowledge_rag import sql
from expert_knowledge_rag.documents import build_documents
from expert_knowledge_rag.filters import ExpertFilter
from expert_knowledge_rag.ranking import (
    UnitHit,
    cue_scores,
    downweight_duplicate_cases,
    rank_by_cues,
)
from expert_knowledge_rag.store import ExpertKnowledgeStore, Rows


class _ExpertRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    store: ExpertKnowledgeStore
    # Must be the model the stored vectors were made with (bge-m3), or the dense search is noise.
    embeddings: Embeddings
    k: int = Field(4, ge=1)  # notes returned
    search: sql.Search = "hybrid"  # hybrid: dense + BM25 fused with RRF
    filter: ExpertFilter = Field(default_factory=ExpertFilter)
    merge_shared: bool = True  # units of one expert that share a sentence become one note
    # Matches config/indexing.yaml `sparse`: the query must be tokenised as the stored vectors were.
    bm25: Bm25Config = Field(default_factory=Bm25Config)
    fusion_depth: int = FUSION_DEPTH
    overfetch: int = Field(
        4, ge=1
    )  # units fetched per note wanted: merging and re-ranking shrink it

    # --- shared pieces ---------------------------------------------------------------------

    def _sparse(self, text: str) -> str | None:
        vector = bm25.query_vector(text, self.bm25)
        return vector.to_text() if vector is not None else None

    def _mode(self, sparse: str | None) -> sql.Search | None:
        """The search to run: a query with no BM25 terms (all stopwords) falls back to dense,
        and has nothing to match in a BM25-only search."""
        if sparse is not None or self.search == "dense":
            return self.search
        return "dense" if self.search == "hybrid" else None

    def _wants_dense(self) -> bool:
        return self.search != "bm25"

    def _vector(self, vector: list[float] | None) -> str | None:
        return self.store.vector_text(vector) if vector is not None else None

    def _hits(self, rows: Rows) -> list[UnitHit]:
        return [UnitHit.from_row(row) for row in rows]

    def _sessions_query(self, hits: list[UnitHit]) -> sql.Query:
        return sql.sessions(self.store.schema, sorted({h.session_id for h in hits}))

    def _documents(self, hits: list[UnitHit], session_rows: Rows, k: int) -> list[Document]:
        records: dict[str, Any] = {r["id"]: r["document"] for r in session_rows}
        return build_documents(hits, records, merge=self.merge_shared)[:k]


class ExpertQuestionRetriever(_ExpertRetriever):
    """A clinician's question -> notes. The evaluations chose the reviewed text (I1)."""

    # Generic case answers repeat across sessions; near-duplicates of a better one go last.
    downweight_duplicate_cases: bool = True

    def _query(self, query: str, vector: list[float] | None, k: int) -> sql.Query | None:
        sparse = self._sparse(query) if self.search != "dense" else None
        mode = self._mode(sparse)
        if mode is None:
            return None
        return sql.units_search(
            self.store.schema,
            search=mode,
            limit=k * self.overfetch,
            filter=self.filter,
            dense=self._vector(vector) if mode != "bm25" else None,
            sparse=sparse if mode != "dense" else None,
            depth=self.fusion_depth,
        )

    def _ranked(self, rows: Rows) -> list[UnitHit]:
        hits = self._hits(rows)
        return downweight_duplicate_cases(hits) if self.downweight_duplicate_cases else hits

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun, k: int | None = None
    ) -> list[Document]:
        k = self.k if k is None else k
        if not query.strip():
            return []
        vector = self.embeddings.embed_query(query) if self._wants_dense() else None
        units = self._query(query, vector, k)
        if units is None:
            return []
        hits = self._ranked(self.store.run([units])[0])
        if not hits:
            return []
        return self._documents(hits, self.store.run([self._sessions_query(hits)])[0], k)

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun, k: int | None = None
    ) -> list[Document]:
        k = self.k if k is None else k
        if not query.strip():
            return []
        vector = await self.embeddings.aembed_query(query) if self._wants_dense() else None
        units = self._query(query, vector, k)
        if units is None:
            return []
        hits = self._ranked((await self.store.arun([units]))[0])
        if not hits:
            return []
        return self._documents(hits, (await self.store.arun([self._sessions_query(hits)]))[0], k)


class PatientTextRetriever(_ExpertRetriever):
    """A new patient's text -> notes about the highlights it resembles.

    Every sentence searches the cue keys (the patient's words of the experts' highlights); a unit
    scores its cue's score plus a bonus for the cues cited together with it. Pass the case being
    read in `filter.exclude_vignettes` if it is itself a teaching case.
    """

    def _sentences(self, text: str) -> list[str]:
        sentences = [text[a:b].strip() for a, b in split_sentences(text)]
        return [s for s in sentences if s] or ([text.strip()] if text.strip() else [])

    def _cue_queries(
        self, sentences: list[str], vectors: list[list[float]] | None
    ) -> list[sql.Query]:
        queries = []
        for n, sentence in enumerate(sentences):
            sparse = self._sparse(sentence) if self.search != "dense" else None
            mode = self._mode(sparse)
            if mode is None:
                continue
            queries.append(
                sql.cues_search(
                    self.store.schema,
                    search=mode,
                    filter=self.filter,
                    dense=self._vector(vectors[n]) if mode != "bm25" and vectors else None,
                    sparse=sparse if mode != "dense" else None,
                    depth=self.fusion_depth,
                )
            )
        return queries

    def _scores(self, per_sentence: list[Rows]) -> dict[int, float]:
        return cue_scores([[r["cue_id"] for r in rows] for rows in per_sentence], RRF_K)

    def _units(self, rows: Rows, score: dict[int, float], k: int) -> list[UnitHit]:
        return rank_by_cues(rows, score)[: k * self.overfetch]

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun, k: int | None = None
    ) -> list[Document]:
        k = self.k if k is None else k
        sentences = self._sentences(query)
        if not sentences:
            return []
        vectors = self.embeddings.embed_documents(sentences) if self._wants_dense() else None
        queries = self._cue_queries(sentences, vectors)
        if not queries:
            return []
        score = self._scores(self.store.run(queries))
        if not score:
            return []
        rows = self.store.run([sql.units_for_cues(self.store.schema, list(score), self.filter)])[0]
        hits = self._units(rows, score, k)
        if not hits:
            return []
        return self._documents(hits, self.store.run([self._sessions_query(hits)])[0], k)

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun, k: int | None = None
    ) -> list[Document]:
        k = self.k if k is None else k
        sentences = self._sentences(query)
        if not sentences:
            return []
        vectors = await self.embeddings.aembed_documents(sentences) if self._wants_dense() else None
        queries = self._cue_queries(sentences, vectors)
        if not queries:
            return []
        score = self._scores(await self.store.arun(queries))
        if not score:
            return []
        rows = (
            await self.store.arun([sql.units_for_cues(self.store.schema, list(score), self.filter)])
        )[0]
        hits = self._units(rows, score, k)
        if not hits:
            return []
        return self._documents(hits, (await self.store.arun([self._sessions_query(hits)]))[0], k)
