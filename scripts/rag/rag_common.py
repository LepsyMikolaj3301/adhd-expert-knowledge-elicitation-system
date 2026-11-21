"""Shared helpers of the expert-notes RAG scripts (eval_expert_*.py, eval_chip_*.py, chat_expert.py,
judge_generations.py, chips_fixture.py).

The query embedder and BM25 settings of config/indexing.yaml, generation with an Ollama chat model
and the clinician judge rubric. Not a backend module on purpose: the scripts import it as
`rag_common` (their folder, scripts/rag/, is on sys.path when they run as
`python scripts/rag/x.py`).
"""

import json
import re
import time
from pathlib import Path

import httpx

from app.embeddings import Embedder
from app.indexing import Bm25Config, build_embedder, load_indexing_config
from app.settings import settings
from expert_knowledge_core.prompts import (
    NOT_IN_SOURCES,  # noqa: F401  (scripts import it from here)
)
from expert_knowledge_core.retrieval import FUSION_DEPTH, RRF_K  # noqa: F401

GENERATION_OPTIONS = {"temperature": 0, "num_ctx": 8192, "num_predict": 600}


def query_embedder(config: Path = Path("config/indexing.yaml")) -> Embedder:
    """The embedder the units were indexed with, so queries land in the same space."""
    return build_embedder(load_indexing_config(config))


def bm25_config(config: Path = Path("config/indexing.yaml")) -> Bm25Config:
    return load_indexing_config(config).sparse


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


# --------------------------------------------------------------------------- generation


class OllamaChat:
    def __init__(
        self, model: str, think: bool = False, base_url: str | None = None, **options
    ) -> None:
        self.model = model
        self.think = think
        self.options = {**GENERATION_OPTIONS, **options}
        self.client = httpx.Client(base_url=base_url or settings.ollama_base_url, timeout=900)

    def chat(self, system: str, user: str, history: list[dict] | None = None) -> tuple[str, dict]:
        """Reply text and stats (tokens, seconds, tokens/s). `history`: earlier
        {"role", "content"} turns, placed between the system message and `user`."""
        start = time.perf_counter()
        resp = self.client.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    *(history or []),
                    {"role": "user", "content": user},
                ],
                "think": self.think,
                "stream": False,
                "options": self.options,
            },
        )
        if resp.status_code == 404:
            raise RuntimeError(
                f"Ollama has no model {self.model!r}: run `ollama pull {self.model}`"
            )
        resp.raise_for_status()
        body = resp.json()
        eval_s = body.get("eval_duration", 0) / 1e9
        stats = {
            "seconds": round(time.perf_counter() - start, 2),
            "prompt_tokens": body.get("prompt_eval_count"),
            "output_tokens": body.get("eval_count"),
            "tokens_per_s": round(body["eval_count"] / eval_s, 1) if eval_s else None,
        }
        return body["message"]["content"].strip(), stats


# --------------------------------------------------------------------------- judge

EXPERT_FIELDS = ("key_points", "fidelity", "attribution", "usefulness", "citation_quality")
EXPERT_NULLABLE = ("fidelity", "citation_quality")  # null when the answer saw no notes

