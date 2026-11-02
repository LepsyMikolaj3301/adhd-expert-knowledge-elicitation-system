"""Shared helpers for the RAG scripts (ask.py, eval_*.py, judge_generations.py, report_eval.py).

Retrieval over the pgvector `chunks` table, generation with Ollama chat models (answers cite
the context as [n]) and the LLM-as-judge rubric. Not a backend module on purpose: the scripts
import it as `rag_common` (their folder, scripts/rag/, is on sys.path when they run as `python scripts/rag/x.py`).
"""

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
import httpx
from pgvector.asyncpg import register_vector

from app.embeddings import Embedder
from app.indexing import Bm25Config, bm25, build_embedder, load_indexing_config
from app.settings import settings

K = 5  # chunks given to the generator
CANDIDATES = 20  # retrieval depth for the metrics
RETRIEVAL_MODES = ("dense", "bm25", "hybrid")
RETRIEVAL = "hybrid"  # dense: pgvector cosine; bm25: sparsevec BM25; hybrid: both fused with RRF
RRF_K = 60  # reciprocal rank fusion: score = sum over rankings of 1 / (RRF_K + rank)
FUSION_DEPTH = 50  # candidates taken from each ranking before fusing
MODELS = ["qwen3.5:9b", "gemma4:e4b"]
GENERATION_OPTIONS = {"temperature": 0, "num_ctx": 8192, "num_predict": 600}
SAMPLING_TEMPERATURE = 0.7  # used when a question is asked more than once
NOT_IN_SOURCES = "NOT_IN_SOURCES"

DATASET = Path("data/eval/bronze_qa.json")
RUNS_DIR = Path("data/eval/runs")


# --------------------------------------------------------------------------- retrieval


@dataclass
class RetrievedChunk:
    id: str
    source_id: str
    title: str
    heading_path: list[str]
    pages: list[int]
    text: str
    score: float

    def provenance(self) -> str:
        """One line: chunk id · source · heading · pages."""
        heading = " > ".join(self.heading_path[-2:]) or "(no heading)"
        pages = f" · p. {self.pages[0]}-{self.pages[-1]}" if self.pages else ""
        return f"{self.id} · {self.title or self.source_id} · {heading}{pages}"


def query_embedder(config: Path = Path("config/indexing.yaml")) -> Embedder:
    """The embedder the chunks were indexed with, so queries land in the same space."""
    return build_embedder(load_indexing_config(config))


def bm25_config(config: Path = Path("config/indexing.yaml")) -> Bm25Config:
    return load_indexing_config(config).sparse


async def connect() -> asyncpg.Connection:
    conn = await asyncpg.connect(settings.database_url)
    await register_vector(conn)
    await conn.execute("SET hnsw.ef_search = 100")
    return conn


COLUMNS = (
    "c.id, c.metadata->>'source_id' AS source_id, c.metadata->>'title' AS title, "
    "c.heading_path, c.pages, c.text"
)

DENSE_SQL = (
    f"SELECT {COLUMNS}, 1 - (c.embedding <=> $1) AS score FROM chunks c "
    "ORDER BY c.embedding <=> $1 LIMIT $2"
)
# `sparse <#> q` is -BM25; chunks sharing no term with the query (score 0) are not matches.
BM25_SQL = (
    f"SELECT {COLUMNS}, -(c.sparse <#> $1) AS score FROM chunks c "
    "WHERE (c.sparse <#> $1) < 0 ORDER BY c.sparse <#> $1 LIMIT $2"
)
HYBRID_SQL = f"""
WITH dense AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> $1) AS rank
    FROM chunks ORDER BY embedding <=> $1 LIMIT $4
), sparse AS (
    SELECT id, row_number() OVER (ORDER BY sparse <#> $2) AS rank
    FROM chunks WHERE (sparse <#> $2) < 0 ORDER BY sparse <#> $2 LIMIT $4
), fused AS (
    SELECT id, sum(1.0 / ($5 + rank)) AS score
    FROM (SELECT * FROM dense UNION ALL SELECT * FROM sparse) r GROUP BY id
)
SELECT {COLUMNS}, f.score FROM fused f JOIN chunks c USING (id)
ORDER BY f.score DESC, c.id LIMIT $3
"""


