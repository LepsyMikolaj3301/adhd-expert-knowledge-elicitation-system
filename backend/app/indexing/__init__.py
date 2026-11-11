"""Indexing chunks into pgvector. See config/indexing.yaml."""

from app.embeddings import Embedder, OllamaEmbedder
from app.indexing.config import Bm25Config, IndexingConfig, load_indexing_config
from expert_knowledge_core import bm25

__all__ = ["Bm25Config", "IndexingConfig", "bm25", "build_embedder", "load_indexing_config"]


def build_embedder(cfg: IndexingConfig) -> Embedder:
    return OllamaEmbedder(**cfg.embeddings.model_dump(exclude={"dimensions"}))
