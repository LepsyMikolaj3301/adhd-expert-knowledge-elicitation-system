"""Compare ways to index expert answers for retrieval, in memory (docs/expert-knowledge.md).

Usage: python scripts/rag/eval_expert_units.py --tier silver [--experiments B B1 B1+mmr ...]
       python scripts/rag/eval_expert_units.py --tier silver --make-queries   # write the request

Representations (searched with bge-m3 dense + BM25, fused with RRF like the literature chunks):
  A  answer-level: each Q answer verbatim          C   the LLM reading rule alone is the unit
  B  header + 2 vignette sentences + the point     D   B, searched also through rule + questions
  B1 as B, one short vignette sentence (lean)      D1  B1, searched also through rule + questions
  Bs as B1 for search, shown in full like B
An experiment label is `<representation>[/dense|/bm25][+cap|+mmr]`: retrieval mode (default hybrid)
and diversity re-ranking (`cap`: one result per vignette and question first; `mmr`: lambda 0.7).

Ground truth is the fixture's reference claims. A unit holds a claim when one of its quote spans
overlaps the claim's quoted span; otherwise the unit of the same answer closest to the claim text by
bge-m3 holds it. Question-mode labels are the claims a Claude agent listed ("original"), plus the
claims another agent marked relevant among everything any experiment returned in its top 8
("pooled", via the inbox: prompts/Expert_unit_pooling.v1.md). Both are reported.

Metrics: claim recall@k / hit@k / MRR / nDCG@10 over the result, the best recall 4 units could
reach (`ceiling@4`), and claim recall within a 500-token budget (greedy fill) with claims per 100
tokens. Intervals are 95% bootstrap over questions; differences are paired. The representation for
the generation test is the best verbatim-unit experiment under pooled labels (ties: cheaper, no LLM
keys); it is written to the report as `selected`. --patient adds the (weak) patient-text mode.
Writes data/eval/expert_units/<timestamp>.json and latest.json.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from expert_metrics import BUDGETS, bootstrap, paired_bootstrap, score_query, tokens
from expert_retrieval import (
    LEAN,
    POOL_DEPTH,
    AwaitingResponse,
    Searcher,
    build_indexes,
    cover_claims,
    load_fixture,
    load_keys,
    load_pool,
    load_questions,
    make_embed,
    patient_queries,
    pool_requests,
)
from make_unit_keys import ROOT, load_units
from rag_common import bm25_config, query_embedder, write_json

from app.indexing import bm25

DEFAULT_EXPERIMENTS = [
    "A", "B", "Bs", "B1", "C", "D", "D1",  # representations
    "B/dense", "B/bm25", "B1/dense", "B1/bm25",  # which side the text helps
    "B1+cap", "B1+mmr", "D1+mmr",  # diversity
]  # fmt: skip
VERBATIM = {"B", "Bs", "B1", "D", "D1"}  # representations that show the clinician's own words
KEYED = {"C", "D", "D1"}
COMPARISONS = [  # (a, b): what a adds over b
    ("B1", "B"), ("Bs", "B"), ("D", "B"), ("D1", "B1"),
    ("B1+cap", "B1"), ("B1+mmr", "B1"), ("D1+mmr", "B1+mmr"), ("C", "B1"), ("A", "B1"),
]  # fmt: skip
HEADLINE = [
    "recall@4", "recall@4/ceiling", "hit@4", "mrr", "ndcg@10", "ceiling@4", "recall@500t",
    "claims_per_100t",
]  # fmt: skip
WITH_CI = ("recall@4", "ndcg@10")


def parse(label: str) -> tuple[str, str, str]:
    """'B1/dense+mmr' -> ('B1', 'dense', 'mmr')."""
    rest, _, diversity = label.partition("+")
    name, _, mode = rest.partition("/")
    return name, mode or "hybrid", diversity or "none"


def rank_all(indexes, queries, experiments, embed, cfg) -> dict[str, list[list]]:
    """{experiment: ranked items (top 50) per query}."""
    searchers = {name: Searcher(items, embed, cfg) for name, items in indexes.items()}
    out = {}
    for label in experiments:
        name, mode, diversity = parse(label)
        if name not in searchers:
            print(f"skipping {label}: no index {name}", file=sys.stderr)
            continue
        s = searchers[name]
        out[label] = []
        for q in queries:
            allowed = np.array(
                [it.unit_ids[0].split(":")[1] not in q.get("exclude", ()) for it in s.items]
            )
            out[label].append(
                [s.items[i] for i in s.rank(q["strings"], allowed, mode, diversity)[:50]]
            )
    return out


def score_all(rankings, queries, covers, label_key) -> dict[str, list[dict]]:
    return {
        label: [score_query(r, q[label_key], covers) for q, r in zip(queries, ranked, strict=True)]
        for label, ranked in rankings.items()
    }


def column(rows: list[dict], key: str) -> list[float]:
    return [r[key] for r in rows if r]


def summarise(scores, indexes) -> dict:
    out = {}
    for label, rows in scores.items():
        item_tokens = np.mean([tokens(it.shown) for it in indexes[parse(label)[0]]])
        out[label] = {"queries": len([r for r in rows if r]), "tokens_per_item": float(item_tokens)}
        for key in ["recall@1", "recall@8", "hit@8", *HEADLINE, *(f"recall@{b}t" for b in BUDGETS)]:
            out[label][key] = bootstrap(column(rows, key))
    return out


def print_table(title: str, summary: dict) -> None:
    n = max(r["queries"] for r in summary.values())
    print(f"\n{title}  (questions scored: {n}; 95% bootstrap interval where shown)")
    head = (
        f"{'':10}"
        + "".join(f"{c:>26}" if c in WITH_CI else f"{c:>18}" for c in HEADLINE)
        + f"{'tok/item':>10}"
    )
    print(head)
    for label, r in summary.items():
        cells = ""
        for c in HEADLINE:
            m, lo, hi = r[c]
            cells += f"{m:>9.3f} [{lo:.2f},{hi:.2f}]" if c in WITH_CI else f"{m:>18.3f}"
        print(f"{label:10}{cells}{r['tokens_per_item']:>10.0f}")


def compare(scores, metric: str = "recall@4") -> list[dict]:
    rows = []
    for a, b in COMPARISONS:
        if a in scores and b in scores:
            out = {"a": a, "b": b}
            for key in ("recall@4", "ndcg@10"):
                out[key] = paired_bootstrap(column(scores[a], key), column(scores[b], key))
            rows.append(out)
    return rows


def print_comparisons(rows: list[dict]) -> None:
    print("\npaired differences a - b  (a call is made only if the 95% interval excludes 0)")
    for r in rows:
        cells = []
        for key in ("recall@4", "ndcg@10"):
            m, lo, hi = r[key]
            verdict = "+" if lo > 0 else "-" if hi < 0 else "~"
            cells.append(f"{key} {m:+.3f} [{lo:+.3f},{hi:+.3f}] {verdict}")
        print(f"  {r['a']:>8} - {r['b']:<8} " + "   ".join(cells))


def select(scores, summary) -> str | None:
    """Best verbatim-unit experiment (mean of recall@4 and nDCG@10); anything not significantly
    worse than it competes on cost: no LLM keys first, then fewer tokens per item."""
    cands = [lb for lb in scores if parse(lb)[0] in VERBATIM and parse(lb)[1] == "hybrid"]
    if not cands:
        return None

    def quality(label):
        return np.mean([summary[label]["recall@4"][0], summary[label]["ndcg@10"][0]])

    top = max(cands, key=quality)
    top_q = np.array([column(scores[top], "recall@4"), column(scores[top], "ndcg@10")]).mean(axis=0)

    def not_worse(label) -> bool:
        q = np.array([column(scores[label], "recall@4"), column(scores[label], "ndcg@10")]).mean(
            axis=0
        )
        return paired_bootstrap(top_q, q)[1] <= 0  # lower bound of top - label includes 0

    eligible = [lb for lb in cands if lb == top or not_worse(lb)]
    return min(eligible, key=lambda lb: (parse(lb)[0] in KEYED, summary[lb]["tokens_per_item"], lb))


def pooled_candidates(rankings, queries, covers) -> list[list[str]]:
    """Per question: claims held by any experiment's top POOL_DEPTH items, and the original ones."""
    held: dict[str, set[str]] = {}
    for cid, units in covers.items():
        for u in units:
            held.setdefault(u, set()).add(cid)
    out = []
    for qi, q in enumerate(queries):
        pool = set(q["claim_ids"])
        for ranked in rankings.values():
            for item in ranked[qi][:POOL_DEPTH]:
                for uid in item.unit_ids:
                    pool |= held.get(uid, set())
        out.append(sorted(pool))
    return out


