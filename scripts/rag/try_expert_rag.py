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
  patient   the silver patient texts with PatientTextRetriever (silver only)
Every suite needs a schema whose units are the silver answers; on the live `chips` schema only
`vignette` runs, without reference points.

--seed-silver builds schema `chips_silver` from the answers of SYN-001 and SYN-002 in
tests/fixtures/scale_answers, ingested as the application would (units, bge-m3 vectors, BM25: it
drops that schema first; `chips` is never touched). Retrieval for all items runs first (bge-m3), then each
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
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from expert_rag_lib import (
    OPTIONS,
    SEARCHES,
    SILVER_SCHEMA,
    answer,
    build_items,
    checks,
    doc_of,
    experts_per_vignette,
    judge_question,
    note_of,
    ollama_models,
    retrieval_record,
    retrieve,
    seed_silver,
    summarise,
)
from langchain_ollama import ChatOllama

from expert_knowledge_rag import ExpertKnowledgeStore, default_embeddings

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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--schema", default=SILVER_SCHEMA)
    ap.add_argument("--seed-silver", action="store_true", help=f"(re)create schema {SILVER_SCHEMA}")
    ap.add_argument("--run-dir", type=Path)
    ap.add_argument("--models", nargs="+", default=["qwen3.8:27b"])
    ap.add_argument("--suites", nargs="+", default=["labelled", "vignette", "patient"])
    ap.add_argument("--search", default="hybrid", choices=SEARCHES)
    ap.add_argument("--k", type=int, default=4, help="notes per question (vignette suite uses 8)")
    ap.add_argument(
        "--limit", type=int, default=None, help="items per suite (vignettes for that suite)"
    )
    ap.add_argument("--think", action="store_true", help="let the model reason before answering")
    ap.add_argument(
        "--group-fragments",
        action="store_true",
        help="fragments several clinicians marked become one note with an agreement line",
    )
    ap.add_argument(
        "--list-models", action="store_true", help="print the chat models of Ollama and exit"
    )
    args = ap.parse_args()

    dsn = os.environ["DATABASE_URL"]
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    if args.list_models:
        print("\n".join(ollama_models(base_url)))
        return
    if args.seed_silver:
        seed_silver(dsn)
        if not args.run_dir:
            return
    if not args.run_dir:
        ap.error("--run-dir is required")

    available = ollama_models(base_url)
    unknown = [m for m in args.models if m not in available]
    if unknown:
        sys.exit(f"models not in Ollama: {unknown}; --list-models shows what is there")

    experts = experts_per_vignette(dsn, args.schema)
    if not experts:
        sys.exit(f"schema {args.schema} has no units (--seed-silver builds {SILVER_SCHEMA})")
    items = build_items(args.schema, args.suites, args.k, args.limit, experts)
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
            "group_fragments": args.group_fragments,
            "options": OPTIONS,
            "questions": {},
            "generations": [],
        }
    )
    if (run["schema"], run["search"], run.get("group_fragments", False)) != (
        args.schema,
        args.search,
        args.group_fragments,
    ):
        sys.exit(f"{args.run_dir} was made with other retrieval settings; use a new --run-dir")
    records = json.loads(ret_path.read_text())["items"] if ret_path.exists() else {}

    # 1. retrieval (bge-m3 only)
    store = ExpertKnowledgeStore(dsn, schema=args.schema)
    embeddings = default_embeddings(base_url=base_url)
    for item in items:
        if item["id"] in run["questions"]:
            continue
        docs = retrieve(item, store, embeddings, args.search, group_fragments=args.group_fragments)
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
