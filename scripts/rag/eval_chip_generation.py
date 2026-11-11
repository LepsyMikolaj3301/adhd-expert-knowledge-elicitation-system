"""Answer the clinician questions from chip notes and from B1 notes with a local model.

Usage: python scripts/rag/eval_chip_generation.py --tier silver \
           --run-dir data/eval/expert_runs/<name> [--model qwen3.5:9b] [--limit N]
           [--contexts chips chips800 b1 oracle none shuffled]
       same questions, notes and contexts for another model (a separate run, so judges and reports
       never mix two models):
       python scripts/rag/eval_chip_generation.py --run-dir <new> --from-run <run> \
           --model qwen3.6:35b-a3b --contexts chips oracle
       python scripts/rag/eval_chip_generation.py --report <run> [--against <other run>]

Needs data/eval/chip_units/latest.json from eval_chip_units.py (the questions, their labels and the
selected experiment). Contexts per question, all with the same token budget unless named:
  chips      the selected chip experiment, always with the pack-time merge, 500 tokens
  chips800   the same ranking with 800 tokens
  b1         the regex units (B1) retrieved for the question, 500 tokens
  oracle     the chip units that hold the labelled claims (retrieval is perfect), 500 tokens
  none       no notes (the model says it answers from general knowledge)
  shuffled   the chips notes of another question, every 4th question only (judge control)
Contexts are built first (embedding), then generation runs with no embedding calls, so the GPU is
never shared. Writes <run-dir>/generations.json ("kind": "expert"), resuming if it exists; judge it
with scripts/rag/judge_generations.py.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
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
from eval_chip_units import parse
from eval_expert_generation import (
    EXPERT_SYSTEM_PROMPT,
    NO_NOTES_SYSTEM_PROMPT,
    SHUFFLE_EVERY,
    build_prompt,
    cited_notes,
    load_judgments,
    reference_line,
    report,
)
from expert_metrics import fill_budget, paired_bootstrap
from expert_retrieval import ROOT, Searcher, cover_claims
from rag_common import (
    GENERATION_OPTIONS,
    NOT_IN_SOURCES,
    OllamaChat,
    bm25_config,
    query_embedder,
    write_json,
)

RUNS = ROOT / "data/eval/expert_runs"
CONTEXTS = ("chips", "chips800", "b1", "oracle", "none", "shuffled")
FIELDS = ("pass", "key_points", "fidelity", "attribution")


def notes_of(items: list) -> list[dict]:
    return [{"id": it.unit_ids[0], "ids": it.unit_ids, "text": it.shown} for it in items]


# --- stage 1: contexts -------------------------------------------------------------------------


def build_contexts(args) -> dict:
    report_ = json.loads((args.units / "latest.json").read_text())
    label = args.experiment or report_["selected"]
    name, alt, mods = parse(label)
    if name == "B1" or alt:
        raise SystemExit(f"{label}: the chips context needs a main-classifier chip experiment")
    mods = mods | {"merge"}
    label_key = "claim_ids" if args.labels == "original" else "pooled_ids"
    questions = report_["questions"][: args.limit]
    vignettes, claims, _, legacy = load_chip_fixture(args.tier)
    ci = ChipIndex(args.tier, model_tag(args.classifier), args.units_dir)
    primed = dict(ci.primed)
    embed, cfg = primed_embed(query_embedder(), primed), bm25_config()
    b1_units, _, b1_idx = b1_baseline(args.tier, legacy)
    covers = cover_chip_claims(ci, claims, vignettes, embed)
    b1_covers = cover_claims(b1_units, claims, vignettes, embed)
    chips_search = Searcher(ci.items(name), embed, cfg)
    b1_search = Searcher(b1_idx["B1"], embed, cfg)
    by_unit = {it.unit_ids[0]: it for it in ci.items("I1")}

    def ranked(search: Searcher, q: str) -> list:
        everyone = np.ones(len(search.items), dtype=bool)
        return [search.items[i] for i in search.rank([q], everyone)[:50]]

    out: dict[str, dict[str, Any]] = {}
    for qi, q in enumerate(questions):
        qid = f"Q{qi + 1:02d}"
        chip_ranked = postprocess(ci, ranked(chips_search, q["question"]), mods)
        relevant = [c for c in q[label_key] if covers[c]]
        count: dict[str, int] = {}
        for c in relevant:
            for u in covers[c]:
                count[u] = count.get(u, 0) + 1
        oracle = ci.merge([by_unit[u] for u in sorted(count, key=lambda u: (-count[u], u))])
        out[qid] = {
            "question": q["question"],
            "type": "clinician_question",
            "reference_points": [reference_line(claims[c]) for c in q["claim_ids"]],
            "optional_points": [
                reference_line(claims[c]) for c in q[label_key] if c not in q["claim_ids"]
            ],
            "relevant_units": sorted(
                count | {u: 1 for c in relevant for u in b1_covers.get(c, ())}
            ),
            "contexts": {
                "chips": notes_of(fill_budget(chip_ranked, args.budget)),
                "chips800": notes_of(fill_budget(chip_ranked, 800)),
                "b1": notes_of(fill_budget(ranked(b1_search, q["question"]), args.budget)),
                "oracle": notes_of(fill_budget(oracle, args.budget)),
                "none": [],
            },
        }
    for qi, qid in enumerate(out):  # a note set that belongs to another question: judge control
        if qi % SHUFFLE_EVERY == 0:
            other = list(out)[(qi + 17) % len(out)]
            out[qid]["contexts"]["shuffled"] = out[other]["contexts"]["chips"]
    return {
        "kind": "expert",
        "representation": label,
        "classifier": args.classifier,
        "budget": args.budget,
        "labels": args.labels,
        "questions": out,
    }


# --- stage 2: generation -----------------------------------------------------------------------


def checks(item: dict, text: str, notes: list[dict]) -> dict:
    numbers = cited_notes(text)
    valid = [notes[n - 1] for n in numbers if 1 <= n <= len(notes)]
    ids = [i for note in valid for i in note["ids"]]
    return {
        "abstained": NOT_IN_SOURCES in text,
        "n_cited": len(valid),
        "invalid_citations": [n for n in numbers if not 1 <= n <= len(notes)],
        "cites_relevant": any(u in item["relevant_units"] for u in ids) if notes else None,
        "words": len(text.split()),
    }


def warm_up(model: str) -> None:
    """Load the model with a long timeout (a 35b model needs about 13 minutes from cold)."""
    base = OllamaChat(model).client.base_url
    httpx.post(
        f"{base}/api/generate",
        json={"model": model, "prompt": "hi", "stream": False, "keep_alive": "30m",
              "options": {"num_predict": 1}},
        timeout=2400,
    ).raise_for_status()  # fmt: skip


def generate(run: dict, args, out_path: Path) -> None:
    done = {(g["model"], g["id"], g["context"]) for g in run["generations"]}
    todo = [
        (qid, ctx)
        for qid, item in run["questions"].items()
        for ctx in args.contexts
        if item["contexts"].get(ctx) is not None and (args.model, qid, ctx) not in done
    ]
    if not todo:
        return
    warm_up(args.model)
    chat = OllamaChat(args.model, think=False, temperature=0, seed=1)
    for qid, ctx in todo:
        item = run["questions"][qid]
        notes = item["contexts"][ctx]
        system = EXPERT_SYSTEM_PROMPT if notes else NO_NOTES_SYSTEM_PROMPT
        try:
            text, stats = chat.chat(system, build_prompt(item["question"], notes))
        except Exception as e:  # one failed call must not stop the run
            print(f"FAILED  {qid} {ctx}: {type(e).__name__}: {e}")
            continue
        run["generations"].append(
            {"id": qid, "model": args.model, "context": ctx, "sample": 1, "answer": text,
             "checks": checks(item, text, notes), "stats": stats}
        )  # fmt: skip
        write_json(out_path, run)
        print(f"{qid} {ctx:9} {stats['seconds']:>6}s  {len(text.split()):>3} words")


# --- report ------------------------------------------------------------------------------------


def by_context(rows: list[dict]) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        out.setdefault(r["context"], {})[r["id"]] = r
    return out


def paired(a: dict, b: dict, field: str):
    shared = [
        q for q in a if q in b and a[q].get(field) is not None and b[q].get(field) is not None
    ]
    if not shared:
        return None
    return paired_bootstrap(
        [float(a[q][field]) for q in shared], [float(b[q][field]) for q in shared]
    )


def print_diff(title: str, a: dict, b: dict) -> None:
    cells = []
    for field in FIELDS:
        d = paired(a, b, field)
        if d:
            verdict = "+" if d[1] > 0 else "-" if d[2] < 0 else "~"
            cells.append(f"{field} {d[0]:+.2f} [{d[1]:+.2f},{d[2]:+.2f}] {verdict}")
    print(f"  {title:24}" + "   ".join(cells))


def report_chips(run_dir: Path, against: Path | None) -> None:
    report(run_dir)  # per-context table, controls and judge agreement (eval_expert_generation)
    run = json.loads((run_dir / "generations.json").read_text())
    judged = load_judgments(run_dir)
    for tag, rows in judged.items():
        ctx = by_context(rows)
        print(f"\npaired differences, judge pass {tag} (a - b; ~ = interval includes 0)")
        for a, b in (
            ("chips", "b1"),
            ("chips800", "b1"),
            ("chips800", "chips"),
            ("oracle", "chips"),
        ):
            if a in ctx and b in ctx:
                print_diff(f"{a} - {b}", ctx[a], ctx[b])
        if against:
            other = load_judgments(against).get(tag)
            if other:
                theirs = by_context(other)
                for c in ("chips", "oracle"):
                    if c in ctx and c in theirs:
                        print_diff(f"{c}: {against.name} - {run_dir.name}", theirs[c], ctx[c])
    print("\nautomatic checks (no judge):")
    for c in CONTEXTS:
        g = [x["checks"] for x in run["generations"] if x["context"] == c]
        if g:
            rel = [x["cites_relevant"] for x in g if x["cites_relevant"] is not None]
            print(f"  {c:9} n={len(g):>3}  abstained {np.mean([x['abstained'] for x in g]):.2f}"
                  f"  bad citations {np.mean([bool(x['invalid_citations']) for x in g]):.2f}"
                  f"  cites a relevant unit {np.mean(rel) if rel else float('nan'):.2f}"
                  f"  words {np.mean([x['words'] for x in g]):.0f}")  # fmt: skip


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier", default="silver", choices=["bronze", "silver"])
    ap.add_argument("--classifier", default="qwen3.5:9b", help="the units' classifier")
    ap.add_argument("--units", type=Path, default=ROOT / "data/eval/chip_units")
    ap.add_argument("--units-dir", type=Path, default=UNITS, help="where build_chip_units wrote")
    ap.add_argument("--run-dir", type=Path, default=RUNS / datetime.now().strftime("%Y%m%d-chips"))
    ap.add_argument("--from-run", type=Path, help="reuse this run's questions and notes")
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument(
        "--experiment", help="chip experiment label; default: `selected` in latest.json"
    )
    ap.add_argument("--labels", choices=["original", "pooled"], default="pooled")
    ap.add_argument("--budget", type=int, default=500)
    ap.add_argument("--contexts", nargs="+", choices=CONTEXTS, default=list(CONTEXTS))
    ap.add_argument("--limit", type=int, help="only the first N questions (smoke test)")
    ap.add_argument("--report", type=Path, metavar="RUN_DIR")
    ap.add_argument("--against", type=Path, help="with --report: another run to compare with")
    args = ap.parse_args(argv)
    if args.report:
        report_chips(args.report, args.against)
        return 0

    out_path = args.run_dir / "generations.json"
    if out_path.exists():
        run = json.loads(out_path.read_text())
    else:
        base = (
            json.loads((args.from_run / "generations.json").read_text())
            if args.from_run
            else build_contexts(args)
        )
        run = {
            **base,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "options": {**GENERATION_OPTIONS, "temperature": 0},
            "model": args.model,
            "generations": [],
        }
        write_json(out_path, run)
        print(f"{len(run['questions'])} questions, experiment {run['representation']}")
    generate(run, args, out_path)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
