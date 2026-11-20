"""Answer the clinician questions from expert notes with a local 9B model.

See notes/expert-knowledge.md.

Usage: python scripts/rag/eval_expert_generation.py --tier silver [--model qwen3.5:9b] [--limit N]
       python scripts/rag/eval_expert_generation.py --report data/eval/expert_runs/<ts>

Needs data/eval/expert_units/latest.json from eval_expert_units.py (the 40 questions, their labels
and the representation it selected). Each question is answered under these contexts, all with the
same token budget of expert notes:
  units     the selected representation, retrieved for the question, shown verbatim ([E1]..)
  rules     the LLM reading rules (option C) retrieved for the question
  oracle    the units that hold the question's labelled claims (the ceiling: retrieval is perfect)
  none      no notes; the model answers from general knowledge and says so (a baseline)
  shuffled  units retrieved for another question, on every 4th question only (judge control)
Contexts are built first (embedding), then generation runs with no embedding calls, so the two never
share the GPU. Writes <run-dir>/generations.json, resuming if it exists; judge it with
scripts/rag/judge_generations.py (the run is marked "kind": "expert"). --report prints per-context
results from the judgments in a run dir, with bootstrap intervals and judge agreement.
"""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from eval_expert_units import parse
from expert_metrics import bootstrap, fill_budget, paired_bootstrap, weighted_kappa
from expert_retrieval import (
    ROOT,
    Searcher,
    build_indexes,
    cover_claims,
    load_fixture,
    load_keys,
    make_embed,
)
from make_unit_keys import load_units
from rag_common import (
    EXPERT_FIELDS,
    GENERATION_OPTIONS,
    NOT_IN_SOURCES,
    OllamaChat,
    bm25_config,
    query_embedder,
    write_json,
)

from expert_knowledge_core.prompts import (  # noqa: F401  (chat_expert imports it from here)
    EXPERT_SYSTEM_PROMPT,
    build_expert_prompt,
)

RUNS = ROOT / "data/eval/expert_runs"
CONTEXTS = ("units", "rules", "oracle", "none", "shuffled")
SHUFFLE_EVERY = 4

NO_NOTES_SYSTEM_PROMPT = """You help a clinician with a question about reading patients' own writing
for ADHD-related traits. No notes from colleagues are available for this question. Answer in 3 to 6
sentences from general knowledge, and begin by saying that this is general knowledge and not
colleagues' notes."""


def reference_line(c: dict) -> str:
    note = "; ".join(x for x in (c.get("direction"), c.get("condition")) if x)
    return f"{c['claim_text']}" + (f" ({note})" if note else "")


def build_prompt(question: str, notes: list[dict]) -> str:
    return build_expert_prompt(question, [c["text"] for c in notes])


def cited_notes(text: str) -> list[int]:
    """[E2], [E1][E3], [E1, E3] -> sorted unique note numbers."""
    return sorted(
        {
            int(n)
            for group in re.findall(r"\[([^\]]*)\]", text)
            for n in re.findall(r"E(\d+)", group)
        }
    )


# --- stage 1: contexts ---------------------------------------------------------------------------


