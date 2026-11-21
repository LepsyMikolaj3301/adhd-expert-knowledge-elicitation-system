# ruff: noqa: E501  (report strings)
"""How retrieval holds up as more experts answer the same vignettes (schema `chips_scale`).

Usage: python scripts/rag/eval_scale_retrieval.py --run-dir data/eval/scale_retrieval/<name> \
           [--schema chips_scale] [--ns 1 2 5 10 15 20] [--ks 4 8] [--order 1 2 21 22 ...] [--limit N]

Ingests the filled vignettes of tests/fixtures/scale_answers (scripts/db/chips_fixture.py: units,
bge-m3 vectors, BM25) into --schema, replacing it, then evaluates; needs Postgres and Ollama with
bge-m3. The pool at n is the first n experts (SYN-001, SYN-002 ... by number) of the schema, or of
--order (expert numbers: `--order 1 2 21 22 ... 32 3 4 ...` puts the experts of other models before the qwen
ones, so equal-size pools can be compared), selected with ExpertFilter(experts=...): dense ranking is exactly that of an n-expert corpus, BM25 statistics
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
            near-duplicate down-weighting on and off, and with the agreement grouping of fragments on and
            off (the groups are recomputed for the pool at every n: a note then counts for every
            clinician of the pool who marked the passage)

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
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
from langchain_core.embeddings import Embeddings
from psycopg import sql

from expert_knowledge_rag import (
    ExpertFilter,
    ExpertKnowledgeStore,
    ExpertQuestionRetriever,
)

ROOT = Path(__file__).resolve().parents[2]
ANCHORS = ["V001", "V004", "V006", "V012"]
FIXED = [
    "Which passages of this teaching case did the clinicians read as pointing toward or away from ADHD-related traits, and why?",
    "Where do the clinicians who read this case agree, and where do their readings differ?",
    "What other explanations did the clinicians give for the highlighted passages, and what did they say was missing from the text?",
]
UNIT_KEY = re.compile(r"DOC-SYN-(\d{4}).*?(V\d{3})-(h\d+|case)$")
MODALS = re.compile(r"\b(would|could|may|might|can|will|is likely|are likely)\b")


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


def build_questions(
    queries: dict, vignettes: dict[str, Any], limit: int | None = None
) -> list[dict]:
    """The three sets, from an ingested corpus's `queries` (labelled questions, claim -> unit ids of
    the same schema) and the vignettes (id -> Vignette)."""
    covers = queries["covers"]
    qs: list[dict] = []
    for i, q in enumerate(queries["questions"], 1):
        qs.append(
            {"id": f"L{i:02d}", "set": "labelled", "question": q["question"], "targets": q["vignettes"],
             "claims": {c: list(covers.get(c, [])) for c in q["claim_ids"]}}
        )  # fmt: skip
    for vid in sorted(vignettes):
        v = {
            "id": vid,
            "design": vignettes[vid].design.model_dump(),
            "framing": vignettes[vid].framing,
        }
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
    return qs[:limit] if limit else qs


# --- metrics ---------------------------------------------------------------------------------


def fragments(doc: Any) -> set[str]:
    words = {w["text"].lower() for w in doc.metadata.get("patient_words", [])}
    return words or {f"case:{doc.metadata['vignette_id']}"}


def crowding(docs: list) -> float:
    """Share of notes (after the first) that repeat a fragment an earlier note already has."""
    return sum(crowding_split(docs).values()) / len(docs) if docs else 0.0


def is_case_note(doc: Any) -> bool:
    return "fragment" not in doc.metadata.get("kinds", [])


def crowding_split(docs: list) -> dict[str, int]:
    """The repeated notes of `crowding`, told apart by what they are: a case note (the whole
    vignette) or one with fragments."""
    seen: set[str] = set()
    repeats = {"case": 0, "fragment": 0}
    for d in docs:
        frags = fragments(d)
        if frags & seen:
            repeats["case" if is_case_note(d) else "fragment"] += 1
        seen |= frags
    return repeats


def passage_keys(doc: Any, group_of: dict[str, int]) -> set[str]:
    """What a note is about, by agreement group (the clinicians' overlapping highlights are one
    passage even when their words differ): its fragment units' groups, or the vignette for a case."""
    keys = {f"g{group_of[u]}" for u in doc.metadata["unit_ids"] if u in group_of}
    return keys or {f"case:{doc.metadata['vignette_id']}"}


