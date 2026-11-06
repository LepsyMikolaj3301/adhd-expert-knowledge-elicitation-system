"""Embedding texts with the model of config/indexing.yaml (bge-m3). Tests replace `embed_texts`."""

import asyncio
from functools import lru_cache

from app.embeddings import Embedder
from app.indexing import build_embedder, load_indexing_config
from app.settings import settings


@lru_cache
def _embedder() -> tuple[Embedder, int]:
    config = load_indexing_config(settings.project_root / "config" / "indexing.yaml")
    return build_embedder(config), config.embeddings.dimensions


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """One L2-normalised vector per text, as lists of floats. Runs the blocking HTTP client in a
    thread, so the heartbeat keeps the job's lease alive meanwhile."""
    if not texts:
        return []
    embedder, dimensions = _embedder()
    vectors = await asyncio.to_thread(embedder.embed, texts)
    if vectors.shape != (len(texts), dimensions):
        raise RuntimeError(f"the embedder returned {vectors.shape}, wanted {dimensions} columns")
    return vectors.tolist()