def distortion(units, keys, claims, covers) -> dict:
    """Heuristic: does a unit's rule flip a linked claim's direction or lose its condition?"""
    tok = bm25.Tokenizer(bm25_config())
    linked: dict[str, list[dict]] = {}
    for cid, cov in covers.items():
        for uid in cov:
            linked.setdefault(uid, []).append(claims[cid])
    flips = drops = directed = conditional = 0
    for u in units:
        if u.unit_id not in keys:
            continue
        key, cs = keys[u.unit_id], linked.get(u.unit_id, [])
        opposite = {"raises": "lowers", "lowers": "raises"}.get(key["direction"])
        if any(c.get("direction") for c in cs):
            directed += 1
            flips += any(c.get("direction") == opposite for c in cs)
        conds = [c["condition"] for c in cs if c.get("condition")]
        if conds:
            conditional += 1
            rule = set(tok(key["reading_rule"]))
            drops += all(not (set(tok(c)) & rule) for c in conds)
    return {
        "direction_flip": flips / directed if directed else None,
        "condition_dropped": drops / conditional if conditional else None,
        "units_with_direction": directed,
        "units_with_condition": conditional,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier", required=True, choices=["bronze", "silver", "gold"])
    ap.add_argument("--source", default="synthetic", choices=["synthetic", "reddit"])
    ap.add_argument("--inbox", type=Path, default=ROOT / "data/inbox")
    ap.add_argument("--out", type=Path, default=ROOT / "data/eval/expert_units")
    ap.add_argument("--experiments", nargs="+", default=DEFAULT_EXPERIMENTS)
    ap.add_argument("--patient", action="store_true", help="also run the weak patient-text mode")
    ap.add_argument("--make-queries", action="store_true", help="write the question request, stop")
    args = ap.parse_args(argv)

    vignettes, claims, answers = load_fixture(args.tier, args.source)
    if args.make_queries:
        try:
            load_questions(args.tier, vignettes, claims, args.inbox)
            print("queries already answered")
        except AwaitingResponse as e:
            print(e)
        return 0

    units, keys = load_units(args.tier, source=args.source), load_keys(args.tier, args.source)
    lean_units = load_units(args.tier, source=args.source, **LEAN)
    embed, cfg = make_embed(query_embedder()), bm25_config()
    covers = cover_claims(units, claims, vignettes, embed)
    print(
        f"{len(units)} units, {len(keys)} with keys, {len(claims)} claims, "
        f"{sum(not c for c in covers.values())} claims no unit holds"
    )
    indexes = build_indexes(units, lean_units, answers, keys)
    report: dict = {
        "source": args.source,
        "tier": args.tier,
        "units": len(units),
        "keys": len(keys),
    }

    try:
        questions = load_questions(args.tier, vignettes, claims, args.inbox)
    except AwaitingResponse as e:
        questions = []
        print(f"question mode skipped: {e}", file=sys.stderr)
    if questions:
        rankings = rank_all(indexes, questions, args.experiments, embed, cfg)
        pooled_ok = False
        try:
            marks = load_pool(
                pool_requests(
                    args.tier, questions, pooled_candidates(rankings, questions, covers), claims
                ),
                args.inbox,
            )
            for n, q in enumerate(questions):
                q["pooled_ids"] = sorted(set(q["claim_ids"]) | marks.get(n, set()))
            pooled_ok = True
            kept = sum(
                len(set(q["claim_ids"]) & marks.get(n, set())) for n, q in enumerate(questions)
            )
            total = sum(len(q["claim_ids"]) for q in questions)
            report["label_agreement"] = {
                "original_confirmed": kept / total,
                "added_per_question": float(
                    np.mean([len(q["pooled_ids"]) - len(q["claim_ids"]) for q in questions])
                ),
            }
            print(
                f"\nlabels: pooled check confirmed {kept}/{total} original labels, "
                f"added {report['label_agreement']['added_per_question']:.1f} per question"
            )
        except AwaitingResponse as e:
            print(f"\npooled labels not available yet: {e}", file=sys.stderr)
        report["question"] = {}
        for label_key in ("claim_ids", "pooled_ids") if pooled_ok else ("claim_ids",):
            name = "original" if label_key == "claim_ids" else "pooled"
            scores = score_all(rankings, questions, covers, label_key)
            summary = summarise(scores, indexes)
            comparisons = compare(scores)
            report["question"][name] = {"summary": summary, "comparisons": comparisons}
            print_table(f"question mode, {name} labels", summary)
            print_comparisons(comparisons)
            if name == "pooled" or not pooled_ok:
                report["selected"] = select(scores, summary)
        print(f"\nselected for the generation test: {report.get('selected')}")
        report["questions"] = [
            {k: q[k] for k in ("question", "claim_ids", "pooled_ids")} for q in questions
        ]

    if args.patient:
        patients = patient_queries(vignettes, claims)
        scores = score_all(
            rank_all(indexes, patients, args.experiments, embed, cfg), patients, covers, "claim_ids"
        )
        report["patient"] = summarise(scores, indexes)
        print_table("patient-text mode (weak labels)", report["patient"])

    report["distortion"] = distortion(units, keys, claims, covers)
    print("\nrule distortion (C and D share the rules):", json.dumps(report["distortion"]))
    path = args.out / f"{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    write_json(path, report)
    write_json(args.out / "latest.json", report)
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