def passage_crowding(docs: list, group_of: dict[str, int]) -> float:
    """Like `crowding`, but a repeat is a note about a passage (agreement group) already in the list."""
    seen: set[str] = set()
    repeats = 0
    for d in docs:
        keys = passage_keys(d, group_of)
        repeats += bool(keys & seen)
        seen |= keys
    return repeats / len(docs) if docs else 0.0


def measure(
    q: dict,
    docs: list,
    k: int,
    pool: list[str],
    facts: dict,
    anchors: set[str],
    group_of: dict[str, int] | None = None,
) -> dict:
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
        split = crowding_split(docs)
        row["crowding_fragment"] = round(split["fragment"] / len(docs), 3) if docs else 0.0
        row["crowding_case"] = round(split["case"] / len(docs), 3) if docs else 0.0
        row["case_share"] = round(sum(map(is_case_note, docs)) / len(docs), 3) if docs else 0.0
        # what grouping the case notes of a vignette into one would free (a what-if: not implemented)
        case_vignettes = [d.metadata["vignette_id"] for d in docs if is_case_note(d)]
        row["case_freed"] = len(case_vignettes) - len(set(case_vignettes))
        row["clinicians_counted"] = len({e for d in docs for e in d.metadata.get("expert_ids", [d.metadata["expert_id"]])})
        if group_of:
            row["crowding_passage"] = round(passage_crowding(docs, group_of), 3)
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


def pool_at(experts: list[str], n: int, order: list[int] | None) -> list[str]:
    """The first n experts: in the schema's order, or in the order of the expert numbers `order`."""
    if not order:
        return experts[:n]
    ids = [next((e for e in experts if e.endswith(f"SYN-{num:03d}")), None) for num in order]
    if missing := [num for num, i in zip(order, ids, strict=True) if i is None]:
        raise ValueError(f"--order names experts that are not in the schema: {missing}")
    return ids[:n]  # type: ignore[return-value]


def evaluate(
    store: ExpertKnowledgeStore,
    embeddings: Embeddings,
    facts: dict,
    questions: list[dict],
    ns: list[int],
    ks: list[int],
    order: list[int] | None = None,
    log: bool = False,
    grouping: Callable[[list[str]], dict[str, int]] | None = None,
) -> list[dict]:
    """Every question at every (n, k), with the near-duplicate down-weighting on (and off, for `fixed`).

    `grouping(pool)` recomputes the agreement groups of the schema for the pool's experts and returns
    each highlight's group; with it the `fixed` questions also run with `group_fragments` on."""
    anchors = set(ANCHORS)
    results: list[dict] = []
    for n in ns:
        pool = pool_at(facts["experts"], n, order)
        in_pool = {v for v, es in facts["by_vignette"].items() if set(es) & set(pool)}
        group_of = grouping(pool) if grouping else {}
        for k in ks:
            for dw, grp in [(True, False), (False, False), *([(True, True), (False, True)] if grouping else [])]:
                for q in questions:
                    if q["set"] != "fixed" and (not dw or grp):
                        continue
                    targets = [t for t in q["targets"] if t in in_pool]
                    if not targets:
                        continue  # nobody in the pool has answered this vignette yet
                    flt = ExpertFilter(
                        experts=pool,
                        vignettes=[q["vignette"]] if q["set"] == "fixed" else None,
                    )
                    retriever = ExpertQuestionRetriever(
                        store=store,
                        embeddings=embeddings,
                        k=k,
                        filter=flt,
                        downweight_duplicate_cases=dw,
                        group_fragments=grp,
                        groups_match_filter=True,
                    )
                    t0 = time.monotonic()
                    docs = retriever.invoke(q["question"])
                    ms = (time.monotonic() - t0) * 1000
                    row = measure({**q, "targets": targets}, docs, k, pool, facts, anchors, group_of)
                    results.append(
                        {
                            "id": q["id"],
                            "set": q["set"],
                            "n": n,
                            "k": k,
                            "downweight": dw,
                            "group": grp,
                            "ms": round(ms, 1),
                            **row,
                        }
                    )
        if log:
            print(f"n={n}: pool {len(pool)} experts, {len(in_pool)} vignettes answered", flush=True)
    return results


