"""Evaluate the chunk sets written by chunk_documents.py (data/chunks/<strategy>/).

Blocks: A shape, B structure, C embedding-based (bge-m3), D retrieval (Chroma-style: qwen3 writes
questions with verbatim excerpts, retrieval is scored by char-level recall/precision/IoU),
E References Completeness (qwen3 resolves each pronoun to its antecedent), F MoC perplexity metrics
(Boundary Clarity, Chunk Stickiness; see chunk_lm.py).
Metrics follow "Adaptive Chunking" (arXiv 2603.25333: size compliance, block integrity,
intrachunk cohesion, document contextual coherence, references completeness), Chroma's
"Evaluating Chunking Strategies for Retrieval" (2024) and MoC (arXiv 2503.09600).

Usage: python scripts/evaluate_chunks.py [--chunks-dir data/chunks] [--k 1,3,5,10]
           [--size-min 50] [--size-max 256] [--questions-per-section 2] [--regen-queries]
           [--no-retrieval] [--no-coref] [--no-lm] [--lm Qwen/Qwen2.5-0.5B]
           [--stickiness-window 5] [--stickiness-k 0.1]
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from chunk_common import (
    STRATEGY_DIRS,
    OllamaClient,
    read_jsonl,
    split_sentences,
)

TINY_TOKENS = 32
BLOCK_TOLERANCE = 5  # chars, from the Block Integrity definition
DCC_BUDGET = 3000  # tokens per context window
DEDUPE_SIM = 0.95
MIN_EXCERPT_CHARS = 20
PRONOUN_RE = re.compile(
    r"\b(it|its|they|them|their|he|she|his|her|this|these|those|such)\b(?! as\b)", re.I
)
DANGLING = re.compile(r"^(This|These|Those|That|It|They|Such|He|She|Their|Its|His|Her)\b")
QUERY_PROMPT = """You are building a retrieval test set. Read the passage and write up to {n} \
questions that can be answered ONLY from this passage.
For each question give 1-2 excerpts: contiguous quotes copied VERBATIM from the passage \
(20-80 words each) that contain the answer.
Phrase each question in your own words; do not reuse the wording of the excerpt.

Section: {headings}

Passage:
{passage}"""
COREF_PROMPT = """In the text below, one pronoun is marked like [[this]]. Which noun phrase \
earlier in the text does it refer to?
Answer with that noun phrase copied VERBATIM from the text before the marker (1-6 words), or an \
empty string if it does not refer back to a specific earlier noun phrase (for example "it is \
important that ...", "such as", or a reference to the document itself).

