"""Answer one question with retrieval-augmented generation over the pgvector `chunks` table.

Usage: python scripts/rag/ask.py "question" [--model qwen3.5:9b] [--k 5] [--retrieval hybrid]
                             [--think] [--show-context]

Takes the top-k chunks for the question (dense bge-m3, BM25, or both fused with RRF), asks an
Ollama chat model to answer from them with [n] citations, and prints the answer followed by the
cited chunks only (chunk id · source · heading · pages).
"""

import argparse
import asyncio

from rag_common import (
    MODELS,
    RETRIEVAL,
    RETRIEVAL_MODES,
    K,
    OllamaChat,
    answer,
    connect,
    query_embedder,
    retrieve,
)


async def run(args: argparse.Namespace) -> None:
    conn = await connect()
    try:
        chunks = await retrieve(conn, query_embedder(), args.question, args.k, args.retrieval)
    finally:
        await conn.close()
    if args.show_context:
        for n, c in enumerate(chunks, 1):
            print(f"[{n}] {c.score:.3f}  {c.provenance()}")
        print()

    result = answer(args.question, chunks, OllamaChat(args.model, think=args.think))
    print(result.text, "\n")
    print("Sources:")
    for c in result.citations:
        print(f"  [{chunks.index(c) + 1}] {c.provenance()}")
    if not result.citations:
        print("  (none cited)")
    if result.invalid_citations:
        print(f"  invalid citations: {result.invalid_citations}")
    stats = result.stats
    print(f"\n{args.model}: {stats['seconds']}s, {stats['tokens_per_s']} tok/s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--model", default=MODELS[0])
    parser.add_argument("--k", type=int, default=K, help="chunks given to the model")
    parser.add_argument("--retrieval", choices=RETRIEVAL_MODES, default=RETRIEVAL)
    parser.add_argument("--think", action="store_true", help="enable the model's thinking mode")
    parser.add_argument("--show-context", action="store_true", help="list all retrieved chunks")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
