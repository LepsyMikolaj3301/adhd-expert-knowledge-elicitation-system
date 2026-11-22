# ruff: noqa: E501  (report strings)
"""Final retrieval report: the package's retrievers on the existing and the new questions.

Usage: python scripts/rag/eval_final_retrieval.py --run-dir data/eval/final/<date>-retrieval \
           [--questions tests/fixtures/final_eval/queries.json]

Needs Postgres with `chips_silver` (try_expert_rag.py --seed-silver) and `chips_scale`
(chips_fixture.py seed --schema chips_scale, agreement groups of all 32 experts) and Ollama with bge-m3.
Every question is retrieved with the package (expert_rag_lib.retrieve, k=10 notes) under four
configurations: hybrid+group (fragment grouping), hybrid, dense, bm25. Sets:
  labelled  the 40 existing silver questions (claims of SYN-001/002), original and pooled labels,
            on chips_silver (2 experts) and chips_scale (32 experts; a lower bound there, since the
            other 30 experts' units that say the same are not labelled)
  patient   the 9 existing patient texts (a vignette's own text, its vignette excluded), weak labels
  final     the new items of make_final_queries.py on chips_scale: clinician questions, new patient
            texts (key points as claims); out-of-scope items have no labels: only their top-1 cosine
Metrics are expert_metrics.score_query (recall@k, hit@4, MRR, nDCG@10, recall@500t, ...), each with a
95% bootstrap interval over questions, and paired differences against `hybrid`. A grouped note carries
the units of every clinician in the group but quotes at most three; metrics are computed twice:
`shown` (only units whose words are in the note) and `carried` (every unit id of the note). Extra:
vignette precision@4 (notes from a vignette that holds a relevant unit), clinicians whose words the
top 4 notes carry, tokens per note. Writes <run-dir>/results.json and report.md.
"""

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from expert_metrics import Item, bootstrap, paired_bootstrap, score_query, tokens
from expert_rag_lib import SILVER_SCHEMA, build_items, retrieve, silver_corpus

from expert_knowledge_rag import ExpertKnowledgeStore, default_embeddings

SCALE = "chips_scale"
CONFIGS = {
    "hybrid+group": ("hybrid", True),
    "hybrid": ("hybrid", False),
    "dense": ("dense", False),
    "bm25": ("bm25", False),
}
DEPTH = 10
METRICS = ["recall@4", "recall@8", "hit@4", "mrr", "ndcg@10", "recall@500t", "recall@4/ceiling"]
EXTRA = ["vignette_precision@4", "clinicians@4", "tokens_per_note"]
CHIP = re.compile(r"«[^»]*»")


# --- which units a note shows ------------------------------------------------------------------


def first_words(embed_text: str) -> str:
    """The clinician's first sentence of a unit, without quoted chips, to find it in a note."""
    for line in embed_text.splitlines():
        if re.match(r"Q\d:", line):
            return re.sub(r"\s+", " ", CHIP.sub("", line[3:])).strip()[:40]
    return ""


def shown_units(doc, words: dict[str, str]) -> list[str]:
    units = doc.metadata["unit_ids"]
    if "group_id" not in doc.metadata:
        return units
    text = re.sub(r"\s+", " ", CHIP.sub("", doc.page_content))
    shown = [u for u in units if words.get(u) and words[u] in text]
    return shown or units[:1]


def unit_words(dsn: str, schema: str) -> dict[str, str]:
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        rows = conn.execute(f"SELECT id, embed_text FROM {schema}.finding_units").fetchall()
    return {u: first_words(t) for u, t in rows}


def top_cosine(dsn: str, schema: str, vector: list[float]) -> float:
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        row = conn.execute(
            f"SELECT 1 - (embedding <=> CAST(%s AS vector)) FROM {schema}.finding_units "
            "ORDER BY embedding <=> CAST(%s AS vector) LIMIT 1",
            ("[" + ",".join(f"{x:.7f}" for x in vector) + "]",) * 2,
        ).fetchone()
    return float(row[0])


# --- scoring -----------------------------------------------------------------------------------


def score(item: dict, docs: list, words: dict[str, str], vignette_of: dict[str, str]) -> dict:
    covers = {c: set(u) for c, u in item["covers"].items()}
    out = {}
    for view in ("shown", "carried"):
        ranked = [
            Item(
                unit_ids=shown_units(d, words) if view == "shown" else d.metadata["unit_ids"],
                shown=d.page_content,
                reps=[],
            )
            for d in docs
        ]
        s = score_query(ranked, list(covers), covers)
        out[view] = s
    relevant_vignettes = {vignette_of[u] for u in item["relevant_units"] if u in vignette_of}
    top = docs[:4]
    out["extra"] = {
        "vignette_precision@4": sum(d.metadata["vignette_id"] in relevant_vignettes for d in top)
        / max(len(top), 1),
        "clinicians@4": len(
            {e for d in top for e in d.metadata.get("expert_ids", [d.metadata["expert_id"]])}
        ),
        "tokens_per_note": sum(tokens(d.page_content) for d in top) / max(len(top), 1),
    }
    return out


