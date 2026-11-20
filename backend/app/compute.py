"""Is the machine with the models up? Ollama and LanguageTool run on the owner's PC, not on the
server that hosts the API (notes/deployment.md). Switched on by REQUIRE_COMPUTE; development and the
tests leave it off.

Two places ask:
- the API, before a request queues a job: a 503 `compute_unavailable` instead of a job that can't
  run. It reads the last probe, which `watch()` (started with the app) renews in the background, so
  no request waits on the network while it holds the assignment's row lock.
- the worker, before it claims a job and after one fails: a job whose machine is down stays queued,
  and a failure while it is down does not use up an attempt (app/jobs/worker.py). That also covers
  the PC going off after the request was let through.
"""

import asyncio
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache

import httpx

from app.core.errors import DomainError, safe_traceback
from app.indexing import load_indexing_config
from app.jobs.models import JobKind
from app.settings import settings

logger = logging.getLogger(__name__)
TIMEOUT = 3.0
WATCH_EVERY = 10.0  # seconds between the API's background probes
API_TRUSTS = 30.0  # an older probe (the watcher stuck or not started) is redone by the request
WORKER_TRUSTS = 15.0
# What runs after a job of this kind without a person in between: approving answers ends in
# ingestion, so the request that queues the cutting checks the embedding model too.
FOLLOWED_BY = {JobKind.PROCESS: JobKind.INGEST}


def client(base_url: str) -> httpx.AsyncClient:
    """Tests replace this with a client that has a mock transport."""
    return httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT)


@cache
def _embedding_model() -> str:
    return load_indexing_config(settings.project_root / "config" / "indexing.yaml").embeddings.model


def _models(kind: JobKind) -> list[str]:
    """The Ollama models a job of this kind calls. Cutting into units (PROCESS) calls none."""
    if kind == JobKind.PROOFREAD:
        wanted = [settings.classifier_model, settings.enhance_model]  # empty enhance: switched off
        return [model for model in wanted if model]
    if kind == JobKind.INGEST:
        return [_embedding_model()]
    return []


def needs_compute(kind: JobKind) -> bool:
    return bool(_models(kind)) or kind == JobKind.PROOFREAD


@dataclass(frozen=True)
class Probe:
    at: float  # time.monotonic()
    models: frozenset[str] | None  # what Ollama has pulled; None: Ollama can't be reached
    languagetool: bool


_last: Probe | None = None


def forget() -> None:
    """Drop the last probe: the next check asks the PC again."""
    global _last
    _last = None


async def _ollama() -> frozenset[str] | None:
    try:
        async with client(settings.ollama_base_url) as http:
            response = await http.get("/api/tags")
            response.raise_for_status()
            return frozenset(entry["name"] for entry in response.json()["models"])
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return None


async def _languagetool() -> bool:
    try:
        async with client(settings.languagetool_url) as http:
            (await http.get("/v2/languages")).raise_for_status()
    except httpx.HTTPError:
        return False
    return True


async def probe() -> Probe:
    global _last
    models, languagetool = await asyncio.gather(_ollama(), _languagetool())
    _last = Probe(time.monotonic(), models, languagetool)
    return _last


async def _recent(max_age: float) -> Probe:
    last = _last
    if last is None or time.monotonic() - last.at > max_age:
        return await probe()
    return last


def _pulled(name: str, available: frozenset[str]) -> bool:
    """`bge-m3` is the model Ollama lists as `bge-m3:latest`."""
    return name in available or (":" not in name and f"{name}:latest" in available)


def _missing(seen: Probe, kinds: Iterable[JobKind]) -> list[str]:
    kinds = list(kinds)
    models = list(dict.fromkeys(model for kind in kinds for model in _models(kind)))
    missing = []
    if models:
        if seen.models is None:
            missing.append("ollama")
        else:
            missing += [f"model {name}" for name in models if not _pulled(name, seen.models)]
    if JobKind.PROOFREAD in kinds and not seen.languagetool:
        missing.append("languagetool")
    return missing


def _describe(missing: str) -> str:
    if missing == "ollama":
        return "Ollama can't be reached"
    if missing == "languagetool":
        return "LanguageTool can't be reached"
    return f"Ollama has no {missing}"


async def require_compute(kind: JobKind) -> None:
    """Raises 503 `compute_unavailable` when what a job of this kind (and what follows it) needs
    can't be used."""
    if not settings.require_compute:
        return
    kinds = [kind] + ([FOLLOWED_BY[kind]] if kind in FOLLOWED_BY else [])
    if not any(needs_compute(k) for k in kinds):
        return
    missing = _missing(await _recent(API_TRUSTS), kinds)
    if missing:
        raise DomainError(
            "compute_unavailable",
            "The computer that checks answers is not ready ("
            + "; ".join(_describe(item) for item in missing)
            + "). Try again later.",
            503,
            {"missing": missing},
        )


async def ready_kinds() -> set[JobKind] | None:
    """The job kinds the worker can run now; None: all of them (the check is off)."""
    if not settings.require_compute:
        return None
    seen = await _recent(WORKER_TRUSTS)
    return {kind for kind in JobKind if not _missing(seen, [kind])}


async def is_down_for(kind: JobKind) -> bool:
    """After a job failed: was it because the PC is down? Asks the PC again, now."""
    if not settings.require_compute or not needs_compute(kind):
        return False
    return bool(_missing(await probe(), [kind]))


async def latest() -> Probe | None:
    """The last probe, for the admin's status. None: the check is off (REQUIRE_COMPUTE)."""
    if not settings.require_compute:
        return None
    return await _recent(API_TRUSTS)


def missing_now(seen: Probe) -> list[str]:
    """Everything any job needs that the PC doesn't offer, e.g. ["ollama", "languagetool"]."""
    return _missing(seen, list(JobKind))


def blocked(seen: Probe, kind: JobKind) -> bool:
    """A job of this kind can't run on what the probe saw."""
    return bool(_missing(seen, [kind]))


async def watch() -> None:
    """The API's background probe. Runs until cancelled."""
    while True:
        try:
            await probe()
        except Exception as exc:  # never let the watcher die: requests would then probe inline
            logger.error("compute probe failed\n%s", safe_traceback(exc))
        await asyncio.sleep(WATCH_EVERY)