def build_contexts(args) -> dict:
    report = json.loads((ROOT / "data/eval/expert_units/latest.json").read_text())
    label = args.representation or report["selected"]
    name, mode, diversity = parse(label)
    label_key = "claim_ids" if args.labels == "original" else "pooled_ids"
    questions = report["questions"][: args.limit]
    vignettes, claims, answers = load_fixture(args.tier, args.source)
    units = load_units(args.tier, source=args.source)
    lean = load_units(args.tier, source=args.source, context_words=30, max_context=1)
    embed = make_embed(query_embedder())
    cfg = bm25_config()
    covers = cover_claims(units, claims, vignettes, embed)
    indexes = build_indexes(units, lean, answers, load_keys(args.tier, args.source))
    main, rules = Searcher(indexes[name], embed, cfg), Searcher(indexes["C"], embed, cfg)
    by_unit = {it.unit_ids[0]: it for it in indexes[name]}
    everyone = np.ones(len(indexes[name]), dtype=bool)

    def retrieved(q: str) -> list[dict]:
        items = [main.items[i] for i in main.rank([q], everyone, mode, diversity)[:50]]
        return [{"id": it.unit_ids[0], "text": it.shown} for it in fill_budget(items, args.budget)]

    out: dict[str, dict[str, Any]] = {}
    for qi, q in enumerate(questions):
        qid = f"Q{qi + 1:02d}"
        relevant = [c for c in q[label_key] if covers[c]]
        count: dict[str, int] = {}
        for c in relevant:
            for u in covers[c]:
                count[u] = count.get(u, 0) + 1
        oracle = [by_unit[u] for u in sorted(count, key=lambda u: (-count[u], u))]
        rule_items = [
            rules.items[i]
            for i in rules.rank([q["question"]], np.ones(len(rules.items), dtype=bool))[:50]
        ]
        out[qid] = {
            "question": q["question"],
            "type": "clinician_question",
            "reference_points": [reference_line(claims[c]) for c in q["claim_ids"]],
            "optional_points": [
                reference_line(claims[c]) for c in q[label_key] if c not in q["claim_ids"]
            ],
            "relevant_units": sorted(count),
            "contexts": {
                "units": retrieved(q["question"]),
                "rules": [
                    {"id": it.unit_ids[0], "text": it.shown}
                    for it in fill_budget(rule_items, args.budget)
                ],
                "oracle": [
                    {"id": it.unit_ids[0], "text": it.shown}
                    for it in fill_budget(oracle, args.budget)
                ],
                "none": [],
            },
        }
    for qi, qid in enumerate(
        out
    ):  # a note set that belongs to another question: the judge's control
        if qi % SHUFFLE_EVERY == 0:
            other = list(out)[(qi + 17) % len(out)]
            out[qid]["contexts"]["shuffled"] = out[other]["contexts"]["units"]
    return {
        "kind": "expert",
        "representation": label,
        "budget": args.budget,
        "labels": args.labels,
        "questions": out,
    }


# --- stage 2: generation -------------------------------------------------------------------------


def checks(item: dict, text: str, notes: list[dict]) -> dict:
    numbers = cited_notes(text)
    cited = [notes[n - 1]["id"] for n in numbers if 1 <= n <= len(notes)]
    return {
        "abstained": NOT_IN_SOURCES in text,
        "n_cited": len(cited),
        "invalid_citations": [n for n in numbers if not 1 <= n <= len(notes)],
        "cites_relevant": any(u in item["relevant_units"] for u in cited) if notes else None,
        "words": len(text.split()),
    }


def generate(run: dict, args, out_path: Path) -> None:
    done = {(g["model"], g["id"], g["context"]) for g in run["generations"]}
    chat_for = {}
    for qid, item in run["questions"].items():
        for context in args.contexts:
            notes = item["contexts"].get(context)
            if notes is None or (args.model, qid, context) in done:
                continue
            chat = chat_for.setdefault(
                context,
                OllamaChat(args.model, think=False, temperature=0, seed=1),
            )
            system = EXPERT_SYSTEM_PROMPT if notes else NO_NOTES_SYSTEM_PROMPT
            try:
                text, stats = chat.chat(system, build_prompt(item["question"], notes))
            except Exception as e:  # keep going: one failed call must not stop the run
                print(f"FAILED  {qid} {context}: {type(e).__name__}: {e}")
                continue
            run["generations"].append(
                {
                    "id": qid,
                    "model": args.model,
                    "context": context,
                    "sample": 1,
                    "answer": text,
                    "checks": checks(item, text, notes),
                    "stats": stats,
                }
            )
            write_json(out_path, run)
            print(f"{qid} {context:9} {stats['seconds']:>6}s  {len(text.split()):>3} words")


# --- report --------------------------------------------------------------------------------------


def load_judgments(run_dir: Path) -> dict[str, list[dict]]:
    """{judge file tag: judgments} for judgments.json and judgments_<tag>.json."""
    return {
        p.stem.removeprefix("judgments").lstrip("_") or "main": json.loads(p.read_text())[
            "judgments"
        ]
        for p in sorted(run_dir.glob("judgments*.json"))
    }


