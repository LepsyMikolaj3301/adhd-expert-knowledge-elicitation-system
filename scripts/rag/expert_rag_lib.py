# ruff: noqa: E501  (long prompt strings)
"""Shared pieces of the package try-out: the script (try_expert_rag.py) and the notebook
(notebooks/expert_rag_check.ipynb) both build on this, so they ask, retrieve and check the same way.

Only the `expert-knowledge-rag` package does the retrieval and the answering (retrievers, answer
chains, ChatOllama); this module builds the questions, calls it and writes down what came back.
Retrieval is always bge-m3 (the model of the stored vectors); the chosen local model only answers.
"""

import re
import sys
import time
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import psycopg
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
from psycopg import sql

from expert_knowledge_core.prompts import NOT_IN_SOURCES
from expert_knowledge_rag import (
    ExpertFilter,
    ExpertKnowledgeStore,
    ExpertQuestionRetriever,
    PatientTextRetriever,
    expert_answer_chain,
    patient_answer_chain,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "db"))
SILVER_SCHEMA = "chips_silver"
OPTIONS = {"temperature": 0, "num_ctx": 8192, "num_predict": 600}  # as in the earlier runs
VIGNETTE_K = 8
MAX_REFERENCE = 12
SEARCHES = ("hybrid", "dense", "bm25")

VIGNETTE_QUESTIONS = [
    (
        "readings",
        "Which passages of this teaching case did the clinicians read as pointing toward or away "
        "from ADHD-related traits, and why?",
    ),
    (
        "agreement",
        "Where do the clinicians who read this case agree, and where do their readings differ? "
        "Say which clinician said what, and which points only one of them made.",
    ),
    (
        "alternatives",
        "What other explanations did the clinicians give for the highlighted passages, and what "
        "did they say was missing from the text?",
    ),
]
PATIENT_QUESTION = (
    "Which passages would colleagues read as ADHD-related, and what else could explain them?"
)


# --- seeding and data ------------------------------------------------------------------------


@lru_cache(maxsize=1)
def silver_corpus():
    """The answers of SYN-001 and SYN-002 (tests/fixtures/scale_answers) ingested as the application
    would: units, bge-m3 vectors (needs Ollama), the labelled questions and patient texts, and which
    units hold each labelled claim. Made once per process."""
    import chips_fixture

    answers = chips_fixture.load(experts=chips_fixture.SILVER_EXPERTS)
    return chips_fixture.ingest(answers, chips_fixture.IndexEmbeddings()), answers.claims


def seed_silver(dsn: str) -> None:
    import chips_fixture

    corpus, _ = silver_corpus()
    with chips_fixture.seeded_schema(dsn, SILVER_SCHEMA, corpus, keep=True):
        pass
    print(f"seeded {SILVER_SCHEMA}: {len(corpus.tables['units'])} units")


def experts_per_vignette(dsn: str, schema: str) -> dict[str, list[str]]:
    query = sql.SQL(
        "SELECT vignette_id, array_agg(DISTINCT expert_id) FROM {}.finding_units GROUP BY 1"
    )
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        rows = conn.execute(query.format(sql.Identifier(schema))).fetchall()
    return {v: sorted(e) for v, e in sorted(rows)}


def reference_line(c: dict) -> str:
    note = "; ".join(x for x in (c.get("direction"), c.get("condition")) if x)
    return c["claim_text"] + (f" ({note})" if note else "")


def load_claims() -> dict[str, dict]:
    """`DOC-SYN-0001#12` -> claim, as the labels name them."""
    return silver_corpus()[1]


def vignette_of_unit(unit_id: str) -> str:
    m = re.search(r"-(V\d+)-[^-]+$", unit_id)
    return m.group(1) if m else ""


def ollama_models(base_url: str) -> list[str]:
    """Chat models the Ollama at `base_url` has (embedding models like bge-m3 left out)."""
    tags = httpx.get(f"{base_url}/api/tags", timeout=10).raise_for_status().json()["models"]
    return sorted(
        m["name"]
        for m in tags
        if "bert" not in (m.get("details", {}).get("family") or "")
        and "embed" not in m["name"]
        and "bge" not in m["name"]
    )


# --- items -----------------------------------------------------------------------------------


