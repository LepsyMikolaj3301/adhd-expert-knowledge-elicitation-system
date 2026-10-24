"""Summarise an evaluation run (retrieval.json, generations.json, judgments.json) as markdown.

Usage: python scripts/report_eval.py --run-dir data/eval/runs/<ts>

Prints, and writes to <run-dir>/summary.md, the retrieval metrics (overall and per source) and
one row per generator model: judge pass rate and mean scores, automatic checks (citation
validity, gold cited, token F1, abstention) and speed. Missing files are skipped.
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from rag_common import JUDGE_FIELDS


def load(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def mean(values: list) -> str:
    values = [float(v) for v in values if v is not None]
    return f"{statistics.fmean(values):.2f}" if values else "–"


def table(header: list[str], rows: list[list]) -> list[str]:
    return [
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
        *("| " + " | ".join(str(v) for v in row) + " |" for row in rows),
    ]


def retrieval_section(retrieval: dict) -> list[str]:
    cols = ["n", "hit@1", "hit@5", "hit@10", "recall@5", "recall@10", "mrr@10", "ndcg@10",
            "source_hit@5"]  # fmt: skip
    s = retrieval["summary"]
    rows = [["**overall**", *(s["overall"][c] for c in cols)]]
    rows += [[f"type: {t}", *(m[c] for c in cols)] for t, m in s["by_type"].items()]
    rows += [[src, *(m[c] for c in cols)] for src, m in s["by_source"].items()]
    return [f"## Retrieval (top-{retrieval['k']}, bge-m3)", "", *table(["", *cols], rows), ""]


def generation_section(generations: dict, judgments: dict | None) -> list[str]:
    judged = {(j["model"], j["id"]): j for j in (judgments or {}).get("judgments", [])}
    by_model = defaultdict(list)
    for g in generations["generations"]:
        by_model[g["model"]].append(g)
    types = {qid: q["type"] for qid, q in generations["questions"].items()}

    header = ["model", "n", "judge pass", *JUDGE_FIELDS, "citations valid", "gold cited",
              "token F1", "abstain (unans.)", "false abstain", "tok/s", "s/answer"]  # fmt: skip
    rows = []
    for model, gens in by_model.items():
        js = [judged[(model, g["id"])] for g in gens if (model, g["id"]) in judged]
        answerable = [g for g in gens if types[g["id"]] != "unanswerable"]
        unanswerable = [g for g in gens if types[g["id"]] == "unanswerable"]
        rows.append(
            [
                model,
                len(gens),
                f"{sum(j['pass'] for j in js)}/{len(js)}" if js else "–",
                *(mean([j[f] for j in js]) for f in JUDGE_FIELDS),
                mean([g["checks"]["citations_valid"] for g in gens]),
                mean([g["checks"]["cites_gold"] for g in answerable]),
                mean([g["checks"]["token_f1"] for g in answerable]),
                f"{sum(g['checks']['abstained'] for g in unanswerable)}/{len(unanswerable)}",
                f"{sum(g['checks']['abstained'] for g in answerable)}/{len(answerable)}",
                mean([g["stats"]["tokens_per_s"] for g in gens]),
                mean([g["stats"]["seconds"] for g in gens]),
            ]
        )
    judge = f"judge: {judgments['judge']}" if judgments else "no judgments yet"
    lines = [f"## Generation (k={generations['k']}, think={generations['think']}; {judge})", ""]
    lines += table(header, rows)

    failed = [(model, j["id"], j["rationale"]) for (model, _), j in judged.items() if not j["pass"]]
    if failed:
        lines += ["", "### Failed answers (judge rationale)", ""]
        lines += [f"- `{model}` {qid}: {why}" for model, qid, why in sorted(failed)]
    return [*lines, ""]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()

    lines = [f"# Evaluation run {args.run_dir.name}", ""]
    if retrieval := load(args.run_dir / "retrieval.json"):
        lines += retrieval_section(retrieval)
    if generations := load(args.run_dir / "generations.json"):
        lines += generation_section(generations, load(args.run_dir / "judgments.json"))
    text = "\n".join(lines)
    (args.run_dir / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
