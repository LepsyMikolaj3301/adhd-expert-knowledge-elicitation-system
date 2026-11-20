# ruff: noqa: E501  (report strings)
"""How much experts agree on the passages of a text, measured on a schema of many experts.

Usage: python scripts/rag/eval_agreement.py --out data/eval/agreement/<name> \
           [--schema chips_scale] [--thresholds 0.3 0.5 0.7] [--level2 0.85] [--bootstrap 2000]

Reads the experts' highlights of the schema (no model, no application tables) and groups them with
the code the application uses (expert_knowledge_core.agreement). Writes <out>/results.json,
<out>/report.md and <out>/level2_candidates.csv.

  groups        for each IoU threshold: how many, how many experts per group, how the labels fall
  alpha         Krippendorff's alpha, nominal, with a 95% bootstrap interval over vignettes
                  attention  unit = a group, coder = an expert who answered that vignette,
                             value = marked it / did not
                  direction  unit = a group of two or more experts, value = the expert's direction
                             (mixed = contradicted themselves)
  level 2       pairs of units of different experts, same text, in different groups, same direction,
                cosine of their stored I1 vectors >= --level2: the same reading of a *different*
                passage. Only candidates, written for a human to label. Never used by retrieval:
                the embedding cannot tell a reading from its negation (see the report).

Reading the alpha: a group exists only because somebody marked it, so attention alpha is biased
low (units nobody marked are absent); the unitizing alpha would not be, and is not implemented
here. Experts 3+ of chips_scale are written by language models, who agree with each other more
than clinicians would: the numbers show the mechanism, not a finding about clinicians.
"""

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg

from app.settings import settings
from expert_knowledge_core.agreement import (
    IOU_THRESHOLD,
    Mark,
    agreement_groups,
    expert_directions,
)

ROOT = Path(__file__).resolve().parents[2]
ATTENTION = ["not marked", "marked"]
DIRECTIONS = ["toward", "away", "neutral", "unclear", "mixed"]


# --- reading the schema ---------------------------------------------------------------------


def read_marks(conn: psycopg.Connection, schema: str):
    """marks[(vignette, version)] -> [Mark], answered[(vignette, version)] -> {expert}."""
    marks: dict[tuple[str, int], list[Mark]] = defaultdict(list)
    query = (
        f"SELECT h.id, s.expert_id, lower(h.span), upper(h.span), h.direction, h.vignette_id, "
        f"h.vignette_version FROM {schema}.highlights h "
        f"JOIN {schema}.elicitation_sessions s ON s.id = h.session_id WHERE h.origin = 'expert'"
    )
    for hid, expert, a, b, direction, vid, ver in conn.execute(query).fetchall():
        marks[(vid, ver)].append(Mark(hid, expert, (a, b), direction))
    answered: dict[tuple[str, int], set[str]] = defaultdict(set)
    for expert, vid, ver in conn.execute(
        f"SELECT DISTINCT expert_id, vignette_id, vignette_version FROM {schema}.finding_units"
    ).fetchall():
        answered[(vid, ver)].add(expert)
    return marks, answered


# --- Krippendorff's alpha, nominal ----------------------------------------------------------


def coincidences(unit_counts: list[list[int]]) -> np.ndarray:
    """The coincidence matrix of units given as category counts (one row per unit). A unit read by
    fewer than two coders pairs with nobody and is left out."""
    size = len(unit_counts[0]) if unit_counts else 0
    total = np.zeros((size, size))
    for counts in unit_counts:
        c = np.asarray(counts, dtype=float)
        m = c.sum()
        if m >= 2:
            total += (np.outer(c, c) - np.diag(c)) / (m - 1)
    return total


def alpha_from(coincidence: np.ndarray) -> float | None:
    n_c = coincidence.sum(axis=1)
    n = n_c.sum()
    expected = float(np.outer(n_c, n_c).sum() - (n_c**2).sum())
    if n < 2 or expected == 0:
        return None
    observed = float(coincidence.sum() - np.trace(coincidence))
    return 1 - (n - 1) * observed / expected


def bootstrap_alpha(
    per_vignette: dict, rng: np.random.Generator, rounds: int
) -> tuple[float | None, list[float | None]]:
    """alpha over every vignette, and its 95% interval from resampling vignettes (sums of their
    coincidence matrices, so a resample costs almost nothing)."""
    keys = list(per_vignette)
    if not keys:
        return None, [None, None]
    matrices = np.stack([per_vignette[k] for k in keys])
    point = alpha_from(matrices.sum(axis=0))
    draws = []
    for _ in range(rounds):
        pick = rng.integers(0, len(keys), len(keys))
        value = alpha_from(matrices[pick].sum(axis=0))
        if value is not None:
            draws.append(value)
    if len(draws) < rounds // 2:
        return point, [None, None]
    return point, [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))]