def sets_for(questions: Path | None) -> list[tuple[str, str, list[dict]]]:
    """(set name, schema, items) with `covers` over the labels of that set."""
    corpus, _ = silver_corpus()
    covers = {c: sorted(u) for c, u in corpus.queries["covers"].items()}
    labelled = build_items(SILVER_SCHEMA, ["labelled"], DEPTH, None, {})
    pooled = [
        {
            **item,
            "covers": {c: covers.get(c, []) for c in q["pooled_ids"]},
            "relevant_units": sorted({u for c in q["pooled_ids"] for u in covers.get(c, [])}),
        }
        for item, q in zip(labelled, corpus.queries["questions"], strict=True)
    ]
    patient = [
        {**p, "covers": {c: covers.get(c, []) for c in pq["claim_ids"]}}
        for p, pq in zip(
            build_items(SILVER_SCHEMA, ["patient"], DEPTH, None, {}),
            corpus.queries["patients"],
            strict=True,
        )
    ]
    out = []
    for schema in (SILVER_SCHEMA, SCALE):
        n = "n=2" if schema == SILVER_SCHEMA else "n=32"
        out += [
            (f"labelled/original {n}", schema, labelled),
            (f"labelled/pooled {n}", schema, pooled),
            (f"patient/weak {n}", schema, patient),
        ]
    if questions:
        final = build_items(SCALE, ["final"], DEPTH, None, {}, final=questions)
        for kind in ("clinician", "patient", "out_of_scope"):
            out.append((f"final/{kind} n=32", SCALE, [i for i in final if i["kind"] == kind]))
    return out


# --- report ------------------------------------------------------------------------------------


def cell(values: list[float]) -> str:
    if not values:
        return "–"
    m, lo, hi = bootstrap(values)
    return f"{m:.3f} [{lo:.2f}, {hi:.2f}]"


def table(rows: dict, view: str, metrics: list[str]) -> list[str]:
    out = ["| konfiguracja | n | " + " | ".join(metrics) + " |", "|---" * (len(metrics) + 2) + "|"]
    for config, per_q in rows.items():
        scored = [s for s in per_q.values() if s[view]]
        vals = [
            cell([s[view][m] if view != "extra" else s["extra"][m] for s in scored])
            for m in metrics
        ]
        out.append(f"| {config} | {len(scored)} | " + " | ".join(vals) + " |")
    return out


def diffs(rows: dict, view: str) -> list[str]:
    out = []
    base = rows["hybrid"]
    for config, per_q in rows.items():
        if config == "hybrid":
            continue
        shared = [q for q in per_q if per_q[q][view] and base[q][view]]
        parts = []
        for m in ("recall@4", "ndcg@10"):
            d, lo, hi = paired_bootstrap(
                [per_q[q][view][m] for q in shared], [base[q][view][m] for q in shared]
            )
            sign = " **≠0**" if lo > 0 or hi < 0 else ""
            parts.append(f"{m} {d:+.3f} [{lo:+.2f}, {hi:+.2f}]{sign}")
        out.append(f"- {config} − hybrid: " + "; ".join(parts))
    return out


def report(results: dict) -> str:
    lines = [
        f"# Final retrieval ({results['generated_at']})",
        "",
        "Średnie z 95% przedziałami bootstrap (1000 prób, po pytaniach). `shown`: jednostki, których "
        "słowa są w nocie; `carried`: wszystkie jednostki noty (nota grupy niesie całą grupę).",
    ]
    for name, block in results["sets"].items():
        lines += ["", f"## {name} ({block['schema']}, {block['n_items']} pozycji)", ""]
        if block.get("top_cosine"):
            tc = block["top_cosine"]
            lines.append(f"Top-1 cosine (bge-m3) do najbliższej jednostki: {cell(tc)}")
            continue
        rows = block["scores"]
        lines += table(rows, "shown", METRICS) + [""]
        lines += ["carried:", ""] + table(rows, "carried", METRICS) + [""]
        lines += table(rows, "extra", EXTRA) + [""]
        lines += diffs(rows, "shown")
    if "top_cosine_in_scope" in results:
        lines += [
            "",
            f"Top-1 cosine pytań klinicysty w zakresie: {cell(results['top_cosine_in_scope'])}",
        ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--questions", type=Path)
    args = ap.parse_args()
    dsn = os.environ["DATABASE_URL"]
    embeddings = default_embeddings(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    results: dict = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "sets": {}}
    words = {s: unit_words(dsn, s) for s in (SILVER_SCHEMA, SCALE)}
    vignette_of: dict[str, dict[str, str]] = {}
    for s in (SILVER_SCHEMA, SCALE):
        with psycopg.connect(dsn) as conn:
            vignette_of[s] = dict(
                conn.execute(f"SELECT id, vignette_id FROM {s}.finding_units").fetchall()
            )
    for name, schema, items in sets_for(args.questions):
        store = ExpertKnowledgeStore(dsn, schema=schema)
        block: dict = {"schema": schema, "n_items": len(items)}
        if name.startswith("final/out_of_scope"):
            block["top_cosine"] = [
                top_cosine(dsn, schema, embeddings.embed_query(i["question"])) for i in items
            ]
        else:
            block["scores"] = {}
            for config, (search, grouped) in CONFIGS.items():
                per_q = {}
                for item in items:
                    docs = retrieve(item, store, embeddings, search, group_fragments=grouped)
                    per_q[item["id"]] = score(item, docs, words[schema], vignette_of[schema])
                block["scores"][config] = per_q
            print(
                f"{name}: hybrid+group recall@4 {cell([s['shown']['recall@4'] for s in block['scores']['hybrid+group'].values() if s['shown']])}"
            )
        results["sets"][name] = block
    if args.questions:
        clin = build_items(SCALE, ["final"], DEPTH, None, {}, final=args.questions)
        results["top_cosine_in_scope"] = [
            top_cosine(dsn, SCALE, embeddings.embed_query(i["question"]))
            for i in clin
            if i["kind"] == "clinician"
        ]
    args.run_dir.mkdir(parents=True, exist_ok=True)
    (args.run_dir / "results.json").write_text(json.dumps(results, indent=1))
    (args.run_dir / "report.md").write_text(report(results))
    print(f"wrote {args.run_dir / 'report.md'}")


if __name__ == "__main__":
    main()