def summary(schema: str, facts: dict, questions: list[dict], order, results: list[dict]) -> dict:
    return {"schema": schema, "facts": {"experts": facts["experts"], "units": facts["n_units"],
            "experts_per_vignette": {v: len(e) for v, e in sorted(facts["by_vignette"].items())}},
            "questions": len(questions), "order": order, "results": results}  # fmt: skip


def run(args: argparse.Namespace) -> dict:
    sys.path.insert(0, str(ROOT / "scripts" / "db"))
    import chips_fixture

    dsn = os.environ["DATABASE_URL"]
    answers = chips_fixture.load(args.fixture)
    embeddings = chips_fixture.IndexEmbeddings()
    corpus = chips_fixture.ingest(answers, embeddings, patients=False)
    with chips_fixture.seeded_schema(dsn, args.schema, corpus, keep=True):
        print(f"seeded {args.schema} from {args.fixture}", flush=True)
    facts = pool_facts(dsn, args.schema)
    if len(facts["experts"]) < max(args.ns):
        sys.exit(f"{args.schema} has {len(facts['experts'])} experts, --ns asks for {max(args.ns)}")
    if args.order and len(args.order) < max(args.ns):
        sys.exit(f"--order lists {len(args.order)} experts, --ns asks for {max(args.ns)}")
    store = ExpertKnowledgeStore(dsn, schema=args.schema)
    questions = build_questions(corpus.queries, answers.vignettes, args.limit)
    for q in questions:
        embeddings.embed_query(q["question"])  # embedded first; the loops below touch only Postgres
    grouping = lambda pool: chips_fixture.set_agreement_pool(dsn, args.schema, pool)  # noqa: E731
    try:
        results = evaluate(
            store, embeddings, facts, questions, args.ns, args.ks, args.order, log=True, grouping=grouping
        )
    finally:
        chips_fixture.set_agreement_pool(dsn, args.schema, None)  # back to everyone's groups
    return summary(args.schema, facts, questions, args.order, results)


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


def order_note(order: list[int] | None) -> str:
    return (
        "the first n experts"
        if not order
        else f"the first n of experts {', '.join(map(str, order))}"
    )


def _fixed(anchor: bool | None, dw: bool, grp: bool):
    """Rows of the `fixed` questions: on anchor vignettes (None: either), with the down-weighting
    and the grouping as given."""
    return lambda r: (
        r["set"] == "fixed"
        and (anchor is None or (r["id"].split("-")[1] in ANCHORS) == anchor)
        and r["downweight"] == dw
        and r.get("group", False) == grp
    )