def alphas(marks, answered, threshold: float, rng, rounds: int, vignettes=None) -> dict:
    attention, direction = {}, {}
    for key, vignette_marks in marks.items():
        if vignettes is not None and key[0] not in vignettes:
            continue
        coders = answered.get(key, set())
        groups = agreement_groups(vignette_marks, len(coders), threshold)
        attn_units, dir_units = [], []
        for members, _ in groups:
            per_expert = expert_directions(members)
            marked = len(per_expert)
            attn_units.append([len(coders) - marked, marked])
            if marked >= 2:
                counts = Counter(per_expert.values())
                dir_units.append([counts.get(d, 0) for d in DIRECTIONS])
        if attn_units:
            attention[key] = coincidences(attn_units)
        if dir_units:
            direction[key] = coincidences(dir_units)
    out = {}
    for name, per_vignette in (("attention", attention), ("direction", direction)):
        point, interval = bootstrap_alpha(per_vignette, rng, rounds)
        out[name] = {"alpha": point, "ci95": interval, "vignettes": len(per_vignette)}
    return out


# --- groups ---------------------------------------------------------------------------------


def group_stats(marks, answered, threshold: float) -> dict:
    labels: Counter[str] = Counter()
    sizes, shares, differing_pairs, pairs = [], [], 0, 0
    for key, vignette_marks in marks.items():
        n = len(answered.get(key, ()))
        for members, a in agreement_groups(vignette_marks, n, threshold):
            labels[a.label] += 1
            sizes.append(a.k)
            shares.append(a.k / a.n)
            by_expert = expert_directions(members)
            experts = list(by_expert)
            for i, first in enumerate(experts):
                for second in experts[i + 1 :]:
                    pairs += 1
                    differing_pairs += by_expert[first] != by_expert[second]
    return {
        "groups": len(sizes),
        "labels": dict(labels),
        "k_median": statistics.median(sizes) if sizes else None,
        "k_max": max(sizes, default=None),
        "k_over_n_median": statistics.median(shares) if shares else None,
        "share_k_ge_2": sum(s >= 2 for s in sizes) / len(sizes) if sizes else None,
        "expert_pairs_in_a_group": pairs,
        "share_of_those_pairs_reading_differently": differing_pairs / pairs if pairs else None,
    }


# --- level 2 --------------------------------------------------------------------------------


def level_two(
    conn: psycopg.Connection, schema: str, marks, answered, cosine: float, out: Path
) -> dict:
    """Units of different experts, same text, in different groups, same direction, cosine >= `cosine`."""
    group_of: dict[str, tuple[str, int, int]] = {}
    for (vid, ver), vignette_marks in marks.items():
        for number, (members, _) in enumerate(
            agreement_groups(vignette_marks, len(answered.get((vid, ver), ())), IOU_THRESHOLD)
        ):
            for m in members:
                group_of[m.id] = (vid, ver, number)
    rows = conn.execute(
        f"SELECT a.id, b.id, a.vignette_id, a.expert_id, b.expert_id, a.direction, "
        f"1 - (a.embedding <=> b.embedding) AS cosine, a.embed_text, b.embed_text, "
        f"ha.id, hb.id FROM {schema}.finding_units a "
        f"JOIN {schema}.finding_units b ON a.vignette_id = b.vignette_id "
        f"AND a.vignette_version = b.vignette_version AND a.id < b.id AND a.expert_id <> b.expert_id "
        f"AND a.direction = b.direction AND a.kind = 'fragment' AND b.kind = 'fragment' "
        f"JOIN {schema}.highlights ha ON ha.id = a.highlight_id "
        f"JOIN {schema}.highlights hb ON hb.id = b.highlight_id "
        f"WHERE 1 - (a.embedding <=> b.embedding) >= %s ORDER BY cosine DESC",
        (cosine,),
    ).fetchall()
    kept = [r for r in rows if group_of.get(r[9]) != group_of.get(r[10])]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "vignette",
                "unit_a",
                "unit_b",
                "expert_a",
                "expert_b",
                "direction",
                "cosine",
                "text_a",
                "text_b",
                "same_reading (yes/no)",
            ]
        )
        for r in kept:
            writer.writerow([r[2], r[0], r[1], r[3], r[4], r[5], f"{r[6]:.3f}", r[7], r[8], ""])
    return {
        "pairs_over_threshold": len(rows),
        "pairs_in_different_groups": len(kept),
        "same_group_share_of_those": 1 - len(kept) / len(rows) if rows else None,
    }