def to_chunks(rows: list[asyncpg.Record]) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            r["id"],
            r["source_id"],
            r["title"] or "",
            list(r["heading_path"]),
            list(r["pages"]),
            r["text"],
            float(r["score"]),
        )
        for r in rows
    ]


async def retrieve(
    conn: asyncpg.Connection,
    embedder: Embedder,
    query: str,
    k: int = K,
    mode: str = RETRIEVAL,
    sparse_config: Bm25Config | None = None,
) -> list[RetrievedChunk]:
    """Top-k chunks by `mode`. `score` is cosine similarity (dense), BM25 (bm25) or the RRF
    score (hybrid); only the order is comparable across modes. A query with no BM25 terms
    (all stopwords) falls back to dense."""
    if mode not in RETRIEVAL_MODES:
        raise ValueError(f"unknown retrieval mode {mode!r}, expected one of {RETRIEVAL_MODES}")
    vector = embedder.embed([query])[0] if mode != "bm25" else None
    sparse = bm25.query_vector(query, sparse_config or bm25_config()) if mode != "dense" else None
    if mode == "bm25" and sparse is None:
        return []
    if mode == "hybrid" and sparse is None:
        mode = "dense"
    if mode == "dense":
        rows = await conn.fetch(DENSE_SQL, vector, k)
    elif mode == "bm25":
        rows = await conn.fetch(BM25_SQL, sparse, k)
    else:
        rows = await conn.fetch(HYBRID_SQL, vector, sparse, k, FUSION_DEPTH, RRF_K)
    return to_chunks(rows)


async def oracle_context(
    conn: asyncpg.Connection, embedder: Embedder, item: dict, retrieved: list[RetrievedChunk]
) -> list[RetrievedChunk]:
    """The retrieved context with the item's gold chunks forced in: gold chunks plus the best
    non-gold retrieved ones, same size as `retrieved`, ordered by cosine similarity to the
    question (whatever retrieval mode produced `retrieved`, whose scores are not comparable).
    Answering well here but not from `retrieved` points at retrieval, not the model."""
    gold_ids = [ev["chunk_id"] for ev in item["evidence"] if ev.get("chunk_id")]
    if quoted := [ev for ev in item["evidence"] if not ev.get("chunk_id")]:
        # Evidence without a chunk id (the chunks it pointed at were re-chunked or removed): the
        # chunks holding the quote, best match to the question first, at most one per quote.
        found = await conn.fetch(
            "SELECT id, text FROM chunks ORDER BY embedding <=> $1",
            embedder.embed([item["question"]])[0],
        )
        for ev in quoted:
            quote = normalize(ev["quote"])
            gold_ids += [r["id"] for r in found if quote in normalize(r["text"])][:1]
    fill = [c for c in retrieved if not relevant_evidence(c.id, c.text, item)]
    rows = await conn.fetch(
        f"SELECT {COLUMNS}, 1 - (c.embedding <=> $1) AS score FROM chunks c WHERE c.id = ANY($2)",
        embedder.embed([item["question"]])[0],
        gold_ids + [c.id for c in fill],
    )
    by_id = {c.id: c for c in to_chunks(rows)}
    gold = [by_id[i] for i in dict.fromkeys(gold_ids) if i in by_id]
    best_fill = [by_id[c.id] for c in fill if c.id in by_id and c.id not in gold_ids]
    context = gold + best_fill[: max(len(retrieved) - len(gold), 0)]
    return sorted(context, key=lambda c: c.score, reverse=True)


# --------------------------------------------------------------------------- generation

SYSTEM_PROMPT = f"""You answer questions about ADHD using only the numbered context passages.
- Use only facts stated in the passages; do not add outside knowledge.
- Cite every claim with the passage number in brackets, e.g. [2] or [1][3].
- Be concise: 1-5 sentences.
- If the passages do not contain the answer, reply exactly: {NOT_IN_SOURCES}"""


