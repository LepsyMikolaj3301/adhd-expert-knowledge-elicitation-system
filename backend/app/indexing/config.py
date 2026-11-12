"""Typed model of config/indexing.yaml (embedding model for the pgvector index)."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from expert_knowledge_core.bm25 import Bm25Config  # BM25 query and stored vectors share it


class Model(BaseModel):
    # Reject unknown keys so a typo in the YAML fails on load instead of mid-run.
    model_config = ConfigDict(extra="forbid")


class EmbeddingConfig(Model):
    model: str
    batch_size: int = Field(64, gt=0)
    truncate: bool = True


class IndexEmbeddingConfig(EmbeddingConfig):
    dimensions: int = Field(gt=0)


class IndexingConfig(Model):
    embeddings: IndexEmbeddingConfig
    text_field: Literal["contextual_text", "text"] = "contextual_text"
    sparse: Bm25Config = Bm25Config()


def load_indexing_config(path: Path) -> IndexingConfig:
    return IndexingConfig.model_validate(yaml.safe_load(path.read_text()))
