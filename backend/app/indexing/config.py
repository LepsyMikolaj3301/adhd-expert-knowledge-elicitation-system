"""Typed model of config/indexing.yaml (embedding model for the pgvector index)."""

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from app.chunking.config import EmbeddingConfig, Model

# Bump when the indexed rows change for the same config, so documents are re-indexed.
INDEXER_VERSION = "1"


class IndexEmbeddingConfig(EmbeddingConfig):
    dimensions: int = Field(gt=0)


class Bm25Config(Model):
    k1: float = Field(1.2, gt=0)
    b: float = Field(0.75, ge=0, le=1)
    stemmer: str | None = "english"  # a Snowball language, or null for no stemming


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
