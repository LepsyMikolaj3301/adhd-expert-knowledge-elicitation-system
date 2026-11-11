"""bge-m3 through Ollama: the embedding model the stored vectors were made with.

Needs the `ollama` extra: `pip install expert-knowledge-rag[ollama]`.
"""

from typing import Any

from expert_knowledge_core.retrieval import EMBEDDING_MODEL


def default_embeddings(base_url: str = "http://localhost:11434", **kwargs: Any) -> Any:
    """`OllamaEmbeddings` for bge-m3, to pass as `embeddings=` to the retrievers."""
    from langchain_ollama import OllamaEmbeddings  # ty: ignore[unresolved-import]

    return OllamaEmbeddings(model=EMBEDDING_MODEL, base_url=base_url, **kwargs)