def build_items(
    schema: str,
    suites: list[str],
    k: int,
    limit: int | None,
    vignettes: dict[str, list[str]],
) -> list[dict]:
    """The questions to ask: {id, suite, question, patient_text?, vignette?, exclude?, k, refs, labels}."""
    silver = schema.startswith(SILVER_SCHEMA)
    queries = silver_corpus()[0].queries if silver else {}
    claims = load_claims() if silver else {}
    covers = queries.get("covers", {})
    items: list[dict] = []

    def refs(ids: list[str]) -> list[str]:
        return [reference_line(claims[c]) for c in ids if c in claims]

    if "labelled" in suites and silver:
        for i, q in enumerate(queries["questions"][:limit], 1):
            relevant = sorted({u for c in q["pooled_ids"] for u in covers.get(c, [])})
            items.append(
                {
                    "id": f"L{i:02d}",
                    "suite": "labelled",
                    "question": q["question"],
                    "k": k,
                    "refs": refs(q["claim_ids"]),
                    "claim_ids": q["claim_ids"],
                    "relevant_units": relevant,
                    "covers": {c: covers.get(c, []) for c in q["claim_ids"]},
                }
            )
    if "vignette" in suites:
        by_vignette = defaultdict(list)
        for claim_id, units in covers.items():
            for u in units:
                by_vignette[vignette_of_unit(u)].append(claim_id)
        for v in list(vignettes)[:limit]:
            ids = sorted(set(by_vignette.get(v, [])))[:MAX_REFERENCE]
            for name, text in VIGNETTE_QUESTIONS:
                items.append(
                    {
                        "id": f"{v}-{name}",
                        "suite": "vignette",
                        "question": text,
                        "vignette": v,
                        "k": VIGNETTE_K,
                        "refs": refs(ids),
                        "relevant_units": sorted(
                            {u for c in ids for u in covers.get(c, []) if vignette_of_unit(u) == v}
                        ),
                    }
                )
    if "patient" in suites and silver:
        for p in queries["patients"][:limit]:
            items.append(
                {
                    "id": f"P-{p['id']}",
                    "suite": "patient",
                    "question": PATIENT_QUESTION,
                    "patient_text": p["text"],
                    "exclude": p.get("exclude", []),
                    "k": k,
                    "refs": refs(p["claim_ids"][:MAX_REFERENCE]),
                    "relevant_units": sorted(
                        {u for c in p["claim_ids"] for u in covers.get(c, [])}
                    ),
                }
            )
    return items


def silver_examples(k: int = 4) -> list[dict]:
    """The 40 labelled questions and the patient texts of the silver answers, with their labels."""
    return build_items(SILVER_SCHEMA, ["labelled", "patient"], k, None, {})


def judge_question(item: dict) -> str:
    """What the judge reads as the question (for a patient text, the text comes with it)."""
    if item["suite"] == "patient":
        return f'Patient text: "{item["patient_text"]}"\n\n{item["question"]}'
    return item["question"]


def note_of(doc: Document) -> dict:
    return {"id": doc.metadata["unit_ids"][0], "text": doc.page_content, "metadata": doc.metadata}


def doc_of(note: dict) -> Document:
    return Document(page_content=note["text"], metadata=note["metadata"])


# --- retrieval -------------------------------------------------------------------------------


def make_retriever(
    store: ExpertKnowledgeStore,
    embeddings: Any,
    *,
    patient: bool,
    k: int,
    search: str = "hybrid",
    filter: ExpertFilter | None = None,  # noqa: A002
    merge_shared: bool = True,
    group_fragments: bool = False,
):
    cls = PatientTextRetriever if patient else ExpertQuestionRetriever
    return cls(
        store=store,
        embeddings=embeddings,
        k=k,
        search=search,
        filter=filter or ExpertFilter(),
        merge_shared=merge_shared,
        group_fragments=group_fragments,
    )


def retrieve(
    item: dict,
    store: ExpertKnowledgeStore,
    embeddings: Any,
    search: str = "hybrid",
    **options: Any,
) -> list[Document]:
    flt = ExpertFilter(
        vignettes=[item["vignette"]] if item.get("vignette") else None,
        exclude_vignettes=item.get("exclude", []),
    )
    retriever = make_retriever(
        store,
        embeddings,
        patient=item["suite"] == "patient",
        k=item["k"],
        search=search,
        filter=flt,
        **options,
    )
    return retriever.invoke(item.get("patient_text") or item["question"])


