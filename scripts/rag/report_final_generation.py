# ruff: noqa: E501  (report strings)
"""Report of the final generation test: several models, contexts and question kinds in one run.

Usage: python scripts/rag/report_final_generation.py --run-dir data/eval/expert_runs/<A> \
           [--compare data/eval/expert_runs/<B>] [--reference qwen3.8:27b] [--out <file.md>]

Reads <run>/generations.json (try_expert_rag.py) and every <run>/judgments_<tag>.json
(judge_generations.py, e.g. two Claude passes j1 and j2). eval_expert_generation.py --report keys
judgments by question and context only (models overwrite each other there), so this report is separate;
it changes no score. Per answer, a judge field is the mean over the passes that graded it (pass: share
of passes that passed it); intervals are 95% bootstrap over questions, differences are paired on the
same questions. Sections: model x context; question kinds (rag); each model against --reference;
oracle - rag per model; --compare: the same model's rag answers in run B (e.g. no fragment grouping)
against run A; out-of-scope abstention and false abstention; judge agreement; speed and VRAM.
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
from expert_metrics import bootstrap, paired_bootstrap, weighted_kappa

FIELDS = ("key_points", "fidelity", "attribution", "usefulness", "citation_quality")
ALL = (*FIELDS, "pass", "unsupported_claims")


def load(run_dir: Path) -> tuple[dict, dict[str, list[dict]]]:
    run = json.loads((run_dir / "generations.json").read_text())
    judged = {
        p.stem.removeprefix("judgments").lstrip("_") or "main": json.loads(p.read_text())[
            "judgments"
        ]
        for p in sorted(run_dir.glob("judgments*.json"))
    }
    return run, judged


def merged(judged: dict[str, list[dict]]) -> dict[tuple, dict]:
    """(id, model, context) -> field means over the passes."""
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for rows in judged.values():
        for r in rows:
            by_key[(r["id"], r["model"], r["context"])].append(r)
    out = {}
    for key, rows in by_key.items():
        out[key] = {}
        for f in ALL:
            vals = [float(r[f]) for r in rows if r.get(f) is not None]
            out[key][f] = float(np.mean(vals)) if vals else None
        out[key]["abstention_ok"] = [r.get("abstention_ok") for r in rows]
    return out


def kind_of(q: dict) -> str:
    return q.get("kind") or q.get("suite") or q["type"]


def cell(vals: list[float], digits: int = 2) -> str:
    vals = [v for v in vals if v is not None]
    if not vals:
        return "–"
    m, lo, hi = bootstrap(vals)
    return f"{m:.{digits}f} [{lo:.{digits}f}, {hi:.{digits}f}]"


def diff(a: list, b: list) -> str:
    pairs = [(x, y) for x, y in zip(a, b, strict=True) if x is not None and y is not None]
    if len(pairs) < 3:
        return "–"
    d, lo, hi = paired_bootstrap([x for x, _ in pairs], [y for _, y in pairs])
    mark = " **≠0**" if lo > 0 or hi < 0 else ""
    return f"{d:+.2f} [{lo:+.2f}, {hi:+.2f}]{mark}"


def models_of(run: dict) -> list[str]:
    return list(dict.fromkeys(g["model"] for g in run["generations"]))


def report(run_dir: Path, compare: Path | None, reference: str) -> str:
    run, judged = load(run_dir)
    scores = merged(judged)
    qs = run["questions"]
    models = models_of(run)
    contexts = list(dict.fromkeys(g["context"] for g in run["generations"]))
    lines = [
        f"# Generacja: {run_dir.name}",
        "",
        f"Schemat `{run['schema']}`, wyszukiwanie `{run['search']}`, grupowanie fragmentów: "
        f"{run.get('group_fragments')}. Przejścia sędziego: {', '.join(judged) or 'brak'}. "
        "Pole = średnia z przejść; pass = odsetek przejść, które uznały odpowiedź; [95% bootstrap].",
    ]

    lines += ["", "## Model × kontekst", ""]
    lines += ["| model | kontekst | n | " + " | ".join(ALL) + " |", "|---" * (len(ALL) + 3) + "|"]
    for model in models:
        for context in contexts:
            rows = [v for (q, m, c), v in scores.items() if m == model and c == context]
            if rows:
                lines.append(
                    f"| {model} | {context} | {len(rows)} | "
                    + " | ".join(cell([r[f] for r in rows]) for f in ALL)
                    + " |"
                )

    lines += ["", "## Rodzaje pytań (kontekst rag)", ""]
    kinds = sorted({kind_of(q) for q in qs.values()})
    cols = ("pass", "key_points", "fidelity", "attribution")
    lines += ["| model | rodzaj | n | " + " | ".join(cols) + " |", "|---" * (len(cols) + 3) + "|"]
    for model in models:
        for kind in kinds:
            rows = [
                v for (q, m, c), v in scores.items()
                if m == model and c == "rag" and kind_of(qs[q]) == kind
            ]  # fmt: skip
            if rows:
                lines.append(
                    f"| {model} | {kind} | {len(rows)} | "
                    + " | ".join(cell([r[f] for r in rows]) for f in cols)
                    + " |"
                )

    def paired(model_a, ctx_a, model_b, ctx_b, field, other=None):
        b_scores = other if other is not None else scores
        ids = sorted(
            q
            for (q, m, c) in scores
            if m == model_a and c == ctx_a and (q, model_b, ctx_b) in b_scores
        )
        return diff(
            [scores[(q, model_a, ctx_a)][field] for q in ids],
            [b_scores[(q, model_b, ctx_b)][field] for q in ids],
        )

    cols = ("pass", "key_points", "fidelity", "attribution", "unsupported_claims")
    if reference in models:
        lines += ["", f"## Model − {reference} (te same pytania i noty)", ""]
        lines += ["| model | kontekst | " + " | ".join(cols) + " |", "|---" * (len(cols) + 2) + "|"]
        for model in models:
            if model == reference:
                continue
            for context in ("rag", "oracle"):
                lines.append(
                    f"| {model} | {context} | "
                    + " | ".join(paired(model, context, reference, context, f) for f in cols)
                    + " |"
                )

    if "oracle" in contexts:
        lines += ["", "## oracle − rag (luka retrievalu przy danym generatorze)", ""]
        lines += ["| model | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
        for model in models:
            lines.append(
                f"| {model} | "
                + " | ".join(paired(model, "oracle", model, "rag", f) for f in cols)
                + " |"
            )
    if "none" in contexts:
        lines += ["", "## Kontrola: oracle/rag − none", ""]
        for model in models:
            if any(m == model and c == "none" for (_, m, c) in scores):
                for ctx in ("rag", "oracle"):
                    lines.append(
                        f"- {model}, {ctx} − none: key_points {paired(model, ctx, model, 'none', 'key_points')}, "
                        f"pass {paired(model, ctx, model, 'none', 'pass')}"
                    )

    if compare:
        run_b, judged_b = load(compare)
        scores_b = merged(judged_b)
        lines += [
            "",
            f"## {run_dir.name} − {compare.name} (rag; grupowanie {run.get('group_fragments')} vs "
            f"{run_b.get('group_fragments')})",
            "",
        ]
        for model in models_of(run_b):
            lines.append(
                f"- {model}: "
                + "; ".join(f"{f} {paired(model, 'rag', model, 'rag', f, scores_b)}" for f in cols)
            )

    lines += ["", "## Pytania spoza zakresu i fałszywe odmowy (rag, kontrola automatyczna)", ""]
    lines += [
        "| model | odmowa: brak odpowiedzi w notach (no) | odmowa: częściowa (partly) | odmowa: jest odpowiedź (yes) |",
        "|---|---|---|---|",
    ]
    for model in models:
        rates = []
        for answerable in ("no", "partly", "yes"):
            gens = [
                g for g in run["generations"]
                if g["model"] == model and g["context"] == "rag" and qs[g["id"]].get("answerable") == answerable
            ]  # fmt: skip
            rates.append(
                f"{np.mean([g['checks']['abstained'] for g in gens]):.2f} (n={len(gens)})"
                if gens
                else "–"
            )
        lines.append(f"| {model} | " + " | ".join(rates) + " |")

    tags = list(judged)
    if len(tags) >= 2:
        a = {(r["id"], r["model"], r["context"]): r for r in judged[tags[0]]}
        b = {(r["id"], r["model"], r["context"]): r for r in judged[tags[1]]}
        shared = sorted(a.keys() & b.keys())
        lines += ["", f"## Zgodność sędziego {tags[0]} vs {tags[1]} ({len(shared)} odpowiedzi)", ""]
        lines.append(
            f"- pass: zgodność {np.mean([a[k]['pass'] == b[k]['pass'] for k in shared]):.2f}"
        )
        for f in FIELDS:
            ks = [k for k in shared if a[k].get(f) is not None and b[k].get(f) is not None]
            kappa = weighted_kappa([a[k][f] for k in ks], [b[k][f] for k in ks]) if ks else None
            lines.append(
                f"- {f}: ważona kappa {kappa if kappa is None else round(kappa, 2)} (n={len(ks)})"
            )

    lines += ["", "## Sprzęt i szybkość", ""]
    lines += [
        "| model | VRAM GiB | całość GiB | tok/s (mediana) | s/odp. (mediana) | słowa (śr.) | ucięte | złe cytowania |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for model in models:
        gens = [g for g in run["generations"] if g["model"] == model and g["context"] != "none"]
        hw = run.get("hardware", {}).get(model) or {}
        limit = run.get("model_options", {}).get(model, {}).get("num_predict")
        tps = [g["stats"]["tokens_per_s"] for g in gens if g["stats"].get("tokens_per_s")]
        cut = [g["stats"].get("output_tokens") == limit for g in gens]
        lines.append(
            f"| {model} | {hw.get('size_vram', 0) / 2**30:.1f} | {hw.get('size', 0) / 2**30:.1f} | "
            f"{statistics.median(tps) if tps else 0:.1f} | {statistics.median(g['stats']['seconds'] for g in gens):.1f} | "
            f"{np.mean([g['checks']['words'] for g in gens]):.0f} | {np.mean(cut):.2f} | "
            f"{np.mean([bool(g['checks']['invalid_citations']) for g in gens]):.2f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--compare", type=Path)
    ap.add_argument("--reference", default="qwen3.8:27b")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    text = report(args.run_dir, args.compare, args.reference)
    if args.out:
        args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