Text:
{context}"""
COREF_SCHEMA = {
    "type": "object",
    "properties": {"antecedent": {"type": "string"}},
    "required": ["antecedent"],
}
QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "excerpts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question", "excerpts"],
            },
        }
    },
    "required": ["items"],
}


def nanmean(a) -> float:
    a = np.asarray(a, dtype=float)
    a = a[~np.isnan(a)]
    return float(a.mean()) if a.size else float("nan")


def print_table(title: str, header: list[str], rows: list[list]) -> None:
    def fmt(v):
        return f"{v:.3f}" if isinstance(v, float) else str(v)

    cells = [header] + [[fmt(v) for v in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]
    print(f"\n{title}")
    for r in cells:
        line = "  ".join(
            c.ljust(w) if i == 0 else c.rjust(w)
            for i, (c, w) in enumerate(zip(r, widths, strict=True))
        )
        print("  " + line)


def load_strategy(chunks_dir: Path, strategy: str):
    recs = [
        r
        for f in sorted((chunks_dir / STRATEGY_DIRS[strategy]).glob("*.jsonl"))
        for r in read_jsonl(f)
    ]
    parents = {r["id"]: r for r in recs if r["kind"] == "parent"}
    children = [r for r in recs if r["kind"] == "child"]
    return parents, children


# --- A + B: shape and structure -------------------------------------------------------------


def block_integrity(children, parents) -> float:
    """Share of parser blocks (paragraphs, list/table elements) not cut by an interior boundary."""
    by_parent = defaultdict(list)
    for c in children:
        by_parent[c["parent_id"]].append(c["span"])
    intact = total = 0
    for pid, spans in by_parent.items():
        bounds = [s[0] for s in spans[1:]] + [s[1] for s in spans[:-1]]
        for lo, hi in parents[pid]["blocks"]:
            total += 1
            intact += not any(lo + BLOCK_TOLERANCE < b < hi - BLOCK_TOLERANCE for b in bounds)
    return intact / total if total else float("nan")


def shape_structure(children, parents, max_tokens, size_min, size_max) -> dict:
    n = np.array([c["n_tokens"] for c in children])
    ctx = np.array([c["n_tokens_ctx"] for c in children])
    per_parent = Counter(c["parent_id"] for c in children)
    norm = [re.sub(r"\s+", " ", c["text"]).strip().lower() for c in children]
    texts = [c["text"].strip() for c in children]
    return {
        "chunks": len(n),
        "mean_tok": float(n.mean()),
        "median_tok": float(np.median(n)),
        "size_compl↑": float(((n >= size_min) & (n <= size_max)).mean()),
        "tiny↓": float((n < TINY_TOKENS).mean()),
        "utilisation": float(n.mean() / max_tokens),
        "single_child": float(np.mean([v == 1 for v in per_parent.values()])),
        "hdr_overhead": float(((ctx - n) / ctx).mean()),
        "dup↓": 1 - len(set(norm)) / len(norm),
        "block_integ↑": block_integrity(children, parents),
        "sent_end↑": float(np.mean([t[-1] in ".?!:)" for t in texts])),
        "mid_start↓": float(np.mean([t[0].islower() for t in texts])),
        "dangling↓": float(np.mean([bool(DANGLING.match(t)) for t in texts])),
    }


# --- C: embedding metrics -------------------------------------------------------------------


def embedding_features(children, client):
    """Per-chunk cohesion and adjacent similarity, plus DCC windows (source, value)."""
    vecs = client.embed([c["text"] for c in children])
    sent_texts, owner = [], []
    for i, c in enumerate(children):
        sents = [c["text"][a:b] for a, b in split_sentences(c["text"])]
        if len(sents) >= 2:
            sent_texts += sents
            owner += [i] * len(sents)
    sent_vecs = client.embed(sent_texts)
    cohesion = np.full(len(children), np.nan)
    owner = np.array(owner)
    for i in set(owner.tolist()):
        cohesion[i] = float((sent_vecs[owner == i] @ vecs[i]).mean())
    adjacent = np.full(len(children), np.nan)
    for i in range(1, len(children)):
        if children[i]["parent_id"] == children[i - 1]["parent_id"]:
            adjacent[i] = float(vecs[i] @ vecs[i - 1])
    # Document Contextual Coherence: chunk vs. embedding of its <=3000-token window of neighbours
    windows = []
    by_doc = defaultdict(list)
    for i, c in enumerate(children):
        by_doc[c["doc"]].append(i)
    for idxs in by_doc.values():
        i = 0
        while i < len(idxs) - 1:
            j, total = i, 0
            while j < len(idxs) and (
                j - i < 2 or total + children[idxs[j]]["n_tokens"] <= DCC_BUDGET
            ):
                total += children[idxs[j]]["n_tokens"]
                j += 1
            members = idxs[i:j]
            windows.append(
                (
                    children[members[0]]["source"],
                    members,
                    "\n".join(children[m]["text"] for m in members),
                )
            )
            if j >= len(idxs):
                break
            i += max(1, len(members) // 2)
    wvecs = client.embed([w[2] for w in windows])
    dcc = [
        (src, float((vecs[members] @ wv).mean()))
        for (src, members, _), wv in zip(windows, wvecs, strict=True)
    ]
    return cohesion, adjacent, dcc


def embedding_metrics(cohesion, adjacent, dcc, mask, group) -> dict:
    icc = max(0.0, nanmean(cohesion[mask]))
    adj = nanmean(adjacent[mask])
    return {
        "ICC↑": icc,
        "adjacent↓": adj,
        "ICC-adj↑": icc - adj,
        "DCC↑": max(0.0, nanmean([v for src, v in dcc if group == "all" or src == group])),
    }


# --- D: retrieval eval ----------------------------------------------------------------------


def generate_queries(client, parents, path: Path, n_questions: int, regen: bool) -> list[dict]:
    if regen and path.exists():
        path.unlink()
    done = {r["parent_id"] for r in read_jsonl(path)} if path.exists() else set()
    todo = [p for p in parents.values() if p["n_tokens"] >= 100 and p["id"] not in done]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for k, p in enumerate(todo, 1):
            prompt = QUERY_PROMPT.format(
                n=n_questions, headings=" > ".join(p["headings"]), passage=p["text"]
            )
            try:
                items = client.chat_json(prompt, QUERY_SCHEMA)["items"]
            except (ValueError, KeyError) as e:
                print(f"  query generation failed for {p['id']}: {e}")
                continue
            f.write(
                json.dumps({"parent_id": p["id"], "source": p["source"], "items": items}) + "\n"
            )
            f.flush()
            print(f"  generated queries {k}/{len(todo)}", end="\r")
    return read_jsonl(path)


def locate(excerpt: str, text: str):
    m = re.search(r"\s+".join(map(re.escape, excerpt.split())), text)
    return m.span() if m else None


def merge_intervals(spans):
    out = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def build_queries(client, parents, query_recs, min_sim) -> list[dict]:
    """Chroma-style filtering: verbatim excerpts only, dedupe near-identical questions, and drop
    excerpts that are not similar enough to their question."""
    counts = {"generated": 0}
    cands = []
    for rec in query_recs:
        text = parents[rec["parent_id"]]["text"]
        for item in rec["items"]:
            counts["generated"] += 1
            found = [
                (e, span)
                for e in item["excerpts"]
                if len(e) >= MIN_EXCERPT_CHARS and (span := locate(e, text))
            ]
            if found:
                cands.append(
                    {
                        "question": item["question"],
                        "parent_id": rec["parent_id"],
                        "source": rec["source"],
                        "excerpts": found,
                    }
                )
    counts["verbatim"] = len(cands)
    qvecs = client.embed([c["question"] for c in cands])
    keep = []
    for i in range(len(cands)):
        if not keep or (qvecs[keep] @ qvecs[i]).max() <= DEDUPE_SIM:
            keep.append(i)
    cands = [cands[i] for i in keep]
    qvecs = qvecs[keep]
    counts["deduped"] = len(cands)
    queries = []
    for c, qv in zip(cands, qvecs, strict=True):
        evecs = client.embed([e for e, _ in c["excerpts"]])
        good = [
            span for (_, span), ev in zip(c["excerpts"], evecs, strict=True) if qv @ ev >= min_sim
        ]
        if good:
            queries.append({**c, "vec": qv, "relevant": merge_intervals(good)})
    counts["final"] = len(queries)
    print("\nQuery set:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    return queries


def retrieval_scores(children, queries, client, ks) -> list[dict]:
    cvecs = client.embed([c["contextualized"] for c in children])
    qmat = np.stack([q["vec"] for q in queries])
    order = np.argsort(-(qmat @ cvecs.T), axis=1)[:, : max(ks)]
    results = []
    for q, ranked in zip(queries, order, strict=True):
        rel_size = sum(e - s for s, e in q["relevant"])
        inter = []
        for ci in ranked:
            c = children[ci]
            if c["parent_id"] != q["parent_id"]:
                inter.append(0)
                continue
            s, e = c["span"]
            inter.append(sum(max(0, min(e, b) - max(s, a)) for a, b in q["relevant"]))
        res = {"source": q["source"]}
        for k in ks:
            ret = sum(children[ci]["span"][1] - children[ci]["span"][0] for ci in ranked[:k])
            hit = sum(inter[:k])
            res[f"recall@{k}"] = hit / rel_size
            res[f"precision@{k}"] = hit / ret
            res[f"iou@{k}"] = hit / (rel_size + ret - hit)
            res[f"hit@{k}"] = float(
                any(children[ci]["parent_id"] == q["parent_id"] for ci in ranked[:k])
            )
        first = next((r for r, v in enumerate(inter, 1) if v > 0), None)
        res["mrr"] = 1 / first if first else 0.0
        results.append(res)
    return results


# --- E: References Completeness --------------------------------------------------------------


def pronoun_candidates(text: str) -> list[dict]:
    """Every pronoun/demonstrative occurrence with the text up to the end of its sentence and
    the two sentences before it, the pronoun marked as [[word]]."""
    sents = split_sentences(text)
    out = []
    for m in PRONOUN_RE.finditer(text):
        k = next((i for i, (a, b) in enumerate(sents) if a <= m.start() < b), None)
        if k is None:
            continue
        lo = sents[max(0, k - 2)][0]
        context = f"{text[lo : m.start()]}[[{m.group()}]]{text[m.end() : sents[k][1]]}"
        out.append({"p": [m.start(), m.end()], "lo": lo, "context": context})
    return out


def extract_references(client, parents, path: Path, regen: bool) -> list[dict]:
    """Resolve each pronoun occurrence to its antecedent with the LLM (stand-in for the Maverick
    coreference model used in the paper). The LLM only returns a short verbatim phrase, which is
    located before the pronoun; cached and resumable like the query generation."""
    if regen and path.exists():
        path.unlink()
    done = set()
    if path.exists():
        done = {(r["parent_id"], r["p"][0]) for r in read_jsonl(path)}
    todo = [
        (p, c)
        for p in parents.values()
        if p["n_tokens"] >= 50
        for c in pronoun_candidates(p["text"])
        if (p["id"], c["p"][0]) not in done
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for k, (p, c) in enumerate(todo, 1):
            try:
                answer = client.chat_json(COREF_PROMPT.format(context=c["context"]), COREF_SCHEMA)
                phrase = answer["antecedent"]
            except (ValueError, KeyError) as e:
                print(f"  reference resolution failed for {p['id']}: {e}")
                continue
            s = None
            if phrase.split():
                ante = re.compile(r"\s+".join(map(re.escape, phrase.split())), re.I)
                before = list(ante.finditer(p["text"], c["lo"], c["p"][0]))
                s = before[-1].start() if before else None
            rec = {
                "parent_id": p["id"],
                "source": p["source"],
                "p": c["p"],
                "s": s,
                "phrase": phrase,
            }
            f.write(json.dumps(rec) + "\n")
            f.flush()
            print(f"  resolved pronouns {k}/{len(todo)}", end="\r")
    return read_jsonl(path)


def reference_pairs(recs) -> list[dict]:
    """Entity-pronoun pairs: s = start of the antecedent, t = end of the pronoun."""
    pairs = [
        {"parent_id": r["parent_id"], "source": r["source"], "s": r["s"], "t": r["p"][1]}
        for r in recs
        if r["s"] is not None
    ]
    print(f"\nPronoun occurrences: {len(recs)}, resolved to an antecedent: {len(pairs)}")
    return pairs


def reference_completeness(children, pairs) -> dict:
    """RC = 1 - share of antecedent-pronoun pairs with a chunk boundary strictly between them."""
    by_parent = defaultdict(list)
    for c in children:
        by_parent[c["parent_id"]].append(c["span"])
    bounds = {
        pid: [s[0] for s in spans[1:]] + [s[1] for s in spans[:-1]]
        for pid, spans in by_parent.items()
    }
    broken = sum(any(p["s"] < b <= p["t"] for b in bounds.get(p["parent_id"], [])) for p in pairs)
    return {
        "RC↑": 1 - broken / len(pairs) if pairs else float("nan"),
        "ref_pairs": len(pairs),
    }


# --- F: MoC perplexity metrics ---------------------------------------------------------------


def moc_summary(docs: list[dict], group: str) -> dict:
    docs = [d for d in docs if group == "all" or d["source"] == group]
    bc = [v for d in docs for v in d["bc"]]
    nodes = sum(d["nodes"] for d in docs)
    return {
        "BC↑": nanmean(bc),
        "CS↓": nanmean([d["cs"] for d in docs]),
        "CS_norm↓": nanmean([d["cs_norm"] for d in docs]),
        "edges/node": sum(d["edges"] for d in docs) / nodes if nodes else float("nan"),
        "bc_pairs": len(bc),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chunks-dir", default="/workspace/data/chunks")
    ap.add_argument("--k", default="1,3,5,10")
    ap.add_argument("--size-min", type=int, default=50)
    ap.add_argument("--size-max", type=int, default=256)
    ap.add_argument("--questions-per-section", type=int, default=2)
    ap.add_argument("--min-sim", type=float, default=0.4, help="min question-excerpt cosine")
    ap.add_argument("--regen-queries", action="store_true")
    ap.add_argument("--no-retrieval", action="store_true")
    ap.add_argument("--no-coref", action="store_true", help="skip References Completeness")
    ap.add_argument("--no-lm", action="store_true", help="skip Boundary Clarity / Stickiness")
    ap.add_argument("--lm", default="Qwen/Qwen2.5-0.5B", help="causal LM for perplexities")
    ap.add_argument("--stickiness-window", type=int, default=5, help="0 = all chunk pairs")
    ap.add_argument("--stickiness-k", type=float, default=0.1, help="edge weight threshold K")
    args = ap.parse_args()
    chunks_dir = Path(args.chunks_dir)
    ks = [int(k) for k in args.k.split(",")]
    max_tokens = json.loads((chunks_dir / "manifest.json").read_text())["params"]["max_tokens"]
    strategies = [s for s, d in STRATEGY_DIRS.items() if (chunks_dir / d).is_dir()]
    client = OllamaClient()
    data = {s: load_strategy(chunks_dir, s) for s in strategies}
    groups = ["all", *sorted({c["source"] for c in data[strategies[0]][1]})]

    report: dict = {s: {g: {} for g in groups} for s in strategies}
    for s in strategies:
        parents, children = data[s]
        print(f"computing metrics for {s} ({len(children)} chunks)")
        cohesion, adjacent, dcc = embedding_features(children, client)
        for g in groups:
            mask = np.array([g == "all" or c["source"] == g for c in children])
            sub = [c for c, m in zip(children, mask, strict=True) if m]
            sub_parents = {pid: p for pid, p in parents.items() if g == "all" or p["source"] == g}
            report[s][g].update(
                shape_structure(sub, sub_parents, max_tokens, args.size_min, args.size_max)
            )
            report[s][g].update(embedding_metrics(cohesion, adjacent, dcc, mask, g))

    for title, keys in [
        (
            "A. Shape (tokens: bge-m3)",
            [
                "chunks",
                "mean_tok",
                "median_tok",
                "size_compl↑",
                "tiny↓",
                "utilisation",
                "single_child",
                "hdr_overhead",
                "dup↓",
            ],
        ),
        ("B. Structure", ["block_integ↑", "sent_end↑", "mid_start↓", "dangling↓"]),
        ("C. Embedding coherence (bge-m3)", ["ICC↑", "adjacent↓", "ICC-adj↑", "DCC↑"]),
    ]:
        rows = [
            [f"{s} [{g}]", *(report[s][g][k] for k in keys)] for g in groups for s in strategies
        ]
        print_table(title, ["strategy [source]", *keys], rows)

    extra_tables = []
    if not args.no_coref:
        parents = data[strategies[0]][0]
        recs = extract_references(
            client, parents, chunks_dir / "eval" / "coref.jsonl", args.regen_queries
        )
        pairs = reference_pairs(recs)
        for s in strategies:
            for g in groups:
                group_pairs = [p for p in pairs if g == "all" or p["source"] == g]
                children = [c for c in data[s][1] if g == "all" or c["source"] == g]
                report[s][g].update(reference_completeness(children, group_pairs))
        extra_tables.append(
            ("E. References Completeness (LLM-resolved pronouns)", ["RC↑", "ref_pairs"])
        )
    if not args.no_lm:
        from chunk_lm import LMScorer, moc_metrics

        scorer = LMScorer(args.lm)
        if scorer.device == "cpu":
            print(
                "note: no GPU, perplexity scoring runs on CPU and is slow "
                "(use --stickiness-window 1 or --no-lm)"
            )
        for s in strategies:
            print(f"scoring perplexities for {s}")
            docs = moc_metrics(data[s][1], scorer, args.stickiness_window, args.stickiness_k)
            for g in groups:
                report[s][g].update(moc_summary(docs, g))
        extra_tables.append(
            (
                f"F. MoC perplexity metrics ({args.lm}, window={args.stickiness_window}, "
                f"K={args.stickiness_k})",
                ["BC↑", "CS↓", "CS_norm↓", "edges/node", "bc_pairs"],
            )
        )
    for title, keys in extra_tables:
        rows = [
            [f"{s} [{g}]", *(report[s][g][k] for k in keys)] for g in groups for s in strategies
        ]
        print_table(title, ["strategy [source]", *keys], rows)

    if not args.no_retrieval:
        parents = data[strategies[0]][0]
        recs = generate_queries(
            client,
            parents,
            chunks_dir / "eval" / "queries.jsonl",
            args.questions_per_section,
            args.regen_queries,
        )
        queries = build_queries(client, parents, recs, args.min_sim)
        scores = {s: retrieval_scores(data[s][1], queries, client, ks) for s in strategies}
        for s in strategies:
            for g in groups:
                rows = [r for r in scores[s] if g == "all" or r["source"] == g]
                if rows:
                    report[s][g]["retrieval"] = {
                        k: float(np.mean([r[k] for r in rows])) for k in rows[0] if k != "source"
                    }
                    report[s][g]["retrieval"]["queries"] = len(rows)
        for g in groups:
            header = [
                "strategy",
                *(f"R@{k}" for k in ks),
                *(f"P@{k}" for k in ks),
                *(f"IoU@{k}" for k in ks),
                *(f"hit@{k}" for k in ks),
                "MRR",
            ]
            rows = []
            for s in strategies:
                m = report[s][g].get("retrieval")
                if m:
                    rows.append(
                        [
                            s,
                            *(m[f"recall@{k}"] for k in ks),
                            *(m[f"precision@{k}"] for k in ks),
                            *(m[f"iou@{k}"] for k in ks),
                            *(m[f"hit@{k}"] for k in ks),
                            m["mrr"],
                        ]
                    )
            n = report[strategies[0]][g].get("retrieval", {}).get("queries", 0)
            print_table(
                f"D. Retrieval [{g}] ({n} queries; hit = parent section found)",
                header,
                rows,
            )

    out = chunks_dir / "eval" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=float))
    print(f"\nWrote {out}")
    print(
        "Direction: ↑ higher is better, ↓ lower is better. Next (not computed): answer-level eval."
    )


if __name__ == "__main__":
    main()
