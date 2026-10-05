"""Shared helpers for chunk_documents.py and evaluate_chunks.py."""

import hashlib
import json
import os
import re
import sqlite3
import sys
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np

CHUNKS_DIR = Path("/workspace/data/chunks")
STRATEGY_DIRS = {"hybrid": "docling_hybrid", "recursive": "recursive", "semantic": "semantic"}
TOKENIZER = "BAAI/bge-m3"
EMBED_MODEL = "bge-m3"
LLM_MODEL = "qwen3:8b"
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# A sentence ends at .?! (plus closing quotes/brackets) followed by whitespace and a capital,
# digit or opening quote, unless the word before the period is a known abbreviation or an initial.
_BOUNDARY = re.compile(r"([.!?][\"')\]]*)\s+(?=[A-Z0-9\"'(\[])|(\n+)")
_ABBREV = re.compile(
    r"(?:\bet al|\be\.g|\bi\.e|\bFigs?|\bEqs?|\bvs|\bcf|\bDr|\bProf|\bNo|\bpp|\b[A-Z])\.$"
)


@lru_cache(maxsize=1)
def hf_tokenizer():
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(TOKENIZER)
    tok.model_max_length = 10**9  # silence the "sequence too long" warning, we only count
    return tok


def count_tokens(text: str) -> int:
    return len(hf_tokenizer()(text, add_special_tokens=False)["input_ids"])


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return (start, end) char spans of sentences; newlines always end a sentence."""
    spans, cursor = [], 0
    for m in _BOUNDARY.finditer(text):
        if m.group(1):
            if _ABBREV.search(text[max(0, m.start(1) - 12) : m.start(1) + 1]):
                continue
            end = m.end(1)
        else:
            end = m.start(2)
        if text[cursor:end].strip():
            spans.append((cursor, end))
        cursor = m.end()
    if text[cursor:].strip():
        spans.append((cursor, len(text)))
    return spans


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


class OllamaClient:
    """Embeddings (cached on disk) and JSON-schema constrained chat against a local Ollama."""

    def __init__(self, cache_path: Path = CHUNKS_DIR / ".cache" / "embeddings.sqlite"):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.http = httpx.Client(base_url=OLLAMA_URL, timeout=600)
        self.db = sqlite3.connect(cache_path)
        self.db.execute("CREATE TABLE IF NOT EXISTS emb (key TEXT PRIMARY KEY, vec BLOB)")

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha1(f"{EMBED_MODEL}\0{text}".encode()).hexdigest()

    def embed(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        """L2-normalised embeddings, one row per input text."""
        keys = [self._key(t) for t in texts]
        unique = dict(zip(keys, texts, strict=True))
        have: dict[str, np.ndarray] = {}
        wanted = list(unique)
        for i in range(0, len(wanted), 500):
            part = wanted[i : i + 500]
            rows = self.db.execute(
                f"SELECT key, vec FROM emb WHERE key IN ({','.join('?' * len(part))})", part
            )
            have.update({k: np.frombuffer(v, dtype=np.float32) for k, v in rows})
        missing = [k for k in unique if k not in have]
        if missing:
            print(f"  embedding {len(missing)} new texts with {EMBED_MODEL}", file=sys.stderr)
        for i in range(0, len(missing), batch_size):
            batch = missing[i : i + batch_size]
            resp = self.http.post(
                "/api/embed",
                json={
                    "model": EMBED_MODEL,
                    "input": [unique[k] for k in batch],
                    "options": {"num_ctx": 8192},
                },
            )
            resp.raise_for_status()
            for k, v in zip(batch, resp.json()["embeddings"], strict=True):
                vec = np.asarray(v, dtype=np.float32)
                vec /= np.linalg.norm(vec)
                have[k] = vec
                self.db.execute("INSERT OR REPLACE INTO emb VALUES (?, ?)", (k, vec.tobytes()))
            self.db.commit()
        if not keys:
            return np.zeros((0, 1), dtype=np.float32)
        return np.stack([have[k] for k in keys])

    def chat_json(self, prompt: str, schema: dict) -> dict:
        resp = self.http.post(
            "/api/chat",
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0},
            },
        )
        resp.raise_for_status()
        return json.loads(resp.json()["message"]["content"])