class OllamaChat:
    def __init__(
        self, model: str, think: bool = False, base_url: str | None = None, **options
    ) -> None:
        self.model = model
        self.think = think
        self.options = {**GENERATION_OPTIONS, **options}
        self.client = httpx.Client(base_url=base_url or settings.ollama_base_url, timeout=900)

    def chat(self, system: str, user: str) -> tuple[str, dict]:
        """Reply text and stats (tokens, seconds, tokens/s)."""
        start = time.perf_counter()
        resp = self.client.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
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


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for n, c in enumerate(chunks, 1):
        heading = " > ".join(c.heading_path) or "(no heading)"
        pages = f" (p. {c.pages[0]}-{c.pages[-1]})" if c.pages else ""
        blocks.append(f"[{n}] {c.title or c.source_id} — {heading}{pages}\n{c.text}")
    return "Context passages:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"


@dataclass
class Answer:
    text: str
    citations: list[RetrievedChunk]
    invalid_citations: list[int]
    abstained: bool
    stats: dict = field(default_factory=dict)


_CITATION = re.compile(r"\[(\d+(?:\s*[,;-]\s*\d+)*)\]")


def cited_numbers(text: str) -> list[int]:
    """[2], [1][3], [1, 3] and [2-4] -> sorted unique passage numbers."""
    numbers: set[int] = set()
    for group in _CITATION.findall(text):
        for part in re.split(r"\s*[,;]\s*", group):
            lo, _, hi = part.partition("-")
            numbers.update(range(int(lo), int(hi or lo) + 1))
    return sorted(numbers)


def answer(question: str, chunks: list[RetrievedChunk], chat: OllamaChat) -> Answer:
    text, stats = chat.chat(SYSTEM_PROMPT, build_prompt(question, chunks))
    numbers = cited_numbers(text)
    return Answer(
        text=text,
        citations=[chunks[n - 1] for n in numbers if 1 <= n <= len(chunks)],
        invalid_citations=[n for n in numbers if not 1 <= n <= len(chunks)],
        abstained=NOT_IN_SOURCES in text,
        stats=stats,
    )


# --------------------------------------------------------------------------- dataset + metrics


def normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def load_dataset(path: Path = DATASET) -> list[dict]:
    """The `items` of a dataset file: {"meta": {...corpus snapshot...}, "items": [...]}."""
    return json.loads(path.read_text())["items"]


async def corpus_snapshot(conn: asyncpg.Connection) -> dict:
    """What a dataset or run was made against, so results can be reproduced or invalidated."""
    row = await conn.fetchrow(
        "SELECT count(*) AS chunks, array_agg(DISTINCT index_config) AS index_configs, "
        "array_agg(DISTINCT embedding_model) AS embedding_models, "
        "array_agg(DISTINCT metadata->>'chunker_config') AS chunker_configs FROM chunks"
    )
    return dict(row)


def relevant_evidence(chunk_id: str, chunk_text: str, item: dict) -> set[int]:
    """Indices of the item's evidence entries this chunk covers: the quote is in its text
    (survives re-chunking), or the chunk id matches."""
    text = normalize(chunk_text)
    return {
        i
        for i, ev in enumerate(item["evidence"])
        if normalize(ev["quote"]) in text or ev.get("chunk_id") == chunk_id
    }


