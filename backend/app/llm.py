"""Thin helpers for talking to the Ollama HTTP API (https://github.com/ollama/ollama/blob/main/docs/api.md)."""

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx

from app.settings import settings

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": "..."}

# Local models can be slow on first load, so allow a generous read timeout.
TIMEOUT = httpx.Timeout(10.0, read=300.0)


def _url(path: str) -> str:
    return f"{settings.ollama_base_url.rstrip('/')}{path}"


def list_models() -> list[str]:
    """Names of models already pulled into Ollama."""
    r = httpx.get(_url("/api/tags"), timeout=TIMEOUT)
    r.raise_for_status()
    return [m["name"] for m in r.json()["models"]]


def generate(
    prompt: str,
    *,
    model: str | None = None,
    system: str | None = None,
    options: dict[str, Any] | None = None,
) -> str:
    """Single-turn completion. `options` takes Ollama params, e.g. {"temperature": 0.2, "num_ctx": 4096}."""
    payload: dict[str, Any] = {
        "model": model or settings.ollama_model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options
    r = httpx.post(_url("/api/generate"), json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["response"].strip()


def chat(
    messages: list[Message],
    *,
    model: str | None = None,
    options: dict[str, Any] | None = None,
    format: str | dict[str, Any] | None = None,
) -> str:
    """Multi-turn chat. `format="json"` or a JSON schema dict forces structured output."""
    payload: dict[str, Any] = {
        "model": model or settings.ollama_model,
        "messages": messages,
        "stream": False,
    }
    if options:
        payload["options"] = options
    if format:
        payload["format"] = format
    r = httpx.post(_url("/api/chat"), json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def chat_stream(
    messages: list[Message],
    *,
    model: str | None = None,
    options: dict[str, Any] | None = None,
    stats: dict[str, Any] | None = None,
) -> Iterator[str]:
    """Yield the reply chunk by chunk (Ollama streams newline-delimited JSON).

    If `stats` is given, it's filled with the final chunk's metadata
    (prompt_eval_count, eval_count, done_reason, timings).
    """
    payload: dict[str, Any] = {
        "model": model or settings.ollama_model,
        "messages": messages,
        "stream": True,
    }
    if options:
        payload["options"] = options
    with httpx.stream("POST", _url("/api/chat"), json=payload, timeout=TIMEOUT) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            yield chunk["message"]["content"]
            if chunk.get("done"):
                if stats is not None:
                    stats.update({k: v for k, v in chunk.items() if k != "message"})
                break


async def achat(
    messages: list[Message],
    *,
    model: str | None = None,
    options: dict[str, Any] | None = None,
) -> str:
    """Async `chat`, for use inside FastAPI endpoints."""
    payload: dict[str, Any] = {
        "model": model or settings.ollama_model,
        "messages": messages,
        "stream": False,
    }
    if options:
        payload["options"] = options
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(_url("/api/chat"), json=payload)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


async def achat_stream(
    messages: list[Message],
    *,
    model: str | None = None,
) -> AsyncIterator[str]:
    """Async streaming chat, e.g. for a FastAPI StreamingResponse."""
    payload = {"model": model or settings.ollama_model, "messages": messages, "stream": True}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", _url("/api/chat"), json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                yield chunk["message"]["content"]
                if chunk.get("done"):
                    break


def embed(texts: str | list[str], *, model: str) -> list[list[float]]:
    """Embeddings for pgvector. Needs an embedding model, e.g. `ollama pull nomic-embed-text`."""
    r = httpx.post(_url("/api/embed"), json={"model": model, "input": texts}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["embeddings"]


if __name__ == "__main__":
    print("models:", list_models())
    print("generate:", generate("Wymień trzy objawy ADHD.", options={"temperature": 0.2}))
    history: list[Message] = [
        {"role": "system", "content": "Jesteś ekspertem od ADHD. Odpowiadaj krótko."},
        {"role": "user", "content": "Czym jest hiperfokus?"},
    ]
    print("chat:", chat(history))
    print("stream: ", end="")
    for piece in chat_stream([{"role": "user", "content": "Policz od 1 do 5."}]):
        print(piece, end="", flush=True)
    print()
