"""Generate answers to the bronze QA questions with several Ollama models and score them.

Usage: python scripts/eval_generation.py [--dataset data/eval/bronze_qa.json] [--models M ...]
                                         [--k 5] [--run-dir data/eval/runs/<ts>] [--think]

Retrieves the top-k chunks once per question and gives the same context to every model, so the
comparison is only about generation. Per answer it records the cited chunks, latency and
tokens/s plus automatic checks: citation validity, whether a cited chunk holds the gold
evidence, token F1 against the reference answer, and abstention (NOT_IN_SOURCES) on
unanswerable questions. Writes <run-dir>/generations.json after every answer; rerunning with the
same --run-dir resumes, skipping (model, question) pairs already done. LLM-as-judge scores come
from scripts/judge_generations.py; scripts/report_eval.py summarises.
"""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from rag_common import (
    DATASET,
    GENERATION_OPTIONS,
    MODELS,
    RUNS_DIR,
    K,
    OllamaChat,
    RetrievedChunk,
    answer,
    connect,
    corpus_snapshot,
    load_dataset,
    query_embedder,
    relevant_evidence,
    retrieve,
    token_f1,
    write_json,
)


def checks(item: dict, result, context: list[RetrievedChunk]) -> dict:
    answerable = bool(item["evidence"])
    gold = [bool(relevant_evidence(c.id, c.text, item)) for c in context]
    cited_gold = [bool(relevant_evidence(c.id, c.text, item)) for c in result.citations]
    return {
        "abstained": result.abstained,
        "abstention_correct": result.abstained != answerable,
        "has_citation": bool(result.citations),
        "citations_valid": not result.invalid_citations
        and (result.abstained or bool(result.citations)),
        "context_has_gold": any(gold) if answerable else None,
        "cites_gold": any(cited_gold) if answerable else None,
        "token_f1": round(token_f1(result.text, item["reference_answer"]), 3)
        if answerable
        else None,
    }


async def run(args: argparse.Namespace) -> None:
    dataset = load_dataset(args.dataset)
    out_path = args.run_dir / "generations.json"
    previous = json.loads(out_path.read_text()) if out_path.exists() else {}
    done = {(g["model"], g["id"]) for g in previous.get("generations", [])}

    embedder = query_embedder()
    conn = await connect()
    try:
        snapshot = await corpus_snapshot(conn)
        contexts = {}
        for q in dataset:
            # On resume, keep the context the earlier answers were generated from.
            if q["id"] in previous.get("questions", {}):
                contexts[q["id"]] = [
                    RetrievedChunk(**c) for c in previous["questions"][q["id"]]["context"]
                ]
            else:
                contexts[q["id"]] = await retrieve(conn, embedder, q["question"], args.k)
    finally:
        await conn.close()

    out = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": str(args.dataset),
        "k": args.k,
        "think": args.think,
        "options": GENERATION_OPTIONS,
        "models": args.models,
        "corpus": snapshot,
        "questions": {
            q["id"]: {
                "question": q["question"],
                "type": q["type"],
                "reference_answer": q["reference_answer"],
                "evidence": q["evidence"],
                "context": [{**asdict(c), "score": round(c.score, 4)} for c in contexts[q["id"]]],
            }
            for q in dataset
        },
        "generations": previous.get("generations", []),
    }
    write_json(out_path, out)

    # Model-major order: each model is loaded once (they do not all fit in VRAM together).
    for model in args.models:
        chat = OllamaChat(model, think=args.think)
        for item in dataset:
            if (model, item["id"]) in done:
                continue
            context = contexts[item["id"]]
            try:
                result = answer(item["question"], context, chat)
            except Exception as e:  # keep going: one failed call must not stop the run
                print(f"FAILED  {model}  {item['id']}: {type(e).__name__}: {e}")
                continue
            out["generations"].append(
                {
                    "id": item["id"],
                    "model": model,
                    "answer": result.text,
                    "cited": [c.id for c in result.citations],
                    "invalid_citations": result.invalid_citations,
                    "checks": checks(item, result, context),
                    "stats": result.stats,
                }
            )
            write_json(out_path, out)
            print(
                f"{model:18} {item['id']}  {result.stats['seconds']:>6}s  "
                f"cited {len(result.citations)}  {'ABSTAIN' if result.abstained else ''}"
            )
    print(f"\nwrote {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--models", nargs="+", default=MODELS)
    parser.add_argument("--k", type=int, default=K, help="chunks given to the models")
    parser.add_argument("--think", action="store_true", help="enable the models' thinking mode")
    parser.add_argument(
        "--run-dir", type=Path, default=RUNS_DIR / datetime.now().strftime("%Y%m%d-%H%M")
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
