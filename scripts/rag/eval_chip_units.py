"""Chip units against the B1 baseline, retrieval only, in memory (docs/new-chips-knowledge.md).

Usage: python scripts/rag/eval_chip_units.py --tier silver [--patient]
       python scripts/rag/eval_chip_units.py --tier silver --make-queries   # write request, stop

Both families are scored on the same questions and the same reference claims (silver, chips
fixtures in data/fixtures_chips). B1 is the regex pipeline run on the same sessions with chips
rendered as quotes. A claim is held by a chip unit when its highlight overlaps the claim's quote,
otherwise by the unit of that answer nearest to the claim text (chip_retrieval.cover_chip_claims).
An experiment label is `<index>[@35b][+dw][+merge]`:
  index   B1 | I1 | I3 | I1|I3 (I1|I3: both texts searched, the better one counts)
  @35b    units built with the labels of the second classifier (--alt-classifier)
  +dw     near-duplicate case units pushed down;  +merge  units sharing sentences become one block
Question mode uses the pooled labels (every system's top 8 judged by a Claude agent through the
inbox, prompts/Expert_unit_pooling.v1.md), original and pooled labels are both reported. Patient
mode (--patient): B1 and I3 over the patient's sentences, I2 through the cue keys; its labels are
weak (claims sharing a planted trait). Writes data/eval/chip_units/<timestamp>.json and latest.json.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from chip_retrieval import (
    ChipIndex,
    b1_baseline,
    cover_chip_claims,
    load_chip_fixture,
    postprocess,
    primed_embed,
)
from classify_sentence_targets import UNITS, model_tag
from eval_expert_units import HEADLINE, pooled_candidates, print_comparisons, print_table
from expert_metrics import BUDGETS, bootstrap, paired_bootstrap, score_query, tokens
from expert_retrieval import (
    ROOT,
    AwaitingResponse,
    Searcher,
    cover_claims,
    load_pool,
    load_questions,
    patient_queries,
    pool_requests,
)
from rag_common import bm25_config, query_embedder, write_json

OUT = ROOT / "data/eval/chip_units"
DEFAULT_EXPERIMENTS = [
    "B1",
    "I1", "I1+merge", "I3", "I3+merge", "I1|I3", "I1|I3+merge",
    "I1+dw", "I1+dw+merge",
    "I1@35b", "I1@35b+merge", "I3@35b",
]  # fmt: skip
COMPARISONS = [  # (a, b): what a adds over b
    ("I1", "B1"), ("I1+merge", "B1"), ("I3", "B1"), ("I3+merge", "B1"), ("I1|I3", "B1"),
    ("I1|I3+merge", "B1"), ("I1+merge", "I1"), ("I3", "I1"), ("I1|I3", "I1"), ("I1+dw", "I1"),
    ("I1@35b", "I1"), ("I1@35b+merge", "I1+merge"),
]  # fmt: skip
PATIENT_LABELS = ["B1", "I3", "I2", "I3@35b", "I2@35b"]
Q_KEYS = ["recall@1", "recall@8", "hit@8", *HEADLINE, *(f"recall@{b}t" for b in BUDGETS)]


def parse(label: str) -> tuple[str, str, set[str]]:
    """'I1|I3@35b+dw+merge' -> ('I1|I3', '35b', {'dw', 'merge'})."""
    rest, *mods = label.split("+")
    name, _, alt = rest.partition("@")
    return name, alt, set(mods)


def column(rows: list[dict], key: str) -> list[float]:
    return [r[key] for r in rows if r]


def summarise(scores: dict, shown: dict) -> dict:
    out = {}
    for label, rows in scores.items():
        out[label] = {"queries": len([r for r in rows if r]), "tokens_per_item": shown[label]}
        for key in Q_KEYS:
            out[label][key] = bootstrap(column(rows, key))
    return out


def compare(scores: dict) -> list[dict]:
    rows = []
    for a, b in COMPARISONS:
        if a in scores and b in scores:
            rows.append({"a": a, "b": b} | {
                key: paired_bootstrap(column(scores[a], key), column(scores[b], key))
                for key in ("recall@4", "ndcg@10")
            })  # fmt: skip
    return rows


def select(summary: dict) -> str | None:
    """Best chip experiment of the main classifier (mean of recall@4 and nDCG@10)."""
    cands = [lb for lb in summary if parse(lb)[0] != "B1" and not parse(lb)[1]]
    if not cands:
        return None
    return max(
        cands, key=lambda lb: np.mean([summary[lb]["recall@4"][0], summary[lb]["ndcg@10"][0]])
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier", default="silver", choices=["bronze", "silver"])
    ap.add_argument("--classifier", default="qwen3.5:9b")
    ap.add_argument("--alt-classifier", default="qwen3.6:35b-a3b")
    ap.add_argument("--units-dir", type=Path, default=UNITS, help="where build_chip_units wrote")
    ap.add_argument("--inbox", type=Path, default=ROOT / "data/inbox")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--experiments", nargs="+", default=DEFAULT_EXPERIMENTS)
    ap.add_argument("--patient", action="store_true")
    ap.add_argument("--make-queries", action="store_true")
    args = ap.parse_args(argv)

    vignettes, claims, docs, legacy = load_chip_fixture(args.tier)
    if args.make_queries:
        try:
            load_questions(args.tier, vignettes, claims, args.inbox)
            print("queries already answered")
        except AwaitingResponse as e:
            print(e)
        return 0

    indexes = {"": ChipIndex(args.tier, model_tag(args.classifier), args.units_dir)}
    try:
        indexes["35b"] = ChipIndex(args.tier, model_tag(args.alt_classifier), args.units_dir)
    except FileNotFoundError:
        print(f"no units for {args.alt_classifier}: @35b experiments skipped", file=sys.stderr)
    primed: dict = {}
    for ci in indexes.values():
        primed |= ci.primed
    embed, cfg = primed_embed(query_embedder(), primed), bm25_config()

    b1_units, _, b1_idx = b1_baseline(args.tier, legacy)
    covers = {"B1": cover_claims(b1_units, claims, vignettes, embed)}
    covers |= {alt: cover_chip_claims(ci, claims, vignettes, embed) for alt, ci in indexes.items()}
    union = {c: set().union(*(cv[c] for cv in covers.values())) for c in claims}
    print(
        f"{len(b1_units)} B1 units; chip units "
        + ", ".join(f"{len(ci.units)} ({ci.tag})" for ci in indexes.values())
        + f"; {len(claims)} claims; claims no chip unit holds: "
        f"{sum(not v for v in covers[''].values())}"
    )

    def family(label: str) -> str:
        name, alt, _ = parse(label)
        return "B1" if name == "B1" else alt

    searchers = {("B1", ""): Searcher(b1_idx["B1"], embed, cfg)}
    for alt, ci in indexes.items():
        for name in ("I1", "I3", "I1|I3"):
            searchers[(name, alt)] = Searcher(ci.items(name), embed, cfg)

    def rank(label: str, query: dict) -> list:
        name, alt, mods = parse(label)
        s = searchers.get((name, alt))
        if s is None:
            return []
        allowed = np.array(
            [it.unit_ids[0].split(":")[1] not in query.get("exclude", ()) for it in s.items]
        )
        ranked = [s.items[i] for i in s.rank(query["strings"], allowed)[:50]]
        return postprocess(indexes[alt], ranked, mods) if name != "B1" else ranked

    experiments = [lb for lb in args.experiments if (parse(lb)[0], parse(lb)[1]) in searchers]
    report: dict = {"tier": args.tier, "classifier": args.classifier, "alt": args.alt_classifier}

    def run(queries: list[dict], label_key: str, labels: list[str]):
        rankings = {lb: [rank(lb, q) for q in queries] for lb in labels}
        scores = {
            lb: [
                score_query(r, q[label_key], covers[family(lb)])
                for q, r in zip(queries, rk, strict=True)
            ]
            for lb, rk in rankings.items()
        }
        shown = {
            lb: float(np.mean([tokens(it.shown) for rk in rankings[lb] for it in rk[:4]] or [0]))
            for lb in labels
        }
        return rankings, scores, shown

    try:
        questions = load_questions(args.tier, vignettes, claims, args.inbox)
    except AwaitingResponse as e:
        questions = []
        print(f"question mode skipped: {e}", file=sys.stderr)
    if questions:
        rankings, _, _ = run(questions, "claim_ids", experiments)
        pooled_ok = False
        try:
            marks = load_pool(
                pool_requests(
                    args.tier, questions, pooled_candidates(rankings, questions, union), claims
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
            added = report["label_agreement"]["added_per_question"]
            print(f"\nlabels: pooled check confirmed {kept}/{total} original labels, added "
                  f"{added:.1f} per question")  # fmt: skip
        except AwaitingResponse as e:
            print(f"\npooled labels not available yet: {e}", file=sys.stderr)
        report["question"] = {}
        for label_key in ("claim_ids", "pooled_ids") if pooled_ok else ("claim_ids",):
            name = "original" if label_key == "claim_ids" else "pooled"
            _, scores, shown = run(questions, label_key, experiments)
            summary, comparisons = summarise(scores, shown), compare(scores)
            report["question"][name] = {"summary": summary, "comparisons": comparisons}
            print_table(f"question mode, {name} labels", summary)
            print_comparisons(comparisons)
            if name == "pooled" or not pooled_ok:
                report["selected"] = select(summary)
        print(f"\nselected for the generation test: {report.get('selected')}")
        report["questions"] = [
            {k: q[k] for k in ("question", "claim_ids", "pooled_ids")} for q in questions
        ]

    if args.patient:
        patients = patient_queries(vignettes, claims)
        cue_search = {alt: Searcher(ci.cue_items(), embed, cfg) for alt, ci in indexes.items()}
        labels = [lb for lb in PATIENT_LABELS if (parse(lb)[1] in indexes)]
        scores = {lb: [] for lb in labels}
        shown = {}
        for lb in labels:
            name, alt, _ = parse(lb)
            for q in patients:
                if name == "I2":
                    ranked = indexes[alt].patient_rank(cue_search[alt], q)
                else:
                    ranked = rank(lb, q)
                scores[lb].append(score_query(ranked, q["claim_ids"], covers[family(lb)]))
            shown[lb] = 0.0
        report["patient"] = summarise(scores, shown)
        print_table("patient-text mode (weak labels)", report["patient"])
        report["patient_comparisons"] = []
        for lb in labels:
            if lb != "B1":
                diffs = {k: paired_bootstrap(column(scores[lb], k), column(scores["B1"], k))
                         for k in ("recall@4", "ndcg@10")}  # fmt: skip
                report["patient_comparisons"].append({"a": lb, "b": "B1"} | diffs)
        print_comparisons(report["patient_comparisons"])

    report["units"] = {alt or "main": ci.built["stats"] for alt, ci in indexes.items()}
    path = args.out / f"{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    write_json(path, report)
    write_json(args.out / "latest.json", report)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
