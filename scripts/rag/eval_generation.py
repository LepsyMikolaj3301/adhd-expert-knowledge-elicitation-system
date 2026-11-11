"""Generate answers to the bronze QA questions with several Ollama models and score them.

Usage: python scripts/rag/eval_generation.py [--dataset data/eval/bronze_qa.json] [--models M ...]
                                         [--k 5] [--retrieval dense|bm25|hybrid]
                                         [--samples 1] [--temperature T]
                                         [--contexts retrieved oracle] [--only ID ...]
                                         [--run-dir data/eval/runs/<ts>] [--think]
       python scripts/rag/eval_generation.py --run-dir ... --import-answers FILE --as-model NAME

Retrieves the top-k chunks once per question and gives the same context to every model, so the
comparison is only about generation. With `--contexts ... oracle` every answerable question is
also asked with its gold chunks forced into the context (rag_common.oracle_context): failing on
`retrieved` but passing on `oracle` points at retrieval. When the gold chunks were retrieved
anyway the oracle context is identical and is not asked again. With --samples N each question
is asked N times (temperature --temperature, default 0.7 when N > 1; seed = sample number), to
see how stable the answers are.

Per answer it records the cited chunks, latency and tokens/s plus automatic checks: citation
validity, whether a cited chunk holds the gold evidence, token F1 against the reference answer,
and abstention (NOT_IN_SOURCES) on unanswerable questions. Writes <run-dir>/generations.json
after every answer; rerunning with the same --run-dir resumes, skipping (model, question,
context, sample) entries already done and reusing the stored contexts.

--import-answers adds answers produced outside Ollama (e.g. a larger model given the same system
prompt and context) as model NAME: FILE is {"<id>|<context>|<sample>": "<answer text>", ...}.
LLM-as-judge scores come from scripts/rag/judge_generations.py; scripts/rag/report_eval.py summarises.
"""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from rag_common import (
    DATASET,
    FUSION_DEPTH,
    GENERATION_OPTIONS,
    MODELS,
    NOT_IN_SOURCES,
    RETRIEVAL,
    RETRIEVAL_MODES,
    RRF_K,
    RUNS_DIR,
    SAMPLING_TEMPERATURE,
    K,
    OllamaChat,
    RetrievedChunk,
    answer,
    bm25_config,
    cited_numbers,
    connect,
    corpus_snapshot,
    load_dataset,
    oracle_context,
    query_embedder,
    relevant_evidence,
    retrieve,
    token_f1,
    write_json,
)

CONTEXTS = ("retrieved", "oracle")


def checks(item: dict, text: str, cited: list[RetrievedChunk], invalid: list[int],
           context: list[RetrievedChunk]) -> dict:  # fmt: skip
    answerable = bool(item["evidence"])
    abstained = NOT_IN_SOURCES in text
    return {
        "abstained": abstained,
        "abstention_correct": abstained != answerable,
        "has_citation": bool(cited),
        "citations_valid": not invalid and (abstained or bool(cited)),
        "context_has_gold": any(relevant_evidence(c.id, c.text, item) for c in context)
        if answerable
        else None,
        "cites_gold": any(relevant_evidence(c.id, c.text, item) for c in cited)
        if answerable
        else None,
        "token_f1": round(token_f1(text, item["reference_answer"]), 3) if answerable else None,
    }


def contexts_for(item: dict, names: list[str]) -> list[str]:
    """Unanswerable questions have no gold chunks, so only the retrieved context."""
    return [c for c in names if c == "retrieved" or item["evidence"]]


def same_ids(a: list[RetrievedChunk], b: list[RetrievedChunk]) -> bool:
    return [c.id for c in a] == [c.id for c in b]


async def build_contexts(dataset: list[dict], previous: dict, args) -> tuple[dict, dict]:
    """{question id: {context name: chunks}}; contexts stored in `previous` are kept."""
    embedder = query_embedder()
    sparse_config = bm25_config()
    conn = await connect()
    contexts: dict[str, dict[str, list[RetrievedChunk]]] = {}
    try:
        for q in dataset:
            stored = previous.get("questions", {}).get(q["id"], {}).get("contexts", {})
            ctx = {name: [RetrievedChunk(**c) for c in chunks] for name, chunks in stored.items()}
            if "retrieved" not in ctx:
                ctx["retrieved"] = await retrieve(
                    conn, embedder, q["question"], args.k, args.retrieval, sparse_config
                )
            if "oracle" in contexts_for(q, args.contexts) and "oracle" not in ctx:
                ctx["oracle"] = await oracle_context(conn, embedder, q, ctx["retrieved"])
            contexts[q["id"]] = ctx
        snapshot = await corpus_snapshot(conn)
    finally:
        await conn.close()
    return contexts, snapshot


def generation_row(item, model, context_name, sample, text, cited, invalid, context, stats):
    return {
        "id": item["id"],
        "model": model,
        "context": context_name,
        "sample": sample,
        "answer": text,
        "cited": [c.id for c in cited],
        "invalid_citations": invalid,
        "checks": checks(item, text, cited, invalid, context),
        "stats": stats,
    }


