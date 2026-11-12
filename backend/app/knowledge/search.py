"""The admin's test search: the platform's own retrievers over the ingested units.

It runs `expert-knowledge-rag`, the package an answering application would use, so a hit here is
a hit there. Each hit is mapped back to the application's unit row (what the admin reviewed), and
given a similarity the retrievers don't report: the cosine between the query's embedding and the
stored one, which is a number an admin can read where the fusion score is only an ordering.
"""

from uuid import UUID

import httpx
import numpy as np
from langchain_core.embeddings import Embeddings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import database_url
from app.core.errors import DomainError
from app.knowledge import embedding
from app.knowledge.models import KnowledgeUnit, UnitStatus
from app.knowledge.schemas import (
    KnowledgeHit,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.knowledge.service import unit_items
from expert_knowledge_core.records import CASE
from expert_knowledge_rag import (
    ExpertFilter,
    ExpertKnowledgeStore,
    ExpertQuestionRetriever,
    PatientTextRetriever,
)

UNAVAILABLE = DomainError(
    "embedding_unavailable",
    "The embedding model can't be reached, so search is off right now.",
    503,
)


class _Embeddings(Embeddings):
    """The application's embedder as a LangChain one, remembering what it embedded.

    Only the async methods are used (the retrievers are called with `ainvoke`). The embedder is
    looked up on the module at call time, so that tests can replace it.
    """

    def __init__(self) -> None:
        self.queries: dict[str, list[float]] = {}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("use aembed_documents")

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError("use aembed_query")

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = await embedding.embed_texts(texts)
        except (httpx.HTTPError, OSError, RuntimeError) as exc:
            # Ollama unreachable, bge-m3 not pulled (RuntimeError), or the wrong vector width.
            raise UNAVAILABLE from exc
        self.queries.update(zip(texts, vectors, strict=True))
        return vectors

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]


def _cosine(a: list[float], b: list[float]) -> float:
    x, y = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return float(x @ y / max(float(np.linalg.norm(x) * np.linalg.norm(y)), 1e-12))


def _parse(vector: str) -> list[float]:
    return [float(v) for v in vector.strip("[]").split(",")]


def _retriever(
    request: KnowledgeSearchRequest, embeddings: _Embeddings
) -> ExpertQuestionRetriever | PatientTextRetriever:
    # shortcut: one connection per search, no pool. Fine for an admin's test tool.
    store = ExpertKnowledgeStore(database_url())
    # Every test search is of units the admin can see, so the experts' test accounts count.
    allowed = ExpertFilter(include_synthetic=True)
    # merge_shared=False: one hit per unit. Merging units that share a sentence is for the
    # generator's prompt, and would hide which unit matched.
    if request.mode == "patient_text":
        return PatientTextRetriever(
            store=store, embeddings=embeddings, k=request.k, filter=allowed, merge_shared=False
        )
    return ExpertQuestionRetriever(
        store=store, embeddings=embeddings, k=request.k, filter=allowed, merge_shared=False
    )


async def search(db: AsyncSession, request: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
    embeddings = _Embeddings()
    notes = await _retriever(request, embeddings).ainvoke(request.query)
    if not notes:
        return KnowledgeSearchResponse(hits=[])

    # The chips id is <assignment>-<case code>-<local id>; the local id is the highlight or `case`.
    wanted: list[tuple[str, str | None]] = []
    for note in notes:
        meta = note.metadata
        prefix = f"{meta['session_id']}-{meta['vignette_id']}-"
        local = meta["unit_ids"][0][len(prefix) :]
        wanted.append((meta["session_id"], None if local == CASE else local))
    items = await unit_items(
        db,
        KnowledgeUnit.status == UnitStatus.INGESTED,
        KnowledgeUnit.assignment_id.in_([UUID(a) for a in {a for a, _ in wanted}]),
    )
    by_key = {(str(i.assignment_id), i.highlight_id): i for i in items}

    similarity, matched = await _similarities(db, request, embeddings, notes)
    hits = []
    for note, key in zip(notes, wanted, strict=True):
        unit = by_key.get(key)
        if unit is None:  # replaced by a later ingestion while the search ran
            continue
        unit_id = note.metadata["unit_ids"][0]
        hits.append(
            KnowledgeHit(
                rank=len(hits) + 1,
                score=float(note.metadata["score"]),
                similarity=similarity.get(unit_id),
                matched_sentence=matched.get(unit_id),
                unit=unit,
            )
        )
    return KnowledgeSearchResponse(hits=hits)


async def _similarities(
    db: AsyncSession, request: KnowledgeSearchRequest, embeddings: _Embeddings, notes
) -> tuple[dict[str, float], dict[str, str]]:
    """Cosine per hit. Question mode: the query against the unit's reviewed text (I1). Patient
    mode: each typed sentence against the unit's cue (the patient's words an expert highlighted);
    the best sentence wins and is named."""
    ids = [n.metadata["unit_ids"][0] for n in notes]
    if request.mode == "question":
        query = embeddings.queries.get(request.query)
        if query is None:
            return {}, {}
        rows = await db.execute(
            text("SELECT id, embedding::text FROM chips.finding_units WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
        return {i: _cosine(query, _parse(v)) for i, v in rows}, {}

    rows = await db.execute(
        text(
            "SELECT uc.unit_id, c.embedding::text FROM chips.unit_cues uc "
            "JOIN chips.cue_keys c ON c.id = uc.cue_key_id "
            "WHERE uc.role = 'cue' AND uc.unit_id = ANY(:ids)"
        ),
        {"ids": ids},
    )
    similarity: dict[str, float] = {}
    matched: dict[str, str] = {}
    for unit_id, vector in rows:
        cue = _parse(vector)
        best = max(embeddings.queries.items(), key=lambda q: _cosine(q[1], cue))
        similarity[unit_id], matched[unit_id] = _cosine(best[1], cue), best[0]
    return similarity, matched
