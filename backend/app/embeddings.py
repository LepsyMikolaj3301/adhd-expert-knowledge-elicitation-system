"""Text embedding backends. Ollama is the only one for now; add others behind `Embedder`."""

from typing import Protocol

import httpx
import numpy as np

from app.settings import settings


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray:
        """One L2-normalized row per text."""
        ...


class OllamaEmbedder:
    def __init__(
        self, model: str, batch_size: int = 64, truncate: bool = True, base_url: str | None = None
    ) -> None:
        self.model = model
        self.batch_size = batch_size
        self.truncate = truncate
        self.client = httpx.Client(base_url=base_url or settings.ollama_base_url, timeout=300)

    def embed(self, texts: list[str]) -> np.ndarray:
        rows: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            resp = self.client.post(
                "/api/embed",
                json={
                    "model": self.model,
                    "input": texts[i : i + self.batch_size],
                    "truncate": self.truncate,
                },
            )
            if resp.status_code == 404:
                raise RuntimeError(
                    f"Ollama has no model {self.model!r}: run `ollama pull {self.model}`"
                )
            resp.raise_for_status()
            rows += resp.json()["embeddings"]
        vectors = np.asarray(rows, dtype=np.float32).reshape(len(texts), -1)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.maximum(norms, 1e-12)