CURVE_RULES = {  # name -> (rows, field, the first n against base that counts as a problem)
    "crowding_anchor": (_fixed(True, True, False), "crowding", lambda b, v: v >= 0.5),
    "crowding_anchor_off": (_fixed(True, False, False), "crowding", None),
    "crowding_other": (_fixed(False, True, False), "crowding", None),
    "coverage_anchor": (_fixed(True, True, False), "expert_coverage", None),
    "precision_labelled": (lambda r: r["set"] == "labelled", "vignette_precision", lambda b, v: b - v >= 0.15),
    "recall_labelled": (lambda r: r["set"] == "labelled", "claim_recall",
                        lambda b, v: b > 0 and (b - v) / b >= 0.25),
    "precision_topic": (lambda r: r["set"] == "topic", "vignette_precision", lambda b, v: b - v >= 0.15),
    # the grouping of fragments (groups recomputed for the pool), with the down-weighting on and off
    "crowding_anchor_grouped": (_fixed(True, True, True), "crowding", lambda b, v: v >= 0.5),
    "crowding_anchor_grouped_nodw": (_fixed(True, False, True), "crowding", None),
    "crowding_other_grouped": (_fixed(False, True, True), "crowding", None),
    "coverage_anchor_grouped": (_fixed(True, True, True), "expert_coverage", None),
    "clinicians_anchor": (_fixed(True, True, False), "clinicians_counted", None),
    "clinicians_anchor_grouped": (_fixed(True, True, True), "clinicians_counted", None),
    # what the crowding is made of (anchors, down-weighting on), and by agreement group
    "crowding_fragment_anchor": (_fixed(True, True, False), "crowding_fragment", None),
    "crowding_case_anchor": (_fixed(True, True, False), "crowding_case", None),
    "crowding_case_anchor_nodw": (_fixed(True, False, False), "crowding_case", None),
    "crowding_case_anchor_grouped": (_fixed(True, True, True), "crowding_case", None),
    "case_freed_anchor": (_fixed(True, True, False), "case_freed", None),
    "case_freed_anchor_grouped": (_fixed(True, True, True), "case_freed", None),
    "case_share_anchor": (_fixed(True, True, False), "case_share", None),
    "crowding_passage_anchor": (_fixed(True, True, False), "crowding_passage", None),
    "crowding_passage_anchor_grouped": (_fixed(True, True, True), "crowding_passage", None),
}  # fmt: skip


def curves(results: list[dict], ns: list[int], ks: list[int]) -> dict:
    """Per curve and k: the mean at every n, how many items it averages, and the first problem n."""
    base = 2 if 2 in ns else ns[0]
    out: dict = {}
    for name, (keep, field, rule) in CURVE_RULES.items():
        rows = [r for r in results if keep(r)]
        out[name] = {}
        for k in ks:
            curve = {n: mean([r for r in rows if r["n"] == n and r["k"] == k], field) for n in ns}
            count = {n: len([r for r in rows if r["n"] == n and r["k"] == k]) for n in ns}
            out[name][k] = {"mean": curve, "items": count,
                            "problem_n": first_problem(curve, base, rule) if rule else None}  # fmt: skip
    return out