def import_answers(out: dict, dataset: list[dict], contexts: dict, args) -> None:
    items = {q["id"]: q for q in dataset}
    for key, text in json.loads(args.import_answers.read_text()).items():
        qid, context_name, sample = key.split("|")
        context = contexts[qid][context_name]
        numbers = cited_numbers(text)
        cited = [context[n - 1] for n in numbers if 1 <= n <= len(context)]
        invalid = [n for n in numbers if not 1 <= n <= len(context)]
        out["generations"] = [
            g
            for g in out["generations"]
            if (g["model"], g["id"], g["context"], g["sample"])
            != (args.as_model, qid, context_name, int(sample))
        ]
        out["generations"].append(
            generation_row(
                items[qid],
                args.as_model,
                context_name,
                int(sample),
                text.strip(),
                cited,
                invalid,
                context,
                {"seconds": None, "tokens_per_s": None},
            )  # fmt: skip
        )
    print(f"imported answers as {args.as_model}")


async def run(args: argparse.Namespace) -> None:
    dataset = load_dataset(args.dataset)
    if args.only:
        dataset = [q for q in dataset if q["id"] in args.only]
    out_path = args.run_dir / "generations.json"
    previous = json.loads(out_path.read_text()) if out_path.exists() else {}
    contexts, snapshot = await build_contexts(dataset, previous, args)

    temperature = args.temperature
    if temperature is None:
        temperature = (
            SAMPLING_TEMPERATURE if args.samples > 1 else GENERATION_OPTIONS["temperature"]
        )
    out = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": str(args.dataset),
        "k": args.k,
        "retrieval": args.retrieval,
        "fusion": {"rrf_k": RRF_K, "depth": FUSION_DEPTH} if args.retrieval == "hybrid" else None,
        "think": args.think,
        "options": {**GENERATION_OPTIONS, "temperature": temperature},
        "samples": max(args.samples, previous.get("samples", 1)),
        "models": sorted({*previous.get("models", []), *args.models}),
        "corpus": snapshot,
        "questions": {
            **previous.get("questions", {}),
            **{
                q["id"]: {
                    "question": q["question"],
                    "type": q["type"],
                    "reference_answer": q["reference_answer"],
                    "evidence": q["evidence"],
                    "contexts": {
                        name: [{**asdict(c), "score": round(c.score, 4)} for c in chunks]
                        for name, chunks in contexts[q["id"]].items()
                    },
                }
                for q in dataset
            },
        },
        "generations": previous.get("generations", []),
    }
    if args.import_answers:
        out["models"] = sorted({*out["models"], args.as_model})
        import_answers(out, dataset, contexts, args)
        write_json(out_path, out)
        return
    write_json(out_path, out)
    done = {(g["model"], g["id"], g["context"], g["sample"]) for g in out["generations"]}

    # Model-major order: each model is loaded once (they do not all fit in VRAM together).
    for model in args.models:
        for item in dataset:
            for context_name in contexts_for(item, args.contexts):
                context = contexts[item["id"]][context_name]
                if context_name != "retrieved" and same_ids(
                    context, contexts[item["id"]]["retrieved"]
                ):
                    continue  # gold already retrieved: the oracle answers would be duplicates
                for sample in range(1, args.samples + 1):
                    if (model, item["id"], context_name, sample) in done:
                        continue
                    chat = OllamaChat(model, think=args.think, temperature=temperature, seed=sample)
                    try:
                        result = answer(item["question"], context, chat)
                    except Exception as e:  # keep going: one failed call must not stop the run
                        print(f"FAILED  {model}  {item['id']}: {type(e).__name__}: {e}")
                        continue
                    out["generations"].append(
                        generation_row(
                            item,
                            model,
                            context_name,
                            sample,
                            result.text,
                            result.citations,
                            result.invalid_citations,
                            context,
                            result.stats,
                        )  # fmt: skip
                    )
                    write_json(out_path, out)
                    print(
                        f"{model:12} {item['id']} {context_name:9} #{sample}  "
                        f"{result.stats['seconds']:>6}s  cited {len(result.citations)}  "
                        f"{'ABSTAIN' if result.abstained else ''}"
                    )
    print(f"\nwrote {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--models", nargs="+", default=MODELS)
    parser.add_argument("--k", type=int, default=K, help="chunks given to the models")
    parser.add_argument("--retrieval", choices=RETRIEVAL_MODES, default=RETRIEVAL)
    parser.add_argument("--samples", type=int, default=1, help="times each question is asked")
    parser.add_argument("--temperature", type=float, help="default 0, or 0.7 with --samples > 1")
    parser.add_argument("--contexts", nargs="+", choices=CONTEXTS, default=["retrieved"])
    parser.add_argument("--only", nargs="+", metavar="ID", help="only these question ids")
    parser.add_argument("--think", action="store_true", help="enable the models' thinking mode")
    parser.add_argument(
        "--run-dir", type=Path, default=RUNS_DIR / datetime.now().strftime("%Y%m%d-%H%M")
    )
    parser.add_argument("--import-answers", type=Path, metavar="FILE")
    parser.add_argument("--as-model", help="model name for --import-answers")
    args = parser.parse_args()
    if args.import_answers and not args.as_model:
        parser.error("--import-answers needs --as-model")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
