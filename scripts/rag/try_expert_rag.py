# ruff: noqa: E501  (long prompt and report strings)
"""Try the expert-knowledge-rag package end to end: retrieve from Postgres, generate, save for grading.

Usage: python scripts/rag/try_expert_rag.py --seed-silver
       python scripts/rag/try_expert_rag.py --schema chips_silver --models qwen3.8:27b \
           --run-dir data/eval/expert_runs/<name> [--suites labelled vignette patient] [--limit N]
       python scripts/rag/try_expert_rag.py --schema chips --suites vignette --run-dir <dir>

Only the package is used for retrieval and generation (retrievers, answer chains, ChatOllama); the
script just feeds it questions and writes down what came back. Suites:
  labelled  the 40 labelled clinician questions over all vignettes (silver only: hit@k, claim recall)
  vignette  per vignette, three fixed questions limited to that vignette, k=8 (the several-experts
            case: do the notes carry both experts, and does the answer attribute each one?)
  patient   the 9 silver patient texts with PatientTextRetriever (silver only)
Every suite needs a schema whose units are the silver snapshot; on the live `chips` schema only
`vignette` runs, without reference points.

--seed-silver builds schema `chips_silver` from tests/fixtures/retrieval_silver (it drops that
schema first; `chips` is never touched). Retrieval for all items runs first (bge-m3), then each
model answers the same notes, so embedding and generation never share the GPU. Resumes when rerun
with the same --run-dir. Writes, in the run dir:
  generations.json  a normal expert run ("kind": "expert"): judge_generations.py --export-blind or
                    --judge-model grade it, eval_expert_generation.py --report reads it
  retrieval.json    per item: what was retrieved, experts and vignettes seen, hit@k / recall
  review.md         notes, reference points and answers with blank score lines, for a human
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
from langchain_ollama import ChatOllama
from psycopg import sql

from expert_knowledge_core.prompts import NOT_IN_SOURCES
from expert_knowledge_rag import (
    ExpertFilter,
    ExpertKnowledgeStore,
    ExpertQuestionRetriever,
    PatientTextRetriever,
    default_embeddings,
    expert_answer_chain,
    patient_answer_chain,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "db"))
SNAPSHOT = ROOT / "tests" / "fixtures" / "retrieval_silver"
CLAIMS = ROOT / "data" / "fixtures_chips" / "synthetic" / "silver" / "claims"
SILVER_SCHEMA = "chips_silver"
OPTIONS = {"temperature": 0, "num_ctx": 8192, "num_predict": 600}  # as in the earlier runs
VIGNETTE_K = 8
MAX_REFERENCE = 12

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


def seed_silver(dsn: str) -> None:
    import chips_snapshot

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(SILVER_SCHEMA))
        )
        conn.execute("BEGIN")
        try:
            counts = chips_snapshot.seed(conn, SILVER_SCHEMA, SNAPSHOT)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    print(f"seeded {SILVER_SCHEMA}: {counts}")


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
    """`DOC-SYN-0001#12` -> claim, as the labels of the snapshot name them."""
    claims: dict[str, dict] = {}
    for path in sorted(CLAIMS.glob("DOC-*.claims.json")):
        for i, c in enumerate(json.loads(path.read_text())):
            claims[f"{path.name.split('.')[0]}#{i}"] = c
    return claims


def vignette_of_unit(unit_id: str) -> str:
    m = re.search(r"-(V\d+)-[^-]+$", unit_id)
    return m.group(1) if m else ""


# --- items -----------------------------------------------------------------------------------


def build_items(args: argparse.Namespace, vignettes: dict[str, list[str]]) -> list[dict]:
    """The questions to ask: {id, suite, question, patient_text?, vignette?, exclude?, k, refs, labels}."""
    silver = args.schema.startswith(SILVER_SCHEMA)
    queries = json.loads((SNAPSHOT / "queries.json").read_text()) if silver else {}
    claims = load_claims() if silver else {}
    covers = queries.get("covers", {})
    items: list[dict] = []

    def refs(ids: list[str]) -> list[str]:
        return [reference_line(claims[c]) for c in ids if c in claims]

    if "labelled" in args.suites and silver:
        for i, q in enumerate(queries["questions"][: args.limit], 1):
            relevant = sorted({u for c in q["pooled_ids"] for u in covers.get(c, [])})
            items.append(
                {
                    "id": f"L{i:02d}",
                    "suite": "labelled",
                    "question": q["question"],
                    "k": args.k,
                    "refs": refs(q["claim_ids"]),
                    "claim_ids": q["claim_ids"],
                    "relevant_units": relevant,
                    "covers": {c: covers.get(c, []) for c in q["claim_ids"]},
                }
            )
    if "vignette" in args.suites:
        by_vignette = defaultdict(list)
        for claim_id, units in covers.items():
            for u in units:
                by_vignette[vignette_of_unit(u)].append(claim_id)
        for v in list(vignettes)[: args.limit]:
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
    if "patient" in args.suites and silver:
        for p in queries["patients"][: args.limit]:
            items.append(
                {
                    "id": f"P-{p['id']}",
                    "suite": "patient",
                    "question": PATIENT_QUESTION,
                    "patient_text": p["text"],
                    "exclude": p.get("exclude", []),
                    "k": args.k,
                    "refs": refs(p["claim_ids"][:MAX_REFERENCE]),
                    "relevant_units": sorted(
                        {u for c in p["claim_ids"] for u in covers.get(c, [])}
                    ),
                }
            )
    return items


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


def retrieve(item: dict, store: ExpertKnowledgeStore, embeddings: Any, args: argparse.Namespace):
    flt = ExpertFilter(
        include_synthetic=True,
        vignettes=[item["vignette"]] if item.get("vignette") else None,
        exclude_vignettes=item.get("exclude", []),
    )
    cls = PatientTextRetriever if item["suite"] == "patient" else ExpertQuestionRetriever
    retriever = cls(store=store, embeddings=embeddings, k=item["k"], search=args.search, filter=flt)
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


def answer(item: dict, docs: list[Document], llm: ChatOllama) -> tuple[str, dict]:
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


# --- output ----------------------------------------------------------------------------------


def write_review(run: dict, records: dict, path: Path) -> None:
    by_item = defaultdict(list)
    for g in run["generations"]:
        by_item[g["id"]].append(g)
    out = [f"# Review sheet: {run['schema']}, search {run['search']}\n"]
    out.append(
        "Per answer: key_points / fidelity / attribution / usefulness / citations 1-5 (`-` if n/a), "
        "pass y/n, comment. Do the answer's claims match the notes, and are they attributed to the "
        "clinicians (and to the right one)?\n"
    )
    for qid, q in run["questions"].items():
        rec = records[qid]
        out.append(f"\n---\n\n## {qid} ({rec['suite']})\n")
        if rec["suite"] == "vignette":
            out.append(
                f"Vignette filter: {q['vignette']}; experts in vignette: {', '.join(rec['experts_in_vignette'])}; "
                f"experts retrieved: {', '.join(rec['experts_retrieved'])}\n"
            )
        out.append(f"**Question:** {q['question']}\n")
        out.append("### Notes the model saw\n")
        for n, note in enumerate(q["contexts"]["rag"], 1):
            m = note["metadata"]
            out.append(
                f"**[E{n}]** {m['expert_id']} · {m['vignette_id']} · score {m['score']:.3f}\n"
            )
            out.append("> " + note["text"].replace("\n", "\n> ") + "\n")
        if q["reference_points"]:
            out.append("### Reference points (from the labelled claims)\n")
            out += [f"- {p}" for p in q["reference_points"]]
            out.append("")
        for g in sorted(by_item[qid], key=lambda g: g["model"]):
            c = g["checks"]
            out.append(f"### Answer: {g['model']}\n")
            out.append(g["answer"] + "\n")
            out.append(
                f"_cited {c['n_cited']} notes, experts cited: {', '.join(c['experts_cited']) or '-'}, "
                f"invalid: {c['invalid_citations'] or '-'}, abstained: {c['abstained']}_\n"
            )
            out.append(
                "`key_points _  fidelity _  attribution _  usefulness _  citations _ | pass _ | comment:`\n"
            )
    path.write_text("\n".join(out))


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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--schema", default=SILVER_SCHEMA)
    ap.add_argument("--seed-silver", action="store_true", help=f"(re)create schema {SILVER_SCHEMA}")
    ap.add_argument("--run-dir", type=Path)
    ap.add_argument("--models", nargs="+", default=["qwen3.8:27b"])
    ap.add_argument("--suites", nargs="+", default=["labelled", "vignette", "patient"])
    ap.add_argument("--search", default="hybrid", choices=["hybrid", "dense", "bm25"])
    ap.add_argument("--k", type=int, default=4, help="notes per question (vignette suite uses 8)")
    ap.add_argument(
        "--limit", type=int, default=None, help="items per suite (vignettes for that suite)"
    )
    ap.add_argument("--think", action="store_true", help="let the model reason before answering")
    args = ap.parse_args()

    dsn = os.environ["DATABASE_URL"]
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    if args.seed_silver:
        seed_silver(dsn)
        if not args.run_dir:
            return
    if not args.run_dir:
        ap.error("--run-dir is required")

    experts = experts_per_vignette(dsn, args.schema)
    if not experts:
        sys.exit(f"schema {args.schema} has no units (--seed-silver builds {SILVER_SCHEMA})")
    items = build_items(args, experts)
    if not items:
        sys.exit("no items: the labelled and patient suites need the silver schema")

    args.run_dir.mkdir(parents=True, exist_ok=True)
    gen_path, ret_path = args.run_dir / "generations.json", args.run_dir / "retrieval.json"
    run = (
        json.loads(gen_path.read_text())
        if gen_path.exists()
        else {
            "kind": "expert",
            "representation": "package: I1 hybrid",
            "budget": None,
            "labels": "claims",
            "schema": args.schema,
            "search": args.search,
            "options": OPTIONS,
            "questions": {},
            "generations": [],
        }
    )
    records = json.loads(ret_path.read_text())["items"] if ret_path.exists() else {}

    # 1. retrieval (bge-m3 only)
    store = ExpertKnowledgeStore(dsn, schema=args.schema)
    embeddings = default_embeddings(base_url=base_url)
    for item in items:
        if item["id"] in run["questions"]:
            continue
        docs = retrieve(item, store, embeddings, args)
        records[item["id"]] = retrieval_record(item, docs, experts)
        run["questions"][item["id"]] = {
            "question": judge_question(item),
            "type": "patient_text" if item["suite"] == "patient" else "clinician_question",
            "reference_points": item["refs"],
            "optional_points": [],
            "relevant_units": item["relevant_units"],
            "contexts": {"rag": [note_of(d) for d in docs]},
            "vignette": item.get("vignette"),
            "question_only": item["question"],
            "patient_text": item.get("patient_text"),
        }
        print(
            f"retrieved {item['id']}: {len(docs)} notes, experts {records[item['id']]['experts_retrieved']}"
        )
    ret_path.write_text(json.dumps({"summary": summarise(records), "items": records}, indent=1))

    # 2. generation, one model at a time
    done = {(g["model"], g["id"]) for g in run["generations"]}
    wanted = {i["id"]: i for i in items}
    for model in args.models:
        llm = ChatOllama(model=model, base_url=base_url, reasoning=args.think, **OPTIONS)
        for qid, item in wanted.items():
            if (model, qid) in done:
                continue
            docs = [doc_of(n) for n in run["questions"][qid]["contexts"]["rag"]]
            text, stats = answer(item, docs, llm)
            run["generations"].append(
                {
                    "id": qid,
                    "model": model,
                    "context": "rag",
                    "sample": 1,
                    "answer": text,
                    "checks": checks(text, docs),
                    "stats": stats,
                }
            )
            run["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            gen_path.write_text(json.dumps(run, indent=1))
            print(f"{model} {qid}: {stats['seconds']}s, {len(text.split())} words")

    # only the items asked for this time go to the review sheet
    shown = {**run, "questions": {q: v for q, v in run["questions"].items() if q in wanted}}
    write_review(shown, records, args.run_dir / "review.md")
    print(json.dumps(summarise({q: records[q] for q in wanted if q in records}), indent=1))
    print(f"wrote {gen_path}, {ret_path}, {args.run_dir / 'review.md'}")


if __name__ == "__main__":
    main()
