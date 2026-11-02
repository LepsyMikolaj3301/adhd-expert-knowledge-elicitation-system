"""Metrics for expert-unit retrieval (scripts/rag/eval_expert_units.py). Pure: numpy only.

A ranking is a list of `Item`s; each holds one or more unit ids. Relevance comes from claims:
`covers[claim_id]` is the set of units that hold the claim, and a query's `relevant` claims are
recalled when one of their units is in the result.
"""

import math
from dataclasses import dataclass

import numpy as np

BUDGETS = (300, 500, 800)  # tokens of expert context given to the generator
KS = (1, 4, 8)  # result sizes in items; the generator gets about 4 expert units


@dataclass
class Item:
    unit_ids: list[str]  # units this item holds, in reading order
    shown: str  # what the generator would get
    reps: list[str]  # what is searched


def tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def fill_budget(ranked: list[Item], budget: int) -> list[Item]:
    """Greedy fill down the ranking: an item that does not fit is skipped, a later short one may."""
    used, chosen = 0, []
    for item in ranked:
        cost = tokens(item.shown)
        if used + cost <= budget:
            used += cost
            chosen.append(item)
    return chosen


def ceiling(wanted: dict[str, set[str]], k: int) -> float:
    """Best recall any k units can reach (greedy set cover over the units' claims)."""
    left, got = set(wanted), 0
    for _ in range(k):
        best = max(
            {u for c in left for u in wanted[c]},
            key=lambda u: sum(u in wanted[c] for c in left),
            default=None,
        )
        if best is None:
            break
        hit = {c for c in left if best in wanted[c]}
        got += len(hit)
        left -= hit
    return got / len(wanted)


def score_query(ranked: list[Item], relevant: list[str], covers: dict[str, set[str]]) -> dict:
    """Per-query metrics; {} when none of the relevant claims is held by any unit."""
    wanted = {c: covers[c] for c in relevant if covers[c]}
    if not wanted:
        return {}
    relevant_units = set().union(*wanted.values())
    out: dict[str, float] = {}
    for k in KS:
        got = {u for item in ranked[:k] for u in item.unit_ids}
        recalled = sum(bool(cov & got) for cov in wanted.values())
        out[f"recall@{k}"] = recalled / len(wanted)
        out[f"hit@{k}"] = float(recalled > 0)
    out["ceiling@4"] = ceiling(wanted, 4)
    out["recall@4/ceiling"] = out["recall@4"] / out["ceiling@4"]  # 4 units rarely hold everything
    first = next((r for r, i in enumerate(ranked, 1) if relevant_units & set(i.unit_ids)), None)
    out["mrr"] = 1 / first if first else 0.0
    flat = [uid for item in ranked for uid in item.unit_ids][:10]
    dcg = sum(1 / math.log2(r + 1) for r, uid in enumerate(flat, 1) if uid in relevant_units)
    ideal = sum(1 / math.log2(r + 1) for r in range(1, min(10, len(relevant_units)) + 1))
    out["ndcg@10"] = dcg / ideal
    for budget in BUDGETS:
        chosen = fill_budget(ranked, budget)
        got = {u for item in chosen for u in item.unit_ids}
        recalled = sum(bool(cov & got) for cov in wanted.values())
        out[f"recall@{budget}t"] = recalled / len(wanted)
        if budget == 500:
            out["claims_per_100t"] = recalled / max(sum(tokens(i.shown) for i in chosen), 1) * 100
    return out


def bootstrap(values, n: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """Mean and 95% interval of the mean, resampling queries."""
    v = np.asarray(values, dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(v), size=(n, len(v)))
    means = v[idx].mean(axis=1)
    return float(v.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def paired_bootstrap(a, b, n: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """Mean difference a - b over the same queries, with its 95% interval."""
    return bootstrap(np.asarray(a, dtype=float) - np.asarray(b, dtype=float), n, seed)


def weighted_kappa(a, b, levels: int = 5) -> float | None:
    """Quadratic weighted kappa between two raters' 1..levels scores; None if undefined."""
    a, b = np.asarray(a) - 1, np.asarray(b) - 1
    obs = np.zeros((levels, levels))
    for i, j in zip(a, b, strict=True):
        obs[i, j] += 1
    expected = np.outer(obs.sum(1), obs.sum(0)) / obs.sum()
    w = (np.subtract.outer(np.arange(levels), np.arange(levels)) ** 2) / (levels - 1) ** 2
    denom = (w * expected).sum()
    return None if denom == 0 else float(1 - (w * obs).sum() / denom)
