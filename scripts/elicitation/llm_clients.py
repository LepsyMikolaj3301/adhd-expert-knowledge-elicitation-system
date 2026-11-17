"""Text-generation sources behind one small interface, so tests can use a fake.

A request carries everything a model needs plus a stable `key` ("persona:S01",
"answer:V003:clean:P1").
- OllamaGenerator: a local Ollama (chat for instruct models, raw /api/generate for base models).
- FileGenerator:   reads a pre-written output from a folder, named by request key.
- InboxGenerator:  hands the request to a Claude agent: writes it to <dir>/requests/, reads the
                   agent's answer from <dir>/responses/. Never calls an API.
- CachedGenerator: wraps any generator and stores outputs under data/cache/.
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx


@dataclass(frozen=True)
class GenRequest:
    key: str
    user: str
    system: str | None = None
    raw: bool = False  # True: plain completion prompt for a base model (no chat template)
    json_mode: bool = False
    seed: int = 0
    options: dict = field(default_factory=dict)


class Generator(Protocol):
    name: str  # recorded in the manifest ("ollama:qwen3.5:9b", "file", ...)

    def generate(self, req: GenRequest) -> str: ...


class ModelRefused(Exception):
    """The model itself failed on this request (e.g. a repetition loop); a new seed may work."""


class AwaitingResponse(Exception):
    """An inbox request has no response yet."""


def request_digest(req: GenRequest, model: str) -> str:
    payload = json.dumps(
        [model, req.key, req.system, req.user, req.raw, req.json_mode, req.seed, req.options],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


class OllamaGenerator:
    attempts = 3  # per request: Ollama answers 500 now and then while it (re)loads a model
    retry_wait = 10.0

    def __init__(self, base_url: str, model: str, timeout: float | None = None, think=False):
        # one reply can include the model load; raise OLLAMA_REQUEST_TIMEOUT for big models
        timeout = timeout or float(os.environ.get("OLLAMA_REQUEST_TIMEOUT", 600))
        self.name = f"ollama:{model}"
        self.model = model
        self.think = think  # False for most models; gpt-oss cannot switch thinking off: "low"
        self._http = httpx.Client(base_url=base_url, timeout=timeout)

    def generate(self, req: GenRequest) -> str:
        options = {"seed": req.seed, **req.options}
        if req.raw:
            body = {"model": self.model, "prompt": req.user, "raw": True, "stream": False}
            path, pick = "/api/generate", lambda d: d["response"]
        else:
            messages = [{"role": "user", "content": req.user}]
            if req.system:
                messages.insert(0, {"role": "system", "content": req.system})
            body = {"model": self.model, "messages": messages, "stream": False, "think": self.think}
            if req.json_mode:
                body["format"] = "json"
            path, pick = "/api/chat", lambda d: d["message"]["content"]
        for attempt in range(self.attempts):
            try:
                r = self._http.post(path, json={**body, "options": options})
                r.raise_for_status()
                return pick(r.json())
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                if isinstance(e, httpx.HTTPStatusError) and "repeat limit" in e.response.text:
                    # Ollama aborts a repetition loop with a 500; the same seed loops again
                    raise ModelRefused(e.response.text) from e
                client_error = isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500
                if client_error or attempt == self.attempts - 1:
                    raise
                time.sleep(self.retry_wait * (attempt + 1))  # a model reload can fail once
        raise AssertionError("unreachable")


class FileGenerator:
    """Samples can carry a PROVENANCE.json ({"model": ...}) so rebuilds still say who wrote them."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.name = "file"
        provenance = directory / "PROVENANCE.json"
        if provenance.exists():
            self.name = f"file:{json.loads(provenance.read_text()).get('model', '?')}"

    def generate(self, req: GenRequest) -> str:
        stem = req.key.replace(":", ".")
        for ext in (".json", ".txt"):
            path = self.directory / f"{stem}{ext}"
            if path.exists():
                return path.read_text()
        raise FileNotFoundError(f"no sample input for {req.key} in {self.directory}")


class InboxGenerator:
    name = "claude-agent"

    def __init__(self, directory: Path):
        self.directory = directory

    def generate(self, req: GenRequest) -> str:
        stem = req.key.replace(":", ".")
        response = self.directory / "responses" / f"{stem}.json"
        if response.exists():
            return response.read_text()
        out = self.directory / "requests" / f"{stem}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"<!-- system -->\n{req.system or ''}\n\n<!-- user -->\n{req.user}\n")
        raise AwaitingResponse(f"{req.key}: write the reply to {response}")


class CachedGenerator:
    def __init__(self, inner: Generator, cache_dir: Path):
        self.inner = inner
        self.cache_dir = cache_dir
        self.name = inner.name

    def generate(self, req: GenRequest) -> str:
        path = self.cache_dir / f"{request_digest(req, self.inner.name)}.json"
        if path.exists():
            return json.loads(path.read_text())["output"]
        output = self.inner.generate(req)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"key": req.key, "model": self.inner.name, "output": output}, indent=1)
        )
        return output
