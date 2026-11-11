"""Typed model of config/indexing.yaml (embedding model for the pgvector index)."""

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from app.chunking.config import EmbeddingConfig, Model
from expert_knowledge_core.bm25 import Bm25Config  # BM25 query and stored vectors share it

# Bump when the indexed rows change for the same config, so documents are re-indexed.
INDEXER_VERSION = "1"


class IndexEmbeddingConfig(EmbeddingConfig):
    dimensions: int = Field(gt=0)


class IndexingConfig(Model):
    embeddings: IndexEmbeddingConfig
    text_field: Literal["contextual_text", "text"] = "contextual_text"
    sparse: Bm25Config = Bm25Config()

    def config_hash(self) -> str:
        """Hash of everything that changes the stored dense vectors. `sparse` is left out: the
        BM25 weights are refitted over the whole corpus on every index run, so changing them
        never needs a re-embedding."""
        payload = {"version": INDEXER_VERSION, **self.model_dump(mode="json", exclude={"sparse"})}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def load_indexing_config(path: Path) -> IndexingConfig:
    return IndexingConfig.model_validate(yaml.safe_load(path.read_text()))
