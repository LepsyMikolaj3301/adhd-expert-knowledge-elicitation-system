"""Summarise an evaluation run (retrieval.json, generations.json, judgments.json) as markdown.

Usage: python scripts/report_eval.py --run-dir data/eval/runs/<ts>

Prints, and writes to <run-dir>/summary.md:
- retrieval metrics (overall, per question type and per source);
- one row per (model, context): judge pass rate averaged over samples, pass@any / pass@all
  (some / every sample passes), unstable questions (mixed pass and fail), mean judge scores and
  consistency, automatic checks and speed. The `oracle` row covers the answerable questions with
  the gold chunks forced into the context; where retrieval had found them anyway the context is
  identical, so the `retrieved` answers stand in;
- a per-question diagnosis: retrieval problem (fails as retrieved, passes with the gold chunks),
  model problem (fails even with the gold chunks; consistently or unstably), or ok;
- the judge's notes on samples whose behaviour changed, and on failed answers.
Missing files are skipped.
"""

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from rag_common import JUDGE_FIELDS

PASS = 0.8  # pass rate over samples that counts as "passes"
FAIL = 0.2  # ...and as "fails"


def load(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def mean(values: list, digits: int = 2) -> str:
    values = [float(v) for v in values if v is not None]
    return f"{statistics.fmean(values):.{digits}f}" if values else "–"


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
    mode = retrieval.get("retrieval", "dense")  # runs before hybrid retrieval were dense only
    return [f"## Retrieval (top-{retrieval['k']}, {mode})", "", *table(["", *cols], rows), ""]


class Run:
    """Generations and judgments indexed by (model, question, context)."""

    def __init__(self, generations: dict, judgments: dict | None) -> None:
        self.questions = generations["questions"]
        self.samples = generations.get("samples", 1)
        self.models = list(dict.fromkeys(g["model"] for g in generations["generations"]))
        self.gens = defaultdict(list)
        for g in generations["generations"]:
            self.gens[(g["model"], g["id"], g.get("context", "retrieved"))].append(g)
        judgments = judgments or {}
        self.judge = ", ".join(judgments.get("judge", [])) or "no judgments yet"
        self.judged = defaultdict(list)
        for j in judgments.get("judgments", []):
            self.judged[(j["model"], j["id"], j.get("context", "retrieved"))].append(j)
        self.consistency = {
            (c["model"], c["id"], c["context"]): c for c in judgments.get("consistency", [])
        }

    def key(self, model: str, qid: str, context: str) -> tuple[str, str, str]:
        """`oracle` falls back to `retrieved` when the two contexts are identical (gold chunks
        retrieved anyway), since eval_generation.py does not ask the question twice then."""
        contexts = self.questions[qid].get("contexts", {})
        same = [c["id"] for c in contexts.get("oracle", [])] == [
            c["id"] for c in contexts.get("retrieved", [])
        ]
        if context == "oracle" and same:
            return (model, qid, "retrieved")
        return (model, qid, context)

    def question_ids(self, context: str) -> list[str]:
        return [
            qid
            for qid, q in self.questions.items()
            if context == "retrieved" or q["type"] != "unanswerable"
        ]

    def pass_rate(self, model: str, qid: str, context: str) -> float | None:
        js = self.judged[self.key(model, qid, context)]
        return statistics.fmean(j["pass"] for j in js) if js else None

    def gold_retrieved(self, qid: str) -> bool:
        return any(
            g["checks"]["context_has_gold"]
            for model in self.models
            for g in self.gens[(model, qid, "retrieved")]
        )


def model_rows(run: Run) -> list[list]:
    rows = []
    for model in run.models:
        for context in ("retrieved", "oracle"):
            keys = [run.key(model, qid, context) for qid in run.question_ids(context)]
            keys = [k for k in keys if run.gens[k]]  # a model may have answered only a subset
            gens = [g for k in keys for g in run.gens[k]]
            if not gens or (context == "oracle" and not any(k[2] == "oracle" for k in keys)):
                continue
            js = [j for k in keys for j in run.judged[k]]
            rates = [r for k in keys if (r := run.pass_rate(*k)) is not None]
            cons = [run.consistency[k] for k in keys if k in run.consistency]
            answerable = [g for g in gens if run.questions[g["id"]]["type"] != "unanswerable"]
            rows.append(
                [
                    model,
                    context,
                    len(keys),
                    len(gens),
                    f"{mean([j['pass'] for j in js])}" if js else "–",
                    f"{sum(r > 0 for r in rates)}/{len(rates)}" if rates else "–",
                    f"{sum(r == 1 for r in rates)}/{len(rates)}" if rates else "–",
                    sum(0 < r < 1 for r in rates) if rates else "–",
                    *(mean([j[f] for j in js]) for f in JUDGE_FIELDS),
                    mean([c["consistency"] for c in cons]),
                    sum(bool(c["behaviour_changed"]) for c in cons) if cons else "–",
                    mean([g["checks"]["citations_valid"] for g in gens]),
                    mean([g["checks"]["abstained"] for g in answerable]),
                    mean([g["stats"]["seconds"] for g in gens]),
                ]
            )
    return rows


def diagnose(run: Run, model: str, qid: str) -> str:
    retrieved = run.pass_rate(model, qid, "retrieved")
    if retrieved is None:
        return "–"
    if run.questions[qid]["type"] == "unanswerable":
        return "ok" if retrieved >= PASS else "model: answers unanswerable"
    oracle = run.pass_rate(model, qid, "oracle")
    if retrieved >= PASS:
        return "ok"
    if oracle is None:
        return "fails" + ("" if run.gold_retrieved(qid) else " (gold not retrieved)")
    if not run.gold_retrieved(qid) and oracle is not None and oracle >= PASS:
        return "retrieval"
    if oracle is not None and oracle <= FAIL:
        return "model: wrong" + ("" if run.gold_retrieved(qid) else " (+retrieval)")
    return "model: unstable" + ("" if run.gold_retrieved(qid) else " (+retrieval)")


def generation_section(run: Run) -> list[str]:
    header = ["model", "context", "questions", "answers", "pass rate", "pass@any", "pass@all",
              "unstable", *JUDGE_FIELDS, "consistency", "behaviour changed", "citations valid",
              "false abstain", "s/answer"]  # fmt: skip
    lines = [f"## Generation (samples={run.samples}; judge: {run.judge})", ""]
    lines += table(header, model_rows(run))

    diagnoses = {m: {qid: diagnose(run, m, qid) for qid in run.questions} for m in run.models}
    lines += ["", "### Diagnosis per question", ""]
    lines += [
        f"Pass rate over samples, as retrieved → with gold chunks forced in (oracle). "
        f"ok: retrieved ≥ {PASS}; retrieval: gold not retrieved and oracle ≥ {PASS}; "
        f"model wrong: oracle ≤ {FAIL}; model unstable: in between.",
        "",
    ]
    rows = []
    for qid, q in run.questions.items():
        cells = []
        for m in run.models:
            r, o = run.pass_rate(m, qid, "retrieved"), run.pass_rate(m, qid, "oracle")
            c = run.consistency.get((m, qid, "retrieved"), {}).get("consistency")
            cells.append(
                f"{mean([r], 1)} → {mean([o], 1) if q['type'] != 'unanswerable' else '·'}"
                f" (cons {c or '–'}) {diagnoses[m][qid]}"
            )
        if any(diagnoses[m][qid] not in ("ok", "–") for m in run.models):
            gold = "yes" if run.gold_retrieved(qid) else "**no**"
            rows.append([qid, q["type"], gold, *cells])
    lines += table(["question", "type", "gold in top-k", *run.models], rows)
    lines += ["", "Counts: " + "; ".join(
        f"`{m}`: " + ", ".join(
            f"{d} {n}" for d, n in Counter(diagnoses[m].values()).most_common() if d != "–"
        )
        for m in run.models
    )]  # fmt: skip

    changed = [
        (c["model"], c["id"], c["context"], c["consistency"], c["consistency_note"])
        for c in run.consistency.values()
        if c["behaviour_changed"]
    ]
    if changed:
        lines += ["", "### Behaviour changed between samples (judge notes)", ""]
        lines += [
            f"- `{m}` {qid} ({ctx}, consistency {cons}): {note}"
            for m, qid, ctx, cons, note in sorted(changed)
        ]

    failed = []
    for (m, qid, ctx), js in sorted(run.judged.items()):
        bad = [j for j in js if not j["pass"]]
        if bad:
            failed.append(
                f"- `{m}` {qid} ({ctx}, {len(bad)}/{len(js)} failed): {bad[0]['rationale']}"
            )
    if failed:
        lines += ["", "### Failed answers (first failing sample's judge rationale)", "", *failed]
    return [*lines, ""]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()

    lines = [f"# Evaluation run {args.run_dir.name}", ""]
    if retrieval := load(args.run_dir / "retrieval.json"):
        lines += retrieval_section(retrieval)
    if generations := load(args.run_dir / "generations.json"):
        lines += generation_section(Run(generations, load(args.run_dir / "judgments.json")))
    text = "\n".join(lines)
    (args.run_dir / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
