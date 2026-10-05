"""Chunk the parsed Wikipedia + PDF documents with three strategies, for later vector-DB ingestion.

All strategies share one parent layer (document sections) and differ only in how a section is split
into child chunks: Docling's HybridChunker, recursive splitting (semchunk) or semantic splitting
(bge-m3 sentence-embedding breakpoints). Output: data/chunks/<strategy>/<doc>.jsonl + manifest.json.

Usage: python scripts/chunk_documents.py [--strategies hybrid,recursive,semantic]
           [--max-tokens 256] [--breakpoint-percentile 95] [--out data/chunks]
Needs Ollama with bge-m3 for the semantic strategy.
"""

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
import semchunk
from chunk_common import (
    STRATEGY_DIRS,
    OllamaClient,
    count_tokens,
    hf_tokenizer,
    split_sentences,
    write_jsonl,
)
from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc import DocItemLabel, DoclingDocument

RAW_DIR = Path("/workspace/data/raw")
MIN_TOKENS = 32  # semantic chunks below this are merged into a neighbour
# Front/back matter and boilerplate headings (case-insensitive prefix match); extends the
# SKIP_SECTIONS idea from scrape_wikipedia.py for the PDF papers.
SKIP_HEADINGS = (
    "references",
    "bibliography",
    "author contributions",
    "funding",
    "conflict of interest",
    "conflicts of interest",
    "declaration of conflicting interests",
    "publisher's note",
    "acknowledg",
    "supplementary material",
    "supplemental material",
    "data availability",
    "ethics statement",
    "open access",
    "citation",
    "copyright",
    "check for updates",
)


def wiki_to_doc(name: str, sections: list[dict]) -> tuple[DoclingDocument, dict[str, str]]:
    """Rebuild a DoclingDocument from the section JSON written by scrape_wikipedia.py."""
    doc = DoclingDocument(name=name)
    doc.add_title(sections[0]["title"])
    urls: dict[str, str] = {}
    for s in sections:
        if s["level"]:
            doc.add_heading(s["section"], level=len(s["level"]) - 1)
        urls.setdefault(s["section"], s["url"])
        for block in s["text"].split("\n\n"):
            lines = block.splitlines()
            if lines and all(line.startswith("- ") for line in lines):
                group = doc.add_list_group()
                for line in lines:
                    doc.add_list_item(line[2:], parent=group)
            else:
                doc.add_text(DocItemLabel.PARAGRAPH, block)
    return doc, urls


def load_documents() -> list[tuple[str, str, DoclingDocument, dict[str, str]]]:
    """(name, source, document, section urls) for every wiki JSON and parsed PDF."""
    docs = []
    for path in sorted(RAW_DIR.glob("*.json")):
        doc, urls = wiki_to_doc(path.stem, json.loads(path.read_text()))
        docs.append((path.stem, "wiki", doc, urls))
    for path in sorted((RAW_DIR / "pdf_parsed").glob("*.docling.json")):
        name = path.name.removesuffix(".docling.json")
        docs.append((name, "pdf", DoclingDocument.load_from_json(path), {}))
    return docs


def build_parents(name: str, source: str, doc: DoclingDocument, urls: dict[str, str]):
    """Group HierarchicalChunker elements by heading path into sections (the parent layer)."""
    groups: list[dict] = []
    kept = dropped = 0
    for ch in HierarchicalChunker().chunk(doc):
        headings = tuple(ch.meta.headings or ())
        tokens = count_tokens(ch.text)
        if (headings and headings[-1].lower().startswith(SKIP_HEADINGS)) or not ch.text.strip():
            dropped += tokens
            continue
        kept += tokens
        if groups and groups[-1]["headings"] == headings:
            groups[-1]["elements"].append(ch)
        else:
            groups.append({"headings": headings, "elements": [ch]})
    parents = []
    for i, g in enumerate(groups):
        parts = [c.text for c in g["elements"]]
        blocks, pos = [], 0
        for part in parts:
            blocks.append([pos, pos + len(part)])
            pos += len(part) + 1
        items = [item for c in g["elements"] for item in c.meta.doc_items]
        headings = g["headings"]
        parents.append(
            {
                "id": f"{name}::p{i}",
                "doc": name,
                "source": source,
                "kind": "parent",
                "parent_id": None,
                "headings": list(headings),
                "text": "\n".join(parts),
                "blocks": blocks,
                "pages": sorted({pv.page_no for item in items for pv in item.prov}),
                "url": urls.get(headings[-1] if len(headings) > 1 else "Lead") if urls else None,
                "refs": {item.self_ref for item in items},
            }
        )
    return parents, kept, dropped


