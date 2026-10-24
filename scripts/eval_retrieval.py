"""Score retrieval from the pgvector `chunks` table against the bronze QA dataset.

Usage: python scripts/eval_retrieval.py [--dataset data/eval/bronze_qa.json] [--k 20]
                                        [--run-dir data/eval/runs/<ts>] [--check]

For every answerable question, retrieves the top-k chunks and scores them against the question's
evidence. A chunk is relevant to an evidence item if it contains the item's quote (whitespace-
normalised) or has its chunk id, so the dataset survives re-chunking. Reports Hit@1/3/5/10,
Recall@5/10 (share of evidence items found), MRR@10, nDCG@10 and a lenient source-level Hit@5,
overall and per source. Writes <run-dir>/retrieval.json.

--check only verifies that every evidence quote is still found in some chunk.
"""

import argparse
import asyncio
import json
import math
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from rag_common import (
    CANDIDATES,
    DATASET,
    RUNS_DIR,
    connect,
    corpus_snapshot,
    load_dataset,
    normalize,
    query_embedder,
    relevant_evidence,
    retrieve,
)

CUTOFFS = (1, 3, 5, 10)


def score(item: dict, ranked: list[tuple[str, str, str]]) -> dict:
    """Metrics for one question; `ranked` is (chunk_id, source_id, text) in rank order."""
    n_evidence = len(item["evidence"])
    covered: list[set[int]] = [relevant_evidence(cid, text, item) for cid, _, text in ranked]
    first = next((r for r, c in enumerate(covered, 1) if c), None)

    def found(k: int) -> set[int]:
        return set().union(*covered[:k])

    # Gain only for chunks that add a not-yet-found evidence item, so ideal DCG has n_evidence.
    dcg, seen = 0.0, set()
    for r, c in enumerate(covered[:10], 1):
        if c - seen:
            dcg += 1 / math.log2(r + 1)
            seen |= c
    idcg = sum(1 / math.log2(r + 1) for r in range(1, min(n_evidence, 10) + 1))
    sources = {ev["source_id"] for ev in item["evidence"]}
    return {
        **{f"hit@{k}": float(bool(found(k))) for k in CUTOFFS},
        "recall@5": len(found(5)) / n_evidence,
        "recall@10": len(found(10)) / n_evidence,
        "mrr@10": 1 / first if first and first <= 10 else 0.0,
        "ndcg@10": dcg / idcg,
        "source_hit@5": float(any(s in sources for _, s, _ in ranked[:5])),
        "first_relevant_rank": first,
    }


def mean_metrics(rows: list[dict]) -> dict:
    keys = [k for k in rows[0] if k != "first_relevant_rank"]
    return {k: round(statistics.fmean(r[k] for r in rows), 3) for k in keys} | {"n": len(rows)}


async def check(dataset: list[dict]) -> int:
    conn = await connect()
    try:
        chunks = {
            r["id"]: normalize(r["text"]) for r in await conn.fetch("SELECT id, text FROM chunks")
        }
    finally:
        await conn.close()
    missing = 0
    for item in dataset:
        for ev in item["evidence"]:
            quote = normalize(ev["quote"])
            if not any(quote in text for text in chunks.values()):
                missing += 1
                print(f"MISSING {item['id']}  {ev['source_id']}: {ev['quote'][:80]!r}")
            elif quote not in chunks.get(ev["chunk_id"], ""):
                print(f"moved   {item['id']}  {ev['chunk_id']} no longer holds the quote")
    print(f"{missing} missing quotes in {len(dataset)} questions")
    return missing


async def run(args: argparse.Namespace) -> None:
    dataset = [q for q in load_dataset(args.dataset) if q["evidence"]]
    embedder = query_embedder()
    conn = await connect()
    try:
        snapshot = await corpus_snapshot(conn)
        results = []
        for item in dataset:
            chunks = await retrieve(conn, embedder, item["question"], args.k)
            metrics = score(item, [(c.id, c.source_id, c.text) for c in chunks])
            results.append(
                {
                    "id": item["id"],
                    "type": item["type"],
                    "sources": sorted({ev["source_id"] for ev in item["evidence"]}),
                    "question": item["question"],
                    "metrics": metrics,
                    "retrieved": [{"id": c.id, "score": round(c.score, 4)} for c in chunks[:10]],
                }
            )
            print(f"{item['id']}  first relevant rank {metrics['first_relevant_rank']}")
    finally:
        await conn.close()

    by_source = defaultdict(list)
    by_type = defaultdict(list)
    for r in results:
        by_type[r["type"]].append(r["metrics"])
        for s in r["sources"]:
            by_source[s].append(r["metrics"])
    summary = {
        "overall": mean_metrics([r["metrics"] for r in results]),
        "by_type": {t: mean_metrics(rows) for t, rows in sorted(by_type.items())},
        "by_source": {s: mean_metrics(rows) for s, rows in sorted(by_source.items())},
    }

    args.run_dir.mkdir(parents=True, exist_ok=True)
    (args.run_dir / "retrieval.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "dataset": str(args.dataset),
                "k": args.k,
                "corpus": snapshot,
                "summary": summary,
                "questions": results,
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    cols = ["n", "hit@1", "hit@3", "hit@5", "hit@10", "recall@5", "recall@10", "mrr@10",
            "ndcg@10", "source_hit@5"]  # fmt: skip
    print(f"\n{'':48}" + "".join(f"{c:>13}" for c in cols))
    rows = [("overall", summary["overall"])]
    rows += [(f"type: {t}", m) for t, m in summary["by_type"].items()]
    rows += [(f"  {s}", m) for s, m in summary["by_source"].items()]
    for name, m in rows:
        print(f"{name:48}" + "".join(f"{m[c]:>13}" for c in cols))
    print(f"\nwrote {args.run_dir / 'retrieval.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--k", type=int, default=CANDIDATES, help="retrieval depth")
    parser.add_argument(
        "--run-dir", type=Path, default=RUNS_DIR / datetime.now().strftime("%Y%m%d-%H%M")
    )
    parser.add_argument("--check", action="store_true", help="only verify the evidence quotes")
    args = parser.parse_args()
    if args.check:
        raise SystemExit(1 if asyncio.run(check(load_dataset(args.dataset))) else 0)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
