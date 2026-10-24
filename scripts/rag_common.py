"""Shared helpers for the RAG scripts (ask.py, eval_*.py, judge_generations.py, report_eval.py).

Retrieval over the pgvector `chunks` table, generation with Ollama chat models (answers cite
the context as [n]) and the LLM-as-judge rubric. Not a backend module on purpose: the scripts
import it as `rag_common` (scripts/ is on sys.path when they run as `python scripts/x.py`).
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
from app.indexing import build_embedder, load_indexing_config
from app.settings import settings

K = 5  # chunks given to the generator
CANDIDATES = 20  # retrieval depth for the metrics
MODELS = ["qwen3.5:9b", "gemma4:e4b"]
GENERATION_OPTIONS = {"temperature": 0, "num_ctx": 8192, "num_predict": 600}
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


async def connect() -> asyncpg.Connection:
    conn = await asyncpg.connect(settings.database_url)
    await register_vector(conn)
    await conn.execute("SET hnsw.ef_search = 100")
    return conn


async def retrieve(
    conn: asyncpg.Connection, embedder: Embedder, query: str, k: int = K
) -> list[RetrievedChunk]:
    vector = embedder.embed([query])[0]
    rows = await conn.fetch(
        "SELECT id, metadata->>'source_id' AS source_id, metadata->>'title' AS title, "
        "heading_path, pages, text, 1 - (embedding <=> $1) AS score "
        "FROM chunks ORDER BY embedding <=> $1 LIMIT $2",
        vector,
        k,
    )
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
You get the question, a reference answer, the context passages the system saw (numbered
[1]..[k]) and the system's answer, which should cite passages as [n] or say {NOT_IN_SOURCES}.

Score each from 1 (bad) to 5 (excellent):
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

Reply with one JSON object only:
{{"correctness": int, "faithfulness": int, "citation_quality": int, "completeness": int,
 "abstention_ok": bool|null, "pass": bool, "rationale": "<one sentence>"}}"""

JUDGE_FIELDS = ("correctness", "faithfulness", "citation_quality", "completeness")


def judge_prompt(question: dict, answer_text: str) -> str:
    """`question` is an entry of generations.json["questions"] (it holds the context)."""
    context = "\n\n".join(
        f"[{n}] {c['id']}\n{c['text']}" for n, c in enumerate(question["context"], 1)
    )
    return (
        f"Question type: {question['type']}\n"
        f"Question: {question['question']}\n\n"
        f"Reference answer: {question['reference_answer']}\n\n"
        f"Context passages:\n\n{context}\n\n"
        f"System answer:\n{answer_text}"
    )


def parse_judgment(text: str) -> dict:
    """The judge's JSON object, validated. Raises ValueError on a malformed reply."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in judge reply: {text[:200]!r}")
    data = json.loads(match.group(0))
    for name in JUDGE_FIELDS:
        if not isinstance(data.get(name), int) or not 1 <= data[name] <= 5:
            raise ValueError(f"{name} must be an int 1-5, got {data.get(name)!r}")
    if not isinstance(data.get("pass"), bool):
        raise ValueError(f"pass must be a bool, got {data.get('pass')!r}")
    return {k: data.get(k) for k in (*JUDGE_FIELDS, "abstention_ok", "pass", "rationale")}
