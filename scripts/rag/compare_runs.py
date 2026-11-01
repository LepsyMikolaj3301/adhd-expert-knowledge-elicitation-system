"""Compare evaluation runs (historic vs old vs new retrieval) as one markdown file.

Usage: python scripts/rag/compare_runs.py --out data/eval/runs/bronze-v3-hybrid/comparison.md
           --historic data/eval/runs/bronze-v2-samples
           --dense data/eval/runs/bronze-v3-dense --hybrid data/eval/runs/bronze-v3-hybrid
           [--bm25 data/eval/runs/bronze-v3-bm25] [--intro FILE] [--findings FILE]

--historic is a run from before hybrid retrieval (possibly on an older corpus or dataset), shown as
recorded. --dense and --hybrid are runs of the same dataset and corpus with the old and the new
retrieval, so they are the like-for-like comparison. Each run dir needs retrieval.json; the
generation tables also need generations.json and judgments.json. Writes the markdown to --out;
--intro (methods, scope, caveats) and --findings (interpretation) are hand-written markdown
files placed before and after the tables.
"""

import argparse
from collections import Counter
from pathlib import Path

from report_eval import FAIL, PASS, Run, diagnose, load, mean, model_rows, table

METRICS = ["n", "hit@1", "hit@3", "hit@5", "hit@10", "recall@5", "recall@10", "mrr@10",
           "ndcg@10", "source_hit@5"]  # fmt: skip
GEN_HEADER = ["model", "context", "run", "questions", "answers", "pass rate", "pass@any",
              "pass@all", "unstable", "correct.", "faithf.", "citation", "complete.",
              "consistency", "behaviour changed", "citations valid", "false abstain"]  # fmt: skip
LOCAL_MODELS = ("qwen3.5:9b", "gemma4:e4b")


def corpus_line(run: dict) -> str:
    c = run["corpus"]
    return f"{c['chunks']} chunks, index `{', '.join(c['index_configs'])}`"


def retrieval_tables(runs: dict[str, dict]) -> list[str]:
    lines = ["### Overall", ""]
    rows = [[name, corpus_line(r), *(r["summary"]["overall"][m] for m in METRICS)]
            for name, r in runs.items()]  # fmt: skip
    lines += table(["run", "corpus", *METRICS], rows)

    names = list(runs)
    lines += ["", "### By source (hit@5 / mrr@10 / recall@10)", ""]
    sources = sorted({s for r in runs.values() for s in r["summary"]["by_source"]})
    rows = []
    for s in sources:
        cells = []
        for r in runs.values():
            m = r["summary"]["by_source"].get(s)
            cells.append(
                f"{m['hit@5']} / {m['mrr@10']} / {m['recall@10']} (n={m['n']})" if m else "–"
            )
        rows.append([s, *cells])
    lines += table(["source", *names], rows)

    lines += ["", "### By question type (hit@5 / mrr@10 / recall@10)", ""]
    types = sorted({t for r in runs.values() for t in r["summary"]["by_type"]})
    rows = []
    for t in types:
        cells = []
        for r in runs.values():
            m = r["summary"]["by_type"].get(t)
            cells.append(
                f"{m['hit@5']} / {m['mrr@10']} / {m['recall@10']} (n={m['n']})" if m else "–"
            )
        rows.append([t, *cells])
    return lines + table(["type", *names], rows)


def rank_changes(old: dict, new: dict) -> list[str]:
    """Questions whose first relevant rank differs between two retrieval runs of one dataset."""
    old_q = {q["id"]: q for q in old["questions"]}
    rows = []
    for q in new["questions"]:
        a, b = old_q[q["id"]]["metrics"]["first_relevant_rank"], q["metrics"]["first_relevant_rank"]
        if a != b:
            rank = lambda r: r if r else "miss"  # noqa: E731
            better = (b or 99) < (a or 99)
            rows.append([q["id"], q["type"], rank(a), rank(b), "better" if better else "worse"])
    if not rows:
        return ["No question changed its first relevant rank."]
    gained = sum(r[4] == "better" for r in rows)
    return [f"{gained} better, {len(rows) - gained} worse, "
            f"{len(old_q) - len(rows)} unchanged.", "",
            *table(["question", "type", "dense first relevant rank", "hybrid first relevant rank",
                    ""], rows)]  # fmt: skip


def context_overlap(dense: Run, hybrid: Run) -> str:
    """How often the top-5 context handed to the models differs between the two methods."""
    same_set = same_order = gold_dense = gold_hybrid = 0
    n = len(hybrid.questions)
    for qid, q in hybrid.questions.items():
        d = [c["id"] for c in dense.questions[qid]["contexts"]["retrieved"]]
        h = [c["id"] for c in q["contexts"]["retrieved"]]
        same_set += set(d) == set(h)
        same_order += d == h
    for run, name in ((dense, "dense"), (hybrid, "hybrid")):
        retrievable = [qid for qid, q in run.questions.items() if q["evidence"]]
        got = sum(run.gold_retrieved(qid) for qid in retrievable)
        if name == "dense":
            gold_dense = f"{got}/{len(retrievable)}"
        else:
            gold_hybrid = f"{got}/{len(retrievable)}"
    return (
        f"The top-5 context is identical (same chunks, same order) for {same_order}/{n} "
        f"questions and has the same chunks in a different order for "
        f"{same_set - same_order}; it differs in content for {n - same_set}. Gold evidence "
        f"in the context of an answerable question: dense {gold_dense}, hybrid {gold_hybrid}."
    )