def token_f1(prediction: str, reference: str) -> float:
    def tokens(s: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", re.sub(r"\[\d[\d,;\s-]*\]", " ", s.lower()))

    pred, ref = tokens(prediction), tokens(reference)
    common = sum((Counter(pred) & Counter(ref)).values())
    if not pred or not ref or not common:
        return 0.0
    precision, recall = common / len(pred), common / len(ref)
    return 2 * precision * recall / (precision + recall)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


# --------------------------------------------------------------------------- judge

JUDGE_RUBRIC = f"""You grade answers from a retrieval-augmented QA system about ADHD.
Each item is one question with a reference answer, the context passages the systems saw
(numbered [1]..[k]) and the answers of one or more anonymous systems. A system may have been
asked the same question several times (samples 1..N); grade every sample on its own, then
judge how consistent that system was across its samples. Answers should cite passages as [n]
or say {NOT_IN_SOURCES}.

Per sample, score each from 1 (bad) to 5 (excellent):
- correctness: agreement with the reference answer on the facts that matter. Extra correct
  detail is fine; contradictions or wrong facts are not.
- faithfulness: every claim is supported by the context passages (not by outside knowledge).
- citation_quality: the cited passages actually support the claims they are attached to.
- completeness: covers the key points of the reference answer.

For an `unanswerable` question the right behaviour is to abstain ({NOT_IN_SOURCES} or an
explicit "the sources do not say"): then abstention_ok = true and all scores 5. Answering
anyway gives abstention_ok = false and correctness 1. For answerable questions an abstention
gets correctness 1 and completeness 1; abstention_ok = null.
pass = correctness >= 4 and faithfulness >= 4 (for unanswerable: pass = abstention_ok).

Per system (only when it has 2+ samples):
- consistency 1-5: 5 = same conclusion, same key facts and same supporting passages in every
  sample (wording may differ); 3 = same conclusion but samples differ in which facts or
  passages they use, or some drop key points; 1 = samples contradict each other, or some
  abstain while others answer.
- behaviour_changed: true if any sample differs from the others in its conclusion, its
  abstain/answer decision or its line of reasoning (not just wording or length).
- consistency_note: one sentence on what changed, or "stable".

Reply with one JSON object only:
{{"<system label>": {{"samples": [{{"correctness": int, "faithfulness": int,
   "citation_quality": int, "completeness": int, "abstention_ok": bool|null, "pass": bool,
   "rationale": "<one sentence>"}}, ...one per sample, in order],
  "consistency": int|null, "behaviour_changed": bool|null, "consistency_note": str|null}},
 ...one per system}}"""

JUDGE_FIELDS = ("correctness", "faithfulness", "citation_quality", "completeness")


def judge_prompt(question: dict, context: list[dict], systems: dict[str, list[str]]) -> str:
    """One grading item: `question` is an entry of generations.json["questions"], `context` the
    passages the systems saw and `systems` maps a blind label to its sample answers."""
    passages = "\n\n".join(f"[{n}] {c['id']}\n{c['text']}" for n, c in enumerate(context, 1))
    answers = "\n\n".join(
        f"=== System {label}, sample {i} ===\n{text}"
        for label, samples in systems.items()
        for i, text in enumerate(samples, 1)
    )
    return (
        f"Question type: {question['type']}\n"
        f"Question: {question['question']}\n\n"
        f"Reference answer: {question['reference_answer']}\n\n"
        f"Context passages:\n\n{passages}\n\n"
        f"Answers:\n\n{answers}"
    )


def parse_sample_judgment(data: dict, expert: bool = False) -> dict:
    fields = EXPERT_FIELDS if expert else JUDGE_FIELDS
    if expert and data.get("key_points") == 0:
        # Haiku writes 0 when an answer covers none of the key points: the bottom of the scale,
        # and exactly the answers (no notes, wrong notes) that must not drop out of the results.
        data = {**data, "key_points": 1}
    for name in fields:
        if expert and name in EXPERT_NULLABLE and data.get(name) is None:
            continue  # nothing to check against: the answer saw no notes
        if not isinstance(data.get(name), int) or not 1 <= data[name] <= 5:
            raise ValueError(f"{name} must be an int 1-5, got {data.get(name)!r}")
    flags = ("unsupported_claims", "pass") if expert else ("pass",)
    for name in flags:
        if not isinstance(data.get(name), bool):
            raise ValueError(f"{name} must be a bool, got {data.get(name)!r}")
    extra = (
        ("abstention_ok", "unsupported_claims", "pass", "rationale")
        if expert
        else ("abstention_ok", "pass", "rationale")
    )
    return {k: data.get(k) for k in (*fields, *extra)}


def parse_judgment(reply: str | dict, systems: dict[str, list[str]], expert: bool = False) -> dict:
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
            "samples": [parse_sample_judgment(j, expert) for j in verdict["samples"]],
            "consistency": consistency,
            "behaviour_changed": verdict.get("behaviour_changed"),
            "consistency_note": verdict.get("consistency_note"),
        }
    return out


# --------------------------------------------------------------------------- expert-notes judge

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