def chunk_hybrid(doc, parents, max_tokens, **_) -> list[list[tuple[int, int]]]:
    tokenizer = HuggingFaceTokenizer(tokenizer=hf_tokenizer(), max_tokens=max_tokens)
    # No repeated table headers, so every chunk stays a substring of its parent's text.
    chunker = HybridChunker(tokenizer=tokenizer, merge_peers=True, repeat_table_header=False)
    owner = {ref: i for i, p in enumerate(parents) for ref in p["refs"]}
    spans: list[list[tuple[int, int]]] = [[] for _ in parents]
    cursors = [0] * len(parents)
    fuzzy = missed = 0
    for ch in chunker.chunk(doc):
        i = owner.get(ch.meta.doc_items[0].self_ref)
        if i is None:  # chunk from a dropped section
            continue
        text = parents[i]["text"]
        start = text.find(ch.text, cursors[i])
        end = start + len(ch.text)
        if start < 0:
            # Merged items are joined with a different separator than the parent text.
            pattern = r"\s+".join(map(re.escape, ch.text.split()))
            m = re.compile(pattern).search(text, cursors[i])
            if not m:
                missed += 1
                continue
            start, end = m.span()
            fuzzy += 1
        cursors[i] = end
        spans[i].append((start, end))
    if fuzzy or missed:
        print(f"  note: {fuzzy} hybrid chunks matched ignoring whitespace, {missed} not located")
    return spans


def chunk_recursive(doc, parents, max_tokens, **_) -> list[list[tuple[int, int]]]:
    chunker = semchunk.chunkerify(count_tokens, max_tokens)
    return [[tuple(o) for o in chunker(p["text"], offsets=True)[1]] for p in parents]


def merge_tiny(text, spans, max_tokens):
    out: list[tuple[int, int]] = []
    for span in spans:
        if out and (
            count_tokens(text[slice(*out[-1])]) < MIN_TOKENS
            or count_tokens(text[slice(*span)]) < MIN_TOKENS
        ):
            merged = (out[-1][0], span[1])
            if count_tokens(text[slice(*merged)]) <= max_tokens:
                out[-1] = merged
                continue
        out.append(span)
    return out


def chunk_semantic(
    doc, parents, max_tokens, client, percentile, **_
) -> list[list[tuple[int, int]]]:
    """Break between sentences whose (±1 sentence window) embedding distance is above the
    per-document percentile; split oversized groups recursively and merge tiny ones."""
    chunker = semchunk.chunkerify(count_tokens, max_tokens)
    sents = [split_sentences(p["text"]) for p in parents]
    windows = []
    for p, ss in zip(parents, sents, strict=True):
        for i in range(len(ss)):
            lo, hi = max(0, i - 1), min(len(ss) - 1, i + 1)
            windows.append(p["text"][ss[lo][0] : ss[hi][1]])
    vecs = client.embed(windows)
    distances, pos = [], 0
    for ss in sents:
        v = vecs[pos : pos + len(ss)]
        pos += len(ss)
        distances.append(1 - (v[:-1] * v[1:]).sum(axis=1))
    threshold = np.percentile(np.concatenate(distances), percentile)
    result = []
    for p, ss, d in zip(parents, sents, distances, strict=True):
        text = p["text"]
        bounds = [0, *(i + 1 for i, x in enumerate(d) if x > threshold), len(ss)]
        spans = []
        for a, b in zip(bounds, bounds[1:], strict=False):
            s, e = ss[a][0], ss[b - 1][1]
            if count_tokens(text[s:e]) > max_tokens:
                spans += [(s + x, s + y) for x, y in chunker(text[s:e], offsets=True)[1]]
            else:
                spans.append((s, e))
        result.append(merge_tiny(text, spans, max_tokens))
    return result


STRATEGIES = {"hybrid": chunk_hybrid, "recursive": chunk_recursive, "semantic": chunk_semantic}


def add_sizes(rec: dict) -> dict:
    path = " > ".join(rec["headings"])
    rec["contextualized"] = f"{path}\n{rec['text']}" if path else rec["text"]
    rec["n_tokens"] = count_tokens(rec["text"])
    rec["n_tokens_ctx"] = count_tokens(rec["contextualized"])
    rec["n_chars"] = len(rec["text"])
    return rec