def retrieval_record(item: dict, docs: list[Document], experts: dict[str, list[str]]) -> dict:
    seen_units = {u for d in docs for u in d.metadata["unit_ids"]}
    relevant = set(item["relevant_units"])
    record = {
        "id": item["id"],
        "suite": item["suite"],
        "n_notes": len(docs),
        "experts_retrieved": sorted({d.metadata["expert_id"] for d in docs}),
        "vignettes_retrieved": sorted({d.metadata["vignette_id"] for d in docs}),
        "notes": [
            {k: d.metadata[k] for k in ("unit_ids", "expert_id", "vignette_id", "score")}
            for d in docs
        ],
    }
    if item.get("vignette"):
        record["experts_in_vignette"] = experts.get(item["vignette"], [])
    if relevant:
        record["hit"] = bool(seen_units & relevant)
    if item.get("covers"):
        record["claim_recall"] = sum(
            bool(seen_units & set(u)) for u in item["covers"].values()
        ) / len(item["covers"])
    return record


# --- generation ------------------------------------------------------------------------------


class Usage(BaseCallbackHandler):
    """Token counts of the last model call (the chain returns only text)."""

    def __init__(self) -> None:
        self.tokens: dict[str, int] = {}

    def on_llm_end(self, response: Any, **_: Any) -> None:
        message = getattr(response.generations[0][0], "message", None)
        self.tokens = dict(getattr(message, "usage_metadata", None) or {})


def answer(item: dict, docs: list[Document], llm: Any) -> tuple[str, dict]:
    """The package's answer chain over the notes already retrieved (so every model sees the same)."""
    fixed = RunnableLambda(lambda _: docs)
    usage = Usage()
    t0 = time.monotonic()
    if item["suite"] == "patient":
        out = patient_answer_chain(fixed, llm).invoke(
            {"patient_text": item["patient_text"], "question": item["question"]},
            config={"callbacks": [usage]},
        )
    else:
        out = expert_answer_chain(fixed, llm).invoke(
            item["question"], config={"callbacks": [usage]}
        )
    seconds = time.monotonic() - t0
    text = out["answer"].strip()
    tokens = usage.tokens
    stats = {
        "seconds": round(seconds, 2),
        "prompt_tokens": tokens.get("input_tokens"),
        "output_tokens": tokens.get("output_tokens"),
        "tokens_per_s": round(tokens["output_tokens"] / seconds, 1)
        if tokens.get("output_tokens")
        else None,
    }
    return text, stats


def cited(text: str) -> list[int]:
    groups = re.findall(r"\[([^\]]*)\]", text)
    return sorted({int(n) for g in groups for n in re.findall(r"E(\d+)", g)})


def checks(text: str, docs: list[Document]) -> dict:
    numbers = cited(text)
    valid = [n for n in numbers if 1 <= n <= len(docs)]
    return {
        "abstained": NOT_IN_SOURCES in text,
        "n_cited": len(valid),
        "invalid_citations": [n for n in numbers if n not in valid],
        "experts_cited": sorted({docs[n - 1].metadata["expert_id"] for n in valid}),
        "words": len(text.split()),
    }


def summarise(records: dict) -> dict:
    summary: dict[str, dict] = {}
    for suite in ("labelled", "vignette", "patient"):
        recs = [r for r in records.values() if r["suite"] == suite]
        if not recs:
            continue
        s: dict[str, Any] = {"items": len(recs)}
        if any("hit" in r for r in recs):
            s["hit_rate"] = round(sum(r.get("hit", False) for r in recs) / len(recs), 3)
        if any("claim_recall" in r for r in recs):
            rs = [r["claim_recall"] for r in recs if "claim_recall" in r]
            s["claim_recall"] = round(sum(rs) / len(rs), 3)
        if suite == "vignette":
            both = [set(r["experts_retrieved"]) >= set(r["experts_in_vignette"]) for r in recs]
            s["all_experts_retrieved"] = round(sum(both) / len(recs), 3)
        s["mean_vignettes_retrieved"] = round(
            sum(len(r["vignettes_retrieved"]) for r in recs) / len(recs), 2
        )
        summary[suite] = s
    return summary
