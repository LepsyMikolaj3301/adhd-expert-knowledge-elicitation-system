# ruff: noqa: E501  (report strings)
"""How retrieval holds up as more experts answer the same vignettes (schema `chips_scale`).

Usage: python scripts/rag/eval_scale_retrieval.py --run-dir data/eval/scale_retrieval/<name> \
           [--schema chips_scale] [--ns 1 2 5 10 15 20] [--ks 4 8] [--limit N]

Needs the scale fixture (scripts/elicitation/make_scale_fixtures.py: stages seed, vignettes, answers,
build). The pool at n is the first n experts (SYN-001, SYN-002 ... by number) of the schema, selected
with ExpertFilter(experts=...): dense ranking is exactly that of an n-expert corpus, BM25 statistics
stay those of all experts. Experts 1-2 are the silver ones whose claims label the 40 questions.

Question sets (every question is embedded once, so the latency is the database's):
  labelled  the 40 silver questions across all vignettes. vignette precision@k (share of the top k from
            the vignettes the labels come from), original-label claim recall (only claims of experts 1-2,
            so a lower bound once other experts say the same), anchor share
  topic     per vignette with planted cues: a question made from its trait and confounder, no vignette
            filter. Relevant = units of that vignette (strict: other vignettes may say the same)
  fixed     per vignette, three questions limited to that vignette (the several-experts case):
            expert coverage (distinct experts in the top k / min(k, experts that answered it)) and
            crowding@k (share of notes that repeat a fragment already in the list), with the
            near-duplicate down-weighting on and off

A "problem" is the first n where, against n=2: crowding@4 on anchor vignettes reaches 0.5, vignette
precision of `labelled` or `topic` falls by 0.15, or original-label recall falls by a quarter.
Writes <run-dir>/results.json (every question at every n) and report.md.
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg
from langchain_core.embeddings import Embeddings
from psycopg import sql

from expert_knowledge_rag import (
    ExpertFilter,
    ExpertKnowledgeStore,
    ExpertQuestionRetriever,
    default_embeddings,
)

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "tests" / "fixtures" / "retrieval_silver" / "queries.json"
FIXTURES = ROOT / "data" / "fixtures_chips_scale" / "synthetic" / "silver"
ANCHORS = ["V001", "V004", "V006", "V012"]
FIXED = [
    "Which passages of this teaching case did the clinicians read as pointing toward or away from ADHD-related traits, and why?",
    "Where do the clinicians who read this case agree, and where do their readings differ?",
    "What other explanations did the clinicians give for the highlighted passages, and what did they say was missing from the text?",
]
UNIT_KEY = re.compile(r"DOC-SYN-(\d{4}).*?(V\d{3})-(h\d+|case)$")
MODALS = re.compile(r"\b(would|could|may|might|can|will|is likely|are likely)\b")


class CachedQueries(Embeddings):
    """Embeds each query text once, so repeated searches measure only the database."""

    def __init__(self, inner: Embeddings) -> None:
        self.inner, self.cache = inner, {}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        if text not in self.cache:
            self.cache[text] = self.inner.embed_query(text)
        return self.cache[text]


# --- the data --------------------------------------------------------------------------------


def pool_facts(dsn: str, schema: str) -> dict[str, Any]:
    """experts (ordered), experts per vignette, unit -> (doc number, vignette, local id), unit counts."""
    ident = sql.Identifier(schema)
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        rows = conn.execute(
            sql.SQL("SELECT id, expert_id, vignette_id FROM {}.finding_units").format(ident)
        ).fetchall()
    experts = sorted({r[1] for r in rows})
    by_vignette: dict[str, set[str]] = defaultdict(set)
    key_of: dict[tuple[str, str, str], str] = {}
    for uid, expert, vignette in rows:
        by_vignette[vignette].add(expert)
        if m := UNIT_KEY.search(uid):
            key_of[(m[1], m[2], m[3])] = uid
    return {"experts": experts, "by_vignette": by_vignette, "key_of": key_of, "n_units": len(rows)}


def topic_question(design: dict, framing: str) -> list[tuple[str, str]]:
    """One question per planted trait of a vignette, with its first confounder as the competing reading."""
    out = []
    alt = ""
    if design["confounders"]:
        text = design["confounders"][0]["alternative_explanation"].rstrip(". ")
        alt = MODALS.split(text)[0].strip().lower() or text.lower()
    seen = set()
    for cue in design["planted_cues"]:
        trait = cue["trait"].replace("_", " ")
        if trait in seen:
            continue
        seen.add(trait)
        where = framing.replace("_", " ")
        tail = (
            f" when {alt} could also explain it"
            if alt
            else " when nothing else obviously explains it"
        )
        out.append((trait, f"How much weight do clinicians give {trait} in a {where}{tail}?"))
    return out


def build_questions(args: argparse.Namespace, facts: dict) -> list[dict]:
    snap = json.loads(SNAPSHOT.read_text())
    covers = {c: units for c, units in snap["covers"].items()}
    qs: list[dict] = []
    for i, q in enumerate(snap["questions"], 1):
        keys = {
            c: [UNIT_KEY.search(u).groups() for u in covers.get(c, []) if UNIT_KEY.search(u)]
            for c in q["claim_ids"]
        }
        qs.append(
            {"id": f"L{i:02d}", "set": "labelled", "question": q["question"], "targets": q["vignettes"],
             "claims": {c: [facts["key_of"].get(k) for k in ks] for c, ks in keys.items()}}
        )  # fmt: skip
    for path in sorted((FIXTURES / "vignettes").glob("V*.json")):
        v = json.loads(path.read_text())
        for n, (trait, text) in enumerate(topic_question(v["design"], v["framing"]), 1):
            qs.append(
                {
                    "id": f"T-{v['id']}-{n}",
                    "set": "topic",
                    "question": text,
                    "targets": [v["id"]],
                    "trait": trait,
                }
            )
        for n, text in enumerate(FIXED, 1):
            qs.append({"id": f"F-{v['id']}-{n}", "set": "fixed", "question": text, "targets": [v["id"]],
                       "vignette": v["id"], "anchor": v["id"] in ANCHORS})  # fmt: skip
    return qs[: args.limit] if args.limit else qs


# --- metrics ---------------------------------------------------------------------------------


def fragments(doc: Any) -> set[str]:
    words = {w["text"].lower() for w in doc.metadata.get("patient_words", [])}
    return words or {f"case:{doc.metadata['vignette_id']}"}


def crowding(docs: list) -> float:
    """Share of notes (after the first) that repeat a fragment an earlier note already has."""
    seen: set[str] = set()
    repeats = 0
    for d in docs:
        frags = fragments(d)
        repeats += bool(frags & seen)
        seen |= frags
    return repeats / len(docs) if docs else 0.0


def measure(q: dict, docs: list, k: int, pool: list[str], facts: dict, anchors: set[str]) -> dict:
    vignettes = [d.metadata["vignette_id"] for d in docs]
    row = {
        "vignettes": vignettes,
        "experts": [d.metadata["expert_id"] for d in docs],
        "units": [d.metadata["unit_ids"][0] for d in docs],
        "crowding": round(crowding(docs), 3),
        "vignette_precision": round(sum(v in q["targets"] for v in vignettes) / len(docs), 3) if docs else 0.0,
        "anchor_share": round(sum(v in anchors for v in vignettes) / len(docs), 3) if docs else 0.0,
    }  # fmt: skip
    if q["set"] == "fixed":
        available = len([e for e in facts["by_vignette"][q["vignette"]] if e in pool])
        row["expert_coverage"] = round(len(set(row["experts"])) / max(1, min(k, available)), 3)
        row["available_experts"] = available
    if q["set"] == "labelled":
        found = {u for d in docs for u in d.metadata["unit_ids"]}
        in_pool = lambda u: u and any(e in pool for e in [expert_of(u, facts)])  # noqa: E731
        reachable = {c for c, us in q["claims"].items() if any(in_pool(u) for u in us)}
        hit = {c for c in reachable if any(u in found for u in q["claims"][c] if u)}
        row["claim_recall"] = round(len(hit) / len(reachable), 3) if reachable else None
    return row


def expert_of(unit_id: str, facts: dict) -> str | None:
    m = UNIT_KEY.search(unit_id)
    return (
        next((e for e in facts["experts"] if e.endswith(f"SYN-{int(m[1]):03d}")), None)
        if m
        else None
    )


# --- the run ---------------------------------------------------------------------------------


def run(args: argparse.Namespace) -> dict:
    dsn = os.environ["DATABASE_URL"]
    facts = pool_facts(dsn, args.schema)
    if len(facts["experts"]) < max(args.ns):
        sys.exit(f"{args.schema} has {len(facts['experts'])} experts, --ns asks for {max(args.ns)}")
    store = ExpertKnowledgeStore(dsn, schema=args.schema)
    embeddings = CachedQueries(
        default_embeddings(base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"))
    )
    questions = build_questions(args, facts)
    anchors = set(ANCHORS)
    for q in questions:
        embeddings.embed_query(q["question"])  # embedded first; the loops below touch only Postgres
    results: list[dict] = []
    for n in args.ns:
        pool = facts["experts"][:n]
        in_pool = {v for v, es in facts["by_vignette"].items() if set(es) & set(pool)}
        for k in args.ks:
            for dw in (True, False):
                for q in questions:
                    if q["set"] != "fixed" and not dw:
                        continue
                    targets = [t for t in q["targets"] if t in in_pool]
                    if not targets:
                        continue  # nobody in the pool has answered this vignette yet
                    flt = ExpertFilter(
                        include_synthetic=True,
                        experts=pool,
                        vignettes=[q["vignette"]] if q["set"] == "fixed" else None,
                    )
                    retriever = ExpertQuestionRetriever(
                        store=store,
                        embeddings=embeddings,
                        k=k,
                        filter=flt,
                        downweight_duplicate_cases=dw,
                    )
                    t0 = time.monotonic()
                    docs = retriever.invoke(q["question"])
                    ms = (time.monotonic() - t0) * 1000
                    row = measure({**q, "targets": targets}, docs, k, pool, facts, anchors)
                    results.append(
                        {
                            "id": q["id"],
                            "set": q["set"],
                            "n": n,
                            "k": k,
                            "downweight": dw,
                            "ms": round(ms, 1),
                            **row,
                        }
                    )
        print(f"n={n}: pool {len(pool)} experts, {len(in_pool)} vignettes answered", flush=True)
    return {"schema": args.schema, "facts": {"experts": facts["experts"], "units": facts["n_units"],
            "experts_per_vignette": {v: len(e) for v, e in sorted(facts["by_vignette"].items())}},
            "questions": len(questions), "results": results}  # fmt: skip


# --- report ----------------------------------------------------------------------------------


def mean(rows: list[dict], field: str) -> float | None:
    values = [r[field] for r in rows if r.get(field) is not None]
    return round(statistics.mean(values), 3) if values else None


def first_problem(curve: dict[int, float | None], base_n: int, rule) -> int | None:
    base = curve.get(base_n)
    if base is None:
        return None
    return next(
        (n for n, v in curve.items() if n > base_n and v is not None and rule(base, v)), None
    )


def report(data: dict, ns: list[int], ks: list[int], path: Path) -> None:
    res = data["results"]
    out = [f"# Retrieval at scale: schema {data['schema']}\n"]
    out.append(
        f"{len(data['facts']['experts'])} experts, {data['facts']['units']} units, {data['questions']} questions. Pool at n = the first n experts.\n"
    )
    out.append(
        "Experts per vignette: "
        + ", ".join(f"{v}:{c}" for v, c in data["facts"]["experts_per_vignette"].items())
        + "\n"
    )

    anchor_rows = [r for r in res if r["set"] == "fixed" and r["id"].split("-")[1] in ANCHORS]
    other_rows = [r for r in res if r["set"] == "fixed" and r["id"].split("-")[1] not in ANCHORS]

    def block(title: str, rows: list[dict], field: str) -> dict[int, dict[int, float | None]]:
        out.append(f"\n## {title}\n")
        out.append("| n | " + " | ".join(f"k={k}" for k in ks) + " |")
        out.append("|---|" + "---|" * len(ks))
        curves: dict[int, dict[int, float | None]] = {k: {} for k in ks}
        for n in ns:
            cells = []
            for k in ks:
                sub = [r for r in rows if r["n"] == n and r["k"] == k]
                m = mean(sub, field)
                curves[k][n] = m
                cells.append(f"{m if m is not None else '-'} ({len(sub)})")
            out.append(f"| {n} | " + " | ".join(cells) + " |")
        return curves

    on = [r for r in anchor_rows if r["downweight"]]
    off = [r for r in anchor_rows if not r["downweight"]]
    crowd_on = block(
        "Crowding@k, anchor vignettes, per-vignette questions (down-weighting on; items in brackets)",
        on,
        "crowding",
    )
    block("Crowding@k, anchor vignettes, down-weighting OFF", off, "crowding")
    block(
        "Crowding@k, other vignettes, down-weighting on",
        [r for r in other_rows if r["downweight"]],
        "crowding",
    )
    block(
        "Expert coverage, anchor vignettes (distinct experts in top k / min(k, experts that answered it))",
        on,
        "expert_coverage",
    )
    block(
        "Experts retrieved vs available, anchors: mean number of experts available",
        on,
        "available_experts",
    )
    prec_l = block(
        "Vignette precision@k, labelled questions (all vignettes, no filter)",
        [r for r in res if r["set"] == "labelled"],
        "vignette_precision",
    )
    rec_l = block(
        "Original-label claim recall@k, labelled questions (experts 1-2 only: a lower bound)",
        [r for r in res if r["set"] == "labelled"],
        "claim_recall",
    )
    block(
        "Anchor share of the top k, labelled questions",
        [r for r in res if r["set"] == "labelled"],
        "anchor_share",
    )
    prec_t = block(
        "Target-vignette precision@k, topic questions (strict)",
        [r for r in res if r["set"] == "topic"],
        "vignette_precision",
    )
    block(
        "Anchor share of the top k, topic questions about non-anchor vignettes",
        [r for r in res if r["set"] == "topic" and r["id"].split("-")[1] not in ANCHORS],
        "anchor_share",
    )
    out.append("\n## Latency (ms per search, database only)\n")
    out.append("| n | p50 | p95 |\n|---|---|---|")
    for n in ns:
        ms = sorted(r["ms"] for r in res if r["n"] == n)
        if ms:
            out.append(
                f"| {n} | {ms[len(ms) // 2]:.0f} | {ms[min(len(ms) - 1, int(len(ms) * 0.95))]:.0f} |"
            )

    base = 2 if 2 in ns else ns[0]
    out.append(f"\n## Where it goes wrong (against n={base})\n")
    for k in ks:
        found = {
            "crowding@k >= 0.5 on anchors": first_problem(crowd_on[k], base, lambda b, v: v >= 0.5),
            "labelled vignette precision falls by 0.15": first_problem(
                prec_l[k], base, lambda b, v: b - v >= 0.15
            ),
            "topic vignette precision falls by 0.15": first_problem(
                prec_t[k], base, lambda b, v: b - v >= 0.15
            ),
            "original-label recall falls by a quarter": first_problem(
                rec_l[k], base, lambda b, v: b > 0 and (b - v) / b >= 0.25
            ),
        }
        out.append(
            f"k={k}: "
            + "; ".join(
                f"{name}: {'n=' + str(n) if n else 'not reached'}" for name, n in found.items()
            )
            + "\n"
        )
    out.append(
        "\nCaveats: experts 3-20 are written by one local model (counts are real, wording is more alike than real "
        "clinicians'); BM25 statistics are those of all experts; the pool at small n has no answers for the new "
        "vignettes yet, so the question sets differ between n (the bracketed counts).\n"
    )
    path.write_text("\n".join(out))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--schema", default="chips_scale")
    ap.add_argument("--ns", type=int, nargs="+", default=[1, 2, 5, 10, 15, 20])
    ap.add_argument("--ks", type=int, nargs="+", default=[4, 8])
    ap.add_argument("--limit", type=int, help="only the first N questions (smoke test)")
    args = ap.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    data = run(args)
    (args.run_dir / "results.json").write_text(json.dumps(data, indent=1))
    report(data, args.ns, args.ks, args.run_dir / "report.md")
    print(f"wrote {args.run_dir / 'report.md'}")


if __name__ == "__main__":
    main()
