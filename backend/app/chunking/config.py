"""Typed model of config/chunking.yaml (chunking method + hyperparameters)."""

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bump when a chunker's output changes for the same config, so outputs are redone.
CHUNKER_VERSION = "1"


class Model(BaseModel):
    # Reject unknown keys so a typo in the YAML fails on load instead of mid-run.
    model_config = ConfigDict(extra="forbid")


class DocumentFilter(Model):
    skip_roles: list[str] = []


class EmbeddingConfig(Model):
    model: str
    batch_size: int = Field(64, gt=0)
    truncate: bool = True


class BreakpointConfig(Model):
    type: Literal["percentile", "std_dev", "interquartile", "gradient"] = "percentile"
    amount: float = 90


class SemanticConfig(Model):
    sentence_split: bool = True
    buffer_size: int = Field(1, ge=0)
    breakpoint: BreakpointConfig = BreakpointConfig()
    min_tokens: int = Field(80, ge=0)
    max_tokens: int = Field(512, gt=0)
    respect_sections: bool = True
    merge_scope_level: int = Field(1, ge=0)
    contextual_header: bool = True

    @model_validator(mode="after")
    def _min_below_max(self) -> "SemanticConfig":
        if self.min_tokens > self.max_tokens:
            raise ValueError("min_tokens must not exceed max_tokens")
        return self


class ChunkingConfig(Model):
    method: Literal["semantic"]
    documents: DocumentFilter = DocumentFilter()
    embeddings: EmbeddingConfig
    tokenizer: str | None = None
    semantic: SemanticConfig | None = None

    @model_validator(mode="after")
    def _method_block_present(self) -> "ChunkingConfig":
        if getattr(self, self.method) is None:
            raise ValueError(f"method {self.method!r} needs a `{self.method}:` block")
        return self

    def method_config(self) -> BaseModel:
        return getattr(self, self.method)

    def config_hash(self) -> str:
        """Hash of everything that changes the chunks (not of the document filter)."""
        payload = {
            "version": CHUNKER_VERSION,
            "method": self.method,
            "params": self.method_config().model_dump(mode="json"),
            "embeddings": self.embeddings.model_dump(mode="json"),
            "tokenizer": self.tokenizer,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def load_chunking_config(path: Path) -> ChunkingConfig:
    return ChunkingConfig.model_validate(yaml.safe_load(path.read_text()))