def build_records(strategy, parents, spans):
    records = []
    for p, p_spans in zip(parents, spans, strict=True):
        parent = {k: v for k, v in p.items() if k != "refs"}
        records.append(add_sizes({**parent, "strategy": strategy, "span": [0, len(p["text"])]}))
        for j, (s, e) in enumerate(p_spans):
            records.append(
                add_sizes(
                    {
                        "id": f"{p['id']}::c{j}",
                        "doc": p["doc"],
                        "source": p["source"],
                        "strategy": strategy,
                        "kind": "child",
                        "parent_id": p["id"],
                        "headings": p["headings"],
                        "text": p["text"][s:e],
                        "span": [s, e],
                        "pages": p["pages"],
                        "url": p["url"],
                    }
                )
            )
    return records


def describe(values) -> list:
    a = np.asarray(values)
    return [
        len(a),
        f"{a.mean():.1f}",
        f"{statistics.median(a):.0f}",
        f"{np.percentile(a, 10):.0f}",
        f"{np.percentile(a, 90):.0f}",
        int(a.max()),
    ]


def print_table(rows: list[list]) -> None:
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print(
            "  "
            + "  ".join(
                str(c).ljust(w) if i == 0 else str(c).rjust(w)
                for i, (c, w) in enumerate(zip(r, widths, strict=True))
            )
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strategies", default="hybrid,recursive,semantic")
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--breakpoint-percentile", type=float, default=95)
    ap.add_argument("--out", default="/workspace/data/chunks")
    args = ap.parse_args()
    strategies = args.strategies.split(",")
    out = Path(args.out)
    client = OllamaClient() if "semantic" in strategies else None

    sizes = defaultdict(lambda: defaultdict(list))  # strategy -> metric -> values
    manifest = {"params": vars(args), "docs": {}}
    for name, source, doc, urls in load_documents():
        parents, kept, dropped = build_parents(name, source, doc, urls)
        manifest["docs"][name] = {
            "source": source,
            "parents": len(parents),
            "kept_tokens": kept,
            "dropped_tokens": dropped,
            "noise_share": round(dropped / (kept + dropped), 4),
        }
        print(f"{name}: {len(parents)} sections, {kept} tokens kept, {dropped} dropped as noise")
        for strategy in strategies:
            spans = STRATEGIES[strategy](
                doc=doc,
                parents=parents,
                max_tokens=args.max_tokens,
                client=client,
                percentile=args.breakpoint_percentile,
            )
            records = build_records(strategy, parents, spans)
            write_jsonl(out / STRATEGY_DIRS[strategy] / f"{name}.jsonl", records)
            children = [r for r in records if r["kind"] == "child"]
            sizes[strategy]["raw"] += [r["n_tokens"] for r in children]
            sizes[strategy]["ctx"] += [r["n_tokens_ctx"] for r in children]
            sizes[strategy]["per_parent"] += [len(s) for s in spans]
            print(f"  {strategy}: {len(children)} chunks")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    parent_tokens = [
        r["n_tokens"]
        for f in (out / STRATEGY_DIRS[strategies[0]]).glob("*.jsonl")
        for r in map(json.loads, f.read_text().splitlines())
        if r["kind"] == "parent"
    ]
    print(f"\nChunk sizes in bge-m3 tokens (max_tokens={args.max_tokens})")
    rows = [["", "n", "mean", "median", "p10", "p90", "max"]]
    rows.append(["parents (sections)", *describe(parent_tokens)])
    for strategy in strategies:
        rows.append([f"{strategy}: raw", *describe(sizes[strategy]["raw"])])
        rows.append([f"{strategy}: contextualized", *describe(sizes[strategy]["ctx"])])
    print_table(rows)
    print("\nChildren per parent")
    rows = [["", "mean", "median", "max", "% single"]]
    for strategy in strategies:
        v = np.asarray(sizes[strategy]["per_parent"])
        rows.append(
            [
                strategy,
                f"{v.mean():.1f}",
                f"{np.median(v):.0f}",
                v.max(),
                f"{(v == 1).mean() * 100:.0f}",
            ]
        )
    print_table(rows)
    total_kept = sum(d["kept_tokens"] for d in manifest["docs"].values())
    total_dropped = sum(d["dropped_tokens"] for d in manifest["docs"].values())
    print(f"\nNoise filter dropped {total_dropped / (total_kept + total_dropped):.1%} of tokens")
    print(f"Wrote chunks to {out}/<strategy>/<doc>.jsonl (+ manifest.json)")


if __name__ == "__main__":
    main()