def generation_tables(runs: dict[str, Run]) -> list[str]:
    rows = []
    for model in LOCAL_MODELS:
        for context in ("retrieved", "oracle"):
            for name, run in runs.items():
                if model not in run.models:
                    continue
                for r in model_rows(run):
                    if r[0] == model and r[1] == context:
                        # model, context, questions, answers, pass rate, pass@any, pass@all,
                        # unstable, 4 judge scores, consistency, behaviour changed, citations
                        # valid, false abstain, s/answer
                        rows.append([model, context, name, *r[2:16]])
    return table(GEN_HEADER, rows)


def diagnosis_counts(runs: dict[str, Run]) -> list[str]:
    rows = []
    for model in LOCAL_MODELS:
        for name, run in runs.items():
            if model in run.models:
                counts = Counter(diagnose(run, model, qid) for qid in run.questions)
                rows.append(
                    [
                        model,
                        name,
                        *(
                            counts.get(k, 0)
                            for k in ("ok", "retrieval", "model: wrong", "model: unstable")
                        ),
                    ]
                )
    return table(["model", "run", "ok", "retrieval", "model: wrong", "model: unstable"], rows) + [
        "", "Other labels (e.g. `fails`, `… (+retrieval)`) are not broken out, so a row can sum "
        "to fewer than the number of questions in the run."]  # fmt: skip


def flips(dense: Run, hybrid: Run) -> list[str]:
    """Questions where the pass rate over samples moved by 0.4 or more between the methods."""
    rows = []
    for model in LOCAL_MODELS:
        for qid, q in hybrid.questions.items():
            if qid not in dense.questions:
                continue
            a, b = (
                dense.pass_rate(model, qid, "retrieved"),
                hybrid.pass_rate(model, qid, "retrieved"),
            )
            if a is not None and b is not None and abs(a - b) >= 0.4:
                same = [c["id"] for c in dense.questions[qid]["contexts"]["retrieved"]] == [
                    c["id"] for c in q["contexts"]["retrieved"]
                ]
                rows.append([model, qid, q["type"], mean([a], 1), mean([b], 1),
                             "same context" if same else "different context"])  # fmt: skip
    if not rows:
        return ["No question moved by 0.4 or more."]
    return table(["model", "question", "type", "dense pass rate", "hybrid pass rate", ""],
                 sorted(rows, key=lambda r: (r[0], r[1])))  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--historic", type=Path, required=True)
    parser.add_argument("--dense", type=Path, required=True)
    parser.add_argument("--hybrid", type=Path, required=True)
    parser.add_argument("--bm25", type=Path)
    parser.add_argument("--intro", type=Path)
    parser.add_argument("--findings", type=Path)
    args = parser.parse_args()

    retrieval = {
        "historic (dense)": load(args.historic / "retrieval.json"),
        "dense (old method)": load(args.dense / "retrieval.json"),
        **({"bm25 only": load(args.bm25 / "retrieval.json")} if args.bm25 else {}),
        "hybrid (new method)": load(args.hybrid / "retrieval.json"),
    }

    def gen(path: Path) -> Run:
        return Run(load(path / "generations.json"), load(path / "judgments.json"))

    runs = {"historic": gen(args.historic), "dense": gen(args.dense), "hybrid": gen(args.hybrid)}
    hist_dir = args.historic.name
    lines = [
        "# Hybrid retrieval (BM25 + dense, RRF) vs dense-only: evaluation comparison", "",
        *(args.intro.read_text().splitlines() if args.intro else []), "",
        "## Retrieval", "",
        f"`historic (dense)` is `{hist_dir}` as recorded (older corpus and dataset, see Scope). "
        "`dense (old method)`, `bm25 only` and `hybrid (new method)` ran on the same corpus and "
        "dataset, so those rows are comparable with each other.", "",
        *retrieval_tables(retrieval), "",
        "### Questions whose first relevant rank changed (dense → hybrid)", "",
        *rank_changes(retrieval["dense (old method)"], retrieval["hybrid (new method)"]), "",
        "## Generation", "",
        "Same protocol in all three runs: top-5 context, 5 samples per question (T=0.7, seed = "
        "sample number), `retrieved` and `oracle` (gold chunks forced in) contexts, blind judge. "
        "`pass rate` is the mean judge `pass` over samples; `pass@any` / `pass@all` count "
        "questions where some / every sample passes; `unstable` is mixed pass and fail.", "",
        context_overlap(runs["dense"], runs["hybrid"]), "",
        *generation_tables(runs), "",
        "### Diagnosis counts (retrieved → oracle, as in summary.md)", "",
        f"ok: pass rate ≥ {PASS}; retrieval: gold not retrieved and oracle ≥ {PASS}; "
        f"model wrong: oracle ≤ {FAIL}.", "",
        *diagnosis_counts(runs), "",
        "### Questions whose pass rate moved by ≥ 0.4 (dense → hybrid, retrieved context)", "",
        *flips(runs["dense"], runs["hybrid"]), "",
        *(args.findings.read_text().splitlines() if args.findings else []), "",
    ]  # fmt: skip
    args.out.write_text("\n".join(lines))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