EXPERT_JUDGE_RUBRIC = f"""You are a consultant psychiatrist in an adult ADHD service. A colleague
asked a knowledge base a question about reading patients' own writing. An AI assistant answered from
short numbered notes that other clinicians wrote ([E1], [E2], ...), or, for some items, with no
notes. You review each answer as you would a junior colleague's summary: you care that what
clinicians said is reported faithfully, with its conditions, and is never turned into
established fact or diagnostic criteria. Score every answer on its own; do not reward length; do
not use outside knowledge to excuse a claim the notes do not support.

You get the question, main key points that a good answer draws on (each with its direction: whether it
raises or lowers the case for ADHD traits, and its condition), the notes the assistant saw, and the
answers. A good answer does not need every key point, but should cover the main ones the notes
allow. It may add other readings that the notes support; do not penalise those.

Score each from 1 (bad) to 5 (excellent):
- key_points: how many of the main key points the answer covers (not how many the notes contained).
- fidelity: direction and conditions match the notes. A hedge or condition in the notes ("only if",
  "unless", "weak alone") that the answer drops is an error. Reversing a direction is the worst
  error. Null if there were no notes.
- attribution: presented as what clinicians in the notes said or read, not as established fact or
  diagnostic criteria; no invented quotes; says so when only one clinician made a point.
- usefulness: concrete and usable by a busy clinician who has to decide what to look for or ask.
- citation_quality: each [E#] supports the claim it is attached to. Null if there were no notes.
Anchors for fidelity: 5 = the note says one missed deadline in a house-move week lowers the weight,
and the answer says that with the condition. 3 = keeps the direction, drops the condition. 1 = the
note says fatigue lowers the weight and the answer says fatigue raises it.
Anchors for attribution: 5 = "The clinicians read X as ...; one of them adds ...". 3 = partly
attributed, partly stated as how things are. 1 = "Diagnostic criteria require ..." or a made-up
quote.

Flags:
- unsupported_claims: true if the answer states a clinical fact or rule that is in neither the
  notes nor the question (with no notes, true if it presents specific rules as established).
- abstention_ok: if the answer says {NOT_IN_SOURCES} or that the notes do not cover it: true if the
  notes truly hold nothing relevant, false if they hold material that answers the question; null
  when the answer does not abstain.
- pass: fidelity >= 4 (or null) and attribution >= 4 and key_points >= 3 and unsupported_claims is
  false.

Write the rationale first in your head, then the scores. Reply with one JSON object only, one entry
per system label (each system has one sample here):
{{"<system label>": {{"samples": [{{"key_points": int, "fidelity": int|null, "attribution": int,
   "usefulness": int, "citation_quality": int|null, "unsupported_claims": bool,
   "abstention_ok": bool|null, "pass": bool, "rationale": "<one sentence>"}}],
  "consistency": null, "behaviour_changed": null, "consistency_note": null}}}}"""


def expert_judge_prompt(question: dict, context: list[dict], systems: dict[str, list[str]]) -> str:
    """One grading item: `question` is an entry of an expert run's questions, `context` the notes
    the system saw (empty for the no-notes baseline) and `systems` maps a blind label to answers."""
    points = "\n".join(f"- {p}" for p in question["reference_points"])
    notes = "\n\n".join(f"[E{n}] {c['text']}" for n, c in enumerate(context, 1))
    answers = "\n\n".join(
        f"=== System {label}, sample {i} ===\n{text}"
        for label, samples in systems.items()
        for i, text in enumerate(samples, 1)
    )
    return (
        f"Question: {question['question']}\n\n"
        f"Key points a good answer draws on:\n{points}\n\n"
        f"Notes the assistant saw:\n\n{notes or '(no notes were given)'}\n\n"
        f"Answers:\n\n{answers}"
    )


def parse_sample_judgment(data: dict) -> dict:
    if data.get("key_points") == 0:
        # Haiku writes 0 when an answer covers none of the key points: the bottom of the scale,
        # and exactly the answers (no notes, wrong notes) that must not drop out of the results.
        data = {**data, "key_points": 1}
    for name in EXPERT_FIELDS:
        if name in EXPERT_NULLABLE and data.get(name) is None:
            continue  # nothing to check against: the answer saw no notes
        if not isinstance(data.get(name), int) or not 1 <= data[name] <= 5:
            raise ValueError(f"{name} must be an int 1-5, got {data.get(name)!r}")
    for name in ("unsupported_claims", "pass"):
        if not isinstance(data.get(name), bool):
            raise ValueError(f"{name} must be a bool, got {data.get(name)!r}")
    extra = ("abstention_ok", "unsupported_claims", "pass", "rationale")
    return {k: data.get(k) for k in (*EXPERT_FIELDS, *extra)}


def parse_judgment(reply: str | dict, systems: dict[str, list[str]]) -> dict:
    """The judge's reply for one item, validated against the systems and sample counts it was
    given. Raises ValueError on a malformed reply."""
    if isinstance(reply, str):
        match = re.search(r"\{.*\}", reply, re.DOTALL)
        if not match:
            raise ValueError(f"no JSON object in judge reply: {reply[:200]!r}")
        reply = json.loads(match.group(0))
    out = {}
    for label, samples in systems.items():
        verdict = reply.get(label)
        if not isinstance(verdict, dict) or len(verdict.get("samples", [])) != len(samples):
            raise ValueError(f"system {label}: expected {len(samples)} sample judgments")
        consistency = verdict.get("consistency")
        if len(samples) > 1 and (not isinstance(consistency, int) or not 1 <= consistency <= 5):
            raise ValueError(f"system {label}: consistency must be an int 1-5")
        out[label] = {
            "samples": [parse_sample_judgment(j) for j in verdict["samples"]],
            "consistency": consistency,
            "behaviour_changed": verdict.get("behaviour_changed"),
            "consistency_note": verdict.get("consistency_note"),
        }
    return out
