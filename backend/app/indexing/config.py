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


class IndexingConfig(Model):
    embeddings: IndexEmbeddingConfig
    text_field: Literal["contextual_text", "text"] = "contextual_text"

    def config_hash(self) -> str:
        """Hash of everything that changes the stored vectors."""
        payload = {"version": INDEXER_VERSION, **self.model_dump(mode="json")}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def load_indexing_config(path: Path) -> IndexingConfig:
    return IndexingConfig.model_validate(yaml.safe_load(path.read_text()))
