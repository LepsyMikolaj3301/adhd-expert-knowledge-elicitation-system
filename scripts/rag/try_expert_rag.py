# ruff: noqa: E501  (long prompt and report strings)
"""Try the expert-knowledge-rag package end to end: retrieve from Postgres, generate, save for grading.

Usage: python scripts/rag/try_expert_rag.py --seed-silver
       python scripts/rag/try_expert_rag.py --schema chips_silver --models qwen3.8:27b \
           --run-dir data/eval/expert_runs/<name> [--suites labelled vignette patient] [--limit N]
       python scripts/rag/try_expert_rag.py --schema chips --suites vignette --run-dir <dir>
       python scripts/rag/try_expert_rag.py --schema chips_scale --group-fragments \
           --questions tests/fixtures/final_eval/queries.json --suites final vignette \
           --vignettes V001 V004 V006 V012 --contexts rag oracle --models <m> --run-dir <dir>

Only the package is used for retrieval and generation (retrievers, answer chains, ChatOllama); the
script just feeds it questions and writes down what came back. Suites:
  labelled  the 40 labelled clinician questions over all vignettes (silver only: hit@k, claim recall)
  vignette  per vignette, three fixed questions limited to that vignette, k=8 (the several-experts
            case: do the notes carry both experts, and does the answer attribute each one?)
  patient   the silver patient texts with PatientTextRetriever (silver only)
  final     the items of --questions (make_final_queries.py: clinician questions, new patient texts,
            out-of-scope questions with their oracle units and key points), any schema they were
            labelled on
Contexts (--contexts): `rag` the retrieved notes; `oracle` the best notes the same retriever can give
from its top 40 (expert_rag_lib.oracle_notes; items without labelled units get none); `none` the
model asked without notes (the no-notes prompt of eval_expert_generation.py). Each context is retrieved
once per item and kept, so a later call can add a context or a model to the same run dir.
--think [low|medium|high] and --num-predict are recorded per model (run["model_options"]), and the
VRAM Ollama gave each model (`/api/ps` after its first answer) in run["hardware"].
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

import httpx
from expert_rag_lib import (
    OPTIONS,
    SEARCHES,
    SILVER_SCHEMA,
    answer,
    build_items,
    checks,
    doc_of,
    experts_per_vignette,
    is_patient,
    judge_question,
    no_notes_answer,
    note_of,
    ollama_models,
    oracle_notes,
    retrieval_record,
    retrieve,
    seed_silver,
    summarise,
)
from langchain_ollama import ChatOllama

from expert_knowledge_rag import ExpertKnowledgeStore, default_embeddings

CONTEXTS = ("rag", "oracle", "none")


def loaded(base_url: str, model: str) -> dict | None:
    """What Ollama reports for a loaded model: size, size_vram (bytes), context length."""
    for m in httpx.get(f"{base_url}/api/ps", timeout=10).json().get("models", []):
        if m["name"] == model or m.get("model") == model:
            return {k: m.get(k) for k in ("size", "size_vram", "context_length")}
    return None


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
        if q.get("patient_text"):
            out.append(f"**Patient text:** {q['patient_text']}\n")
        out.append("### Notes the model saw (rag)\n")
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
        for g in sorted(by_item[qid], key=lambda g: (g["context"], g["model"])):
            c = g["checks"]
            out.append(f"### Answer: {g['model']} ({g['context']})\n")
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
    ap.add_argument(
        "--think",
        nargs="?",
        const=True,
        default=False,
        choices=[True, "low", "medium", "high"],
        help="let the model reason before answering (a level for gpt-oss)",
    )
    ap.add_argument("--num-predict", type=int, help=f"default {OPTIONS['num_predict']}")
    ap.add_argument("--questions", type=Path, help="final-evaluation items (suite final)")
    ap.add_argument("--vignettes", nargs="+", help="only these vignettes in the vignette suite")
    ap.add_argument("--contexts", nargs="+", default=["rag"], choices=CONTEXTS)
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
    if "final" in args.suites and not args.questions:
        ap.error("suite final needs --questions")
    items = build_items(
        args.schema, args.suites, args.k, args.limit, experts, args.vignettes, args.questions
    )
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
    run.setdefault("model_options", {})
    run.setdefault("hardware", {})
    if (run["schema"], run["search"], run.get("group_fragments", False)) != (
        args.schema,
        args.search,
        args.group_fragments,
    ):
        sys.exit(f"{args.run_dir} was made with other retrieval settings; use a new --run-dir")
    records = json.loads(ret_path.read_text())["items"] if ret_path.exists() else {}

    # 1. retrieval (bge-m3 only), every context once per item
    store = ExpertKnowledgeStore(dsn, schema=args.schema)
    embeddings = default_embeddings(base_url=base_url)
    options = {"group_fragments": args.group_fragments}
    for item in items:
        q = run["questions"].get(item["id"])
        if q is None:
            docs = retrieve(item, store, embeddings, args.search, **options)
            records[item["id"]] = retrieval_record(item, docs, experts)
            q = run["questions"][item["id"]] = {
                "question": judge_question(item),
                "type": "patient_text" if is_patient(item) else "clinician_question",
                "suite": item["suite"],
                "kind": item.get("kind"),
                "answerable": item.get("answerable"),
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
        if "oracle" in args.contexts and "oracle" not in q["contexts"]:
            oracle = oracle_notes(item, store, embeddings, args.search, **options)
            q["contexts"]["oracle"] = [note_of(d) for d in oracle]
            records[item["id"]]["oracle_notes"] = len(oracle)
        if "none" in args.contexts:
            q["contexts"].setdefault("none", [])
    ret_path.write_text(json.dumps({"summary": summarise(records), "items": records}, indent=1))
    gen_path.write_text(json.dumps(run, indent=1))

    # 2. generation, one model at a time
    done = {(g["model"], g["id"], g["context"]) for g in run["generations"]}
    wanted = {i["id"]: i for i in items}
    model_options = {**OPTIONS}
    if args.num_predict:
        model_options["num_predict"] = args.num_predict
    for model in args.models:
        llm = ChatOllama(model=model, base_url=base_url, reasoning=args.think, **model_options)
        used = {"think": args.think, **model_options}
        if run["model_options"].setdefault(model, used) != used:
            sys.exit(
                f"{model} was run here with {run['model_options'][model]}; use a new --run-dir"
            )
        for context in args.contexts:
            for qid, item in wanted.items():
                notes = run["questions"][qid]["contexts"].get(context)
                if (model, qid, context) in done or (context == "oracle" and not notes):
                    continue
                docs = [doc_of(n) for n in notes]
                if context == "none":
                    text, stats = no_notes_answer(item, llm)
                else:
                    text, stats = answer(item, docs, llm, grouped=args.group_fragments)
                run["generations"].append(
                    {
                        "id": qid,
                        "model": model,
                        "context": context,
                        "sample": 1,
                        "answer": text,
                        "checks": checks(text, docs),
                        "stats": stats,
                    }
                )
                if model not in run["hardware"]:
                    run["hardware"][model] = loaded(base_url, model)
                    print(f"{model} loaded: {run['hardware'][model]}")
                run["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
                gen_path.write_text(json.dumps(run, indent=1))
                print(f"{model} {context} {qid}: {stats['seconds']}s, {len(text.split())} words")

    # only the items asked for this time go to the review sheet
    shown = {**run, "questions": {q: v for q, v in run["questions"].items() if q in wanted}}
    write_review(shown, records, args.run_dir / "review.md")
    print(json.dumps(summarise({q: records[q] for q in wanted if q in records}), indent=1))
    print(f"wrote {gen_path}, {ret_path}, {args.run_dir / 'review.md'}")


if __name__ == "__main__":
    main()