# --- report ---------------------------------------------------------------------------------


def fmt(x, digits=2):
    return "-" if x is None else f"{x:.{digits}f}"


def interval(a: dict) -> str:
    lo, hi = a["ci95"]
    return f"{fmt(a['alpha'])} [{fmt(lo)}, {fmt(hi)}]"


def report(results: dict) -> str:
    lines = [
        f"# Agreement of experts on passages ({results['schema']}, {results['when']})",
        "",
        f"{results['experts']} experts, {results['vignettes']} vignettes, {results['highlights']} expert highlights. "
        f"Default IoU threshold {IOU_THRESHOLD}.",
        "",
        "## Groups by IoU threshold",
        "",
        "| IoU | groups | experts per group (median / max) | k/n median | groups with 2+ experts | labels | expert pairs reading differently |",
        "|---|---|---|---|---|---|---|",
    ]
    for t, g in results["by_threshold"].items():
        labels = ", ".join(f"{k} {v}" for k, v in sorted(g["labels"].items()))
        lines.append(
            f"| {t} | {g['groups']} | {fmt(g['k_median'], 1)} / {g['k_max']} | {fmt(g['k_over_n_median'])} "
            f"| {fmt(g['share_k_ge_2'])} | {labels} | {fmt(g['share_of_those_pairs_reading_differently'])} |"
        )
    lines += [
        "",
        "## Krippendorff's alpha (nominal), 95% interval over vignettes",
        "",
        "| IoU | scope | attention | direction (groups of 2+) |",
        "|---|---|---|---|",
    ]
    for t, scopes in results["alpha"].items():
        for scope, a in scopes.items():
            lines.append(
                f"| {t} | {scope} ({a['attention']['vignettes']} vignettes) | {interval(a['attention'])} | {interval(a['direction'])} |"
            )
    lv = results["level2"]
    lines += [
        "",
        "## Same reading of a different passage (candidates only)",
        "",
        f"Cosine of the stored I1 vectors >= {results['level2_cosine']}, different experts, same text, same direction: "
        f"{lv['pairs_over_threshold']} pairs; {lv['pairs_in_different_groups']} of them are about passages that are not the same group "
        f"(the rest are the same passage, which level 1 already counts). Written to `level2_candidates.csv` for a human to label "
        f"`same_reading`. Nothing in retrieval or in an answer uses them.",
        "",
        "## Caveats",
        "",
        "- Experts 3+ of the scale schema are written by language models; they agree with each other more than clinicians do. "
        "Read the numbers as how the measure behaves, not as a result about clinicians.",
        "- Attention alpha is biased low: a group exists only because someone marked it. Groups nobody marked cannot appear.",
        "- I1 contains a header and the patient's words in short quotes, so two units that quote the same words are similar by construction.",
        "- The embedding does not separate a reading from its negation (on this schema the median cosine of same-direction and opposite-direction "
        "units of overlapping passages differs by about 0.01), so level-2 candidates need a human.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--schema", default="chips_scale")
    parser.add_argument("--thresholds", type=float, nargs="+", default=[0.3, 0.5, 0.7])
    parser.add_argument("--level2", type=float, default=0.85)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--anchors", nargs="+", default=["V001", "V004", "V006", "V012"])
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    with psycopg.connect(settings.database_url) as conn:
        marks, answered = read_marks(conn, args.schema)
        results = {
            "schema": args.schema,
            "when": datetime.now(UTC).strftime("%Y-%m-%d"),
            "experts": len({e for experts in answered.values() for e in experts}),
            "vignettes": len(marks),
            "highlights": sum(len(m) for m in marks.values()),
            "iou_default": IOU_THRESHOLD,
            "by_threshold": {},
            "alpha": {},
            "level2_cosine": args.level2,
        }
        for t in args.thresholds:
            results["by_threshold"][str(t)] = group_stats(marks, answered, t)
            results["alpha"][str(t)] = {
                "all vignettes": alphas(marks, answered, t, rng, args.bootstrap),
                "anchors": alphas(marks, answered, t, rng, args.bootstrap, set(args.anchors)),
            }
        results["level2"] = level_two(
            conn, args.schema, marks, answered, args.level2, args.out / "level2_candidates.csv"
        )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2, default=float) + "\n")
    text = report(results)
    (args.out / "report.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
