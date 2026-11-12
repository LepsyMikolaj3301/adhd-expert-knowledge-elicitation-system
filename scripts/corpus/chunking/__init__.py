"""Chunking methods. See config/chunking.yaml for how to add one."""

from app.embeddings import OllamaEmbedder
from chunking.base import Chunk, Chunker, TokenCounter
from chunking.config import ChunkingConfig, load_chunking_config
from chunking.semantic import SemanticChunker

__all__ = ["Chunk", "Chunker", "ChunkingConfig", "build_chunker", "load_chunking_config"]


def build_chunker(cfg: ChunkingConfig) -> Chunker:
    count = TokenCounter(cfg.tokenizer)
    embedder = OllamaEmbedder(**cfg.embeddings.model_dump())
    # Add an `if cfg.method == "<name>": return ...` branch per new method.
    if cfg.method == "semantic":
        assert cfg.semantic is not None
        return SemanticChunker(cfg.semantic, embedder, count)
    raise ValueError(f"unknown chunking method {cfg.method!r}")