def report(data: dict, ns: list[int], ks: list[int], path: Path) -> None:
    res = data["results"]
    out = [f"# Retrieval at scale: schema {data['schema']}\n"]
    out.append(
        f"{len(data['facts']['experts'])} experts, {data['facts']['units']} units, {data['questions']} questions. Pool at n = {order_note(data.get('order'))}.\n"
    )
    out.append(
        "Experts per vignette: "
        + ", ".join(f"{v}:{c}" for v, c in data["facts"]["experts_per_vignette"].items())
        + "\n"
    )

    anchor_rows = [r for r in res if r["set"] == "fixed" and r["id"].split("-")[1] in ANCHORS]
    other_rows = [r for r in res if r["set"] == "fixed" and r["id"].split("-")[1] not in ANCHORS]

    def block(title: str, rows: list[dict], field: str) -> None:
        out.append(f"\n## {title}\n")
        out.append("| n | " + " | ".join(f"k={k}" for k in ks) + " |")
        out.append("|---|" + "---|" * len(ks))
        for n in ns:
            cells = []
            for k in ks:
                sub = [r for r in rows if r["n"] == n and r["k"] == k]
                m = mean(sub, field)
                cells.append(f"{m if m is not None else '-'} ({len(sub)})")
            out.append(f"| {n} | " + " | ".join(cells) + " |")

    on = [r for r in anchor_rows if r["downweight"] and not r.get("group")]
    off = [r for r in anchor_rows if not r["downweight"] and not r.get("group")]
    grouped = [r for r in anchor_rows if r["downweight"] and r.get("group")]
    grouped_off = [r for r in anchor_rows if not r["downweight"] and r.get("group")]
    block(
        "Crowding@k, anchor vignettes, per-vignette questions (down-weighting on; items in brackets)",
        on,
        "crowding",
    )
    block("Crowding@k, anchor vignettes, down-weighting OFF", off, "crowding")
    block(
        "Crowding@k, other vignettes, down-weighting on",
        [r for r in other_rows if r["downweight"] and not r.get("group")],
        "crowding",
    )
    if grouped:
        block("Crowding@k, anchor vignettes, fragments GROUPED (down-weighting on)", grouped, "crowding")
        block("Crowding@k, anchor vignettes, fragments GROUPED, down-weighting OFF", grouped_off, "crowding")
        block("Crowding@k, other vignettes, fragments GROUPED", [r for r in other_rows if r["downweight"] and r.get("group")], "crowding")
        block("Expert coverage, anchors, GROUPED", grouped, "expert_coverage")
        block("Clinicians whose words the top k carries, anchors, plain", on, "clinicians_counted")
        block("Clinicians whose words the top k carries, anchors, GROUPED", grouped, "clinicians_counted")
        block("Passage crowding (by agreement group), anchors, plain", on, "crowding_passage")
        block("Passage crowding (by agreement group), anchors, GROUPED", grouped, "crowding_passage")
    block("Crowding from repeated fragments, anchors, plain", on, "crowding_fragment")
    block("Crowding from repeated case notes, anchors, plain (down-weighting on)", on, "crowding_case")
    block("Crowding from repeated case notes, anchors, plain, down-weighting OFF", off, "crowding_case")
    block("Share of the top k that is case notes, anchors, plain", on, "case_share")
    block("Places freed in the top k if the case notes of a vignette were ONE note (what-if), anchors, plain", on, "case_freed")
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
    block(
        "Vignette precision@k, labelled questions (all vignettes, no filter)",
        [r for r in res if r["set"] == "labelled"],
        "vignette_precision",
    )
    block(
        "Original-label claim recall@k, labelled questions (experts 1-2 only: a lower bound)",
        [r for r in res if r["set"] == "labelled"],
        "claim_recall",
    )
    block(
        "Anchor share of the top k, labelled questions",
        [r for r in res if r["set"] == "labelled"],
        "anchor_share",
    )
    block(
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
    names = {
        "crowding_anchor": "crowding@k >= 0.5 on anchors",
        "precision_labelled": "labelled vignette precision falls by 0.15",
        "precision_topic": "topic vignette precision falls by 0.15",
        "recall_labelled": "original-label recall falls by a quarter",
    }
    found = curves(res, ns, ks)
    for k in ks:
        out.append(
            f"k={k}: "
            + "; ".join(
                f"{label}: {'n=' + str(n) if (n := found[name][k]['problem_n']) else 'not reached'}"
                for name, label in names.items()
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
    ap.add_argument("--run-dir", type=Path)
    ap.add_argument("--schema", default="chips_scale", help="seeded (replaced) from --fixture")
    ap.add_argument("--fixture", type=Path, default=ROOT / "tests" / "fixtures" / "scale_answers")
    ap.add_argument("--ns", type=int, nargs="+", default=[1, 2, 5, 10, 15, 20])
    ap.add_argument("--ks", type=int, nargs="+", default=[4, 8])
    ap.add_argument(
        "--order", type=int, nargs="+", help="expert numbers in the order the pools grow"
    )
    ap.add_argument("--limit", type=int, help="only the first N questions (smoke test)")
    args = ap.parse_args()
    if not args.run_dir:
        ap.error("--run-dir is required")
    args.run_dir.mkdir(parents=True, exist_ok=True)
    data = run(args)
    (args.run_dir / "results.json").write_text(json.dumps(data, indent=1))
    report(data, args.ns, args.ks, args.run_dir / "report.md")
    print(f"wrote {args.run_dir / 'report.md'}")


if __name__ == "__main__":
    main()