def report(run_dir: Path) -> None:
    run = json.loads((run_dir / "generations.json").read_text())
    judged = load_judgments(run_dir)
    if not judged:
        raise SystemExit(f"no judgments in {run_dir}: run judge_generations.py first")
    qids = list(run["questions"])
    for tag, rows in judged.items():
        print(f"\njudge pass {tag}: {len(rows)} judgments")
        by_context: dict[str, dict[tuple, dict]] = {}
        for r in rows:
            by_context.setdefault(r["context"], {})[r["id"]] = r
        cols = [*EXPERT_FIELDS, "pass", "unsupported_claims"]
        print(f"{'context':10}{'n':>4}" + "".join(f"{c[:14]:>16}" for c in cols))
        for context, by_q in by_context.items():
            cells = ""
            for c in cols:
                vals = [float(r[c]) for r in by_q.values() if r.get(c) is not None]
                if vals:
                    m, lo, hi = bootstrap(vals)
                    cells += f"{m:>6.2f} [{lo:.1f},{hi:.1f}]"
                else:
                    cells += f"{'-':>16}"
            print(f"{context:10}{len(by_q):>4}{cells}")
        if {"units", "rules"} <= by_context.keys():
            both = [q for q in qids if q in by_context["units"] and q in by_context["rules"]]
            for c in ("pass", "fidelity", "key_points", "attribution"):
                a = [
                    float(by_context["units"][q][c])
                    for q in both
                    if by_context["units"][q].get(c) is not None
                ]
                b = [
                    float(by_context["rules"][q][c])
                    for q in both
                    if by_context["rules"][q].get(c) is not None
                ]
                if len(a) == len(b) and a:
                    m, lo, hi = paired_bootstrap(a, b)
                    print(f"  units - rules, {c:12} {m:+.2f} [{lo:+.2f},{hi:+.2f}]")
        for control in ("none", "shuffled"):
            if control in by_context and "oracle" in by_context:
                shared = [q for q in by_context[control] if q in by_context["oracle"]]
                for c in ("key_points", "fidelity"):
                    a = [by_context["oracle"][q].get(c) for q in shared]
                    b = [by_context[control][q].get(c) for q in shared]
                    pairs = [
                        (x, y) for x, y in zip(a, b, strict=True) if x is not None and y is not None
                    ]
                    if pairs:
                        gap = np.mean([x - y for x, y in pairs])
                        print(
                            f"  control: oracle - {control:8} {c:11} {gap:+.2f} (want clearly > 0)"
                        )
    tags = list(judged)
    if len(tags) >= 2:
        a = {(r["id"], r["context"]): r for r in judged[tags[0]]}
        b = {(r["id"], r["context"]): r for r in judged[tags[1]]}
        shared = sorted(a.keys() & b.keys())
        print(f"\njudge agreement {tags[0]} vs {tags[1]} on {len(shared)} items")
        print(f"  pass agreement {np.mean([a[k]['pass'] == b[k]['pass'] for k in shared]):.2f}")
        for c in EXPERT_FIELDS:
            ks = [k for k in shared if a[k].get(c) is not None and b[k].get(c) is not None]
            kappa = weighted_kappa([a[k][c] for k in ks], [b[k][c] for k in ks]) if ks else None
            print(f"  {c:16} kappa {kappa if kappa is None else round(kappa, 2)} (n={len(ks)})")
    print("\nautomatic checks (no judge):")
    for context in CONTEXTS:
        g = [x["checks"] for x in run["generations"] if x["context"] == context]
        if g:
            rel = [c["cites_relevant"] for c in g if c["cites_relevant"] is not None]
            print(
                f"  {context:9} n={len(g):>3}  abstained {np.mean([c['abstained'] for c in g]):.2f}"
                f"  bad citations {np.mean([bool(c['invalid_citations']) for c in g]):.2f}"
                f"  cites a relevant unit {np.mean(rel) if rel else float('nan'):.2f}"
                f"  words {np.mean([c['words'] for c in g]):.0f}"
            )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier", default="silver", choices=["bronze", "silver", "gold"])
    ap.add_argument("--source", default="synthetic", choices=["synthetic"])
    ap.add_argument("--run-dir", type=Path, default=RUNS / datetime.now().strftime("%Y%m%d-%H%M"))
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--representation", help="experiment label; default: `selected` in latest.json")
    ap.add_argument("--labels", choices=["original", "pooled"], default="pooled")
    ap.add_argument("--budget", type=int, default=500, help="tokens of notes per answer")
    ap.add_argument("--contexts", nargs="+", choices=CONTEXTS, default=list(CONTEXTS))
    ap.add_argument("--limit", type=int, help="only the first N questions (smoke test)")
    ap.add_argument("--report", type=Path, metavar="RUN_DIR", help="summarise judged results")
    args = ap.parse_args(argv)
    if args.report:
        report(args.report)
        return 0

    out_path = args.run_dir / "generations.json"
    if out_path.exists():
        run = json.loads(out_path.read_text())
    else:
        run = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "options": {**GENERATION_OPTIONS, "temperature": 0},
            "model": args.model,
            **build_contexts(args),
            "generations": [],
        }
        write_json(out_path, run)
        print(f"{len(run['questions'])} questions, representation {run['representation']}")
    generate(run, args, out_path)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
