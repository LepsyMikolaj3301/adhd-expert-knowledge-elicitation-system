# ruff: noqa: E501  (report strings)
"""How differently the experts of the scale fixture write, before and after the proofreading.

Usage: python scripts/rag/eval_style_diversity.py --run-dir data/eval/style_diversity/<name> \
           [--raw data/fixtures_chips_scale/synthetic/silver] \
           [--proofread data/fixtures_chips_scale_proofread/synthetic/silver]

Needs the scale fixture (scripts/elicitation/make_scale_fixtures.py, stages answers and proofread) and
Ollama with bge-m3. Experts are grouped by the model that wrote them (manifest `answer_models`; experts
1-2 are Claude; qwen3.8 is split into the old one-line personas, 3-20, and the persona files, 31-32).

Per fixture (raw and proofread), on the anchor vignettes that every expert answered:
  similarity  mean pairwise cosine (bge-m3) of the experts' answers to one vignette, chips removed,
              within each group and between groups. Lower = the experts sound less alike
  stylometry  per expert: words per answer, words per sentence, chips per sentence, share of sentences
              with a chip, where the first chip stands (0 = start of the answer, 1 = end), type-token
              ratio, share of lines that are list items; per group mean and standard deviation over
              the experts
  drift       raw -> proofread, per group: cosine of an expert's raw and proofread answer, and the
              change of the between-expert similarity
Writes <run-dir>/results.json and report.md.
"""

import argparse
import json
import os
import re
import statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ANCHORS = ["V001", "V004", "V006", "V012"]
OPEN = ("Q1", "Q2", "Q3", "Q5")
CHIP = re.compile(r"⟦h\d+⟧")
LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
METRICS = [
    "words_per_answer", "words_per_sentence", "chips_per_sentence", "sentences_with_chip",
    "first_chip_position", "type_token_ratio", "list_lines",
]  # fmt: skip


def group_of(expert: int, answer_models: dict[str, str]) -> str:
    if expert <= 2:
        return "claude"
    model = answer_models.get(f"SYN-{expert:03d}", "qwen3.8:27b").split(":")[0]
    if model.startswith("qwen"):
        return "qwen3.8 (persona file)" if expert >= 21 else "qwen3.8 (one-line persona)"
    return model


def load(root: Path) -> tuple[dict[int, dict[str, dict[str, str]]], dict]:
    """{expert number: {vignette: {question: answer}}} and the manifest."""
    out: dict[int, dict[str, dict[str, str]]] = {}
    for path in sorted((root / "documents").glob("DOC-SYN-*.json")):
        doc = json.loads(path.read_text())
        number = int(doc["session_id"].rsplit("-", 1)[1])
        out[number] = {
            r["vignette_id"]: {q: r["answers"][q] for q in OPEN if q in r["answers"]}
            for r in doc["responses"]
        }
    return out, json.loads((root / "manifest.json").read_text())


def sentences(text: str) -> list[str]:
    return [s for s in SENTENCE.split(text) if s.strip()]


def stylometry(answers: list[str]) -> dict[str, float]:
    """The metrics over one expert's answers (the raw strings, chips included)."""
    words = [len(CHIP.sub("", a).split()) for a in answers]
    sents = [s for a in answers for s in sentences(a)]
    chipped = [s for s in sents if CHIP.search(s)]
    firsts = [m.start() / max(len(a), 1) for a in answers if (m := CHIP.search(a))]
    tokens = re.findall(r"[a-z']+", " ".join(CHIP.sub("", a) for a in answers).lower())
    lines = [ln for a in answers for ln in a.split("\n") if ln.strip()]
    return {
        "words_per_answer": statistics.mean(words),
        "words_per_sentence": statistics.mean(len(CHIP.sub("", s).split()) for s in sents),
        "chips_per_sentence": sum(len(CHIP.findall(s)) for s in sents) / len(sents),
        "sentences_with_chip": len(chipped) / len(sents),
        "first_chip_position": statistics.mean(firsts) if firsts else float("nan"),
        # over the first 300 words, so that a long writer does not look less varied
        "type_token_ratio": len(set(tokens[:300])) / max(len(tokens[:300]), 1),
        "list_lines": sum(bool(LIST_ITEM.match(ln)) for ln in lines) / len(lines),
    }


def plain(answers: dict[str, str]) -> str:
    """One text for the embedding: the questions' answers, chips and line breaks removed."""
    return re.sub(
        r"\s+", " ", " ".join(CHIP.sub("", answers[q]) for q in OPEN if q in answers)
    ).strip()


def unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def similarity(texts: dict[tuple[int, str], str], groups: dict[int, str], embed) -> dict:
    """Mean pairwise cosine per (group, group), anchors averaged. `texts[(expert, vignette)]`."""
    keys = sorted(texts)
    vectors = unit(np.array(embed([texts[k] for k in keys])))
    index = {k: i for i, k in enumerate(keys)}
    pairs: dict[tuple[str, str], list[float]] = defaultdict(list)
    for vid in ANCHORS:
        experts = sorted(e for e, v in keys if v == vid)
        for a, b in combinations(experts, 2):
            cos = float(vectors[index[(a, vid)]] @ vectors[index[(b, vid)]])
            pairs[tuple(sorted((groups[a], groups[b])))].append(cos)  # type: ignore[arg-type]
    every = [c for cs in pairs.values() for c in cs]
    return {
        "all": round(statistics.mean(every), 4),
        "pairs": {" x ".join(k): round(statistics.mean(v), 4) for k, v in sorted(pairs.items())},
        "counts": {" x ".join(k): len(v) for k, v in sorted(pairs.items())},
        "vectors": {f"{e}:{v}": vectors[i] for (e, v), i in index.items()},
    }


def analyse(root: Path, embed) -> dict:
    answers, manifest = load(root)
    models = manifest.get("answer_models", {})
    groups = {e: group_of(e, models) for e in answers}
    texts = {
        (e, v): plain(by_q) for e, vs in answers.items() for v, by_q in vs.items() if v in ANCHORS
    }
    sim = similarity(texts, groups, embed)
    per_expert = {}
    for e, vs in answers.items():
        mine = [a for by_q in vs.values() for a in by_q.values()]
        per_expert[e] = {"group": groups[e], **stylometry(mine)}
    by_group: dict[str, dict] = {}
    for g in sorted(set(groups.values())):
        members = [e for e in per_expert if groups[e] == g]
        by_group[g] = {"experts": members}
        for m in METRICS:
            vals = [per_expert[e][m] for e in members if not np.isnan(per_expert[e][m])]
            by_group[g][m] = (
                [round(statistics.mean(vals), 3), round(statistics.pstdev(vals), 3)]
                if vals
                else None
            )
    return {
        "root": str(root), "experts": len(answers), "groups": {str(e): g for e, g in groups.items()},
        "similarity": {k: v for k, v in sim.items() if k != "vectors"},
        "stylometry_by_group": by_group, "stylometry": {str(e): m for e, m in per_expert.items()},
        "_vectors": sim["vectors"], "_texts": {f"{e}:{v}": t for (e, v), t in texts.items()},
    }  # fmt: skip


def drift(raw: dict, proof: dict) -> dict:
    """Per group: cosine between an expert's raw and proofread answer, and the change in similarity."""
    by_group: dict[str, list[float]] = defaultdict(list)
    for key, a in raw["_vectors"].items():
        if key in proof["_vectors"]:
            by_group[raw["groups"][key.split(":")[0]]].append(float(a @ proof["_vectors"][key]))
    words = defaultdict(list)
    for e, m in raw["stylometry"].items():
        words[m["group"]].append(proof["stylometry"][e]["words_per_answer"] / m["words_per_answer"])
    return {
        "raw_vs_proofread_cosine": {g: round(statistics.mean(v), 4) for g, v in sorted(by_group.items())},
        "length_ratio": {g: round(statistics.mean(v), 3) for g, v in sorted(words.items())},
        "similarity_all": [raw["similarity"]["all"], proof["similarity"]["all"]],
    }  # fmt: skip


def report(data: dict, path: Path) -> None:
    out = ["# Style diversity of the scale fixture\n"]
    for label in ("raw", "proofread"):
        if label not in data:
            continue
        d = data[label]
        out.append(f"## {label}: {d['experts']} experts, anchors {', '.join(ANCHORS)}\n")
        out.append(
            f"Mean pairwise cosine of all expert pairs (same vignette): **{d['similarity']['all']}**\n"
        )
        out.append("| group pair | mean cosine | pairs |\n|---|---|---|")
        for k, v in d["similarity"]["pairs"].items():
            out.append(f"| {k} | {v} | {d['similarity']['counts'][k]} |")
        out.append("\nStylometry, per group: mean (sd over the experts of the group)\n")
        out.append("| group | n | " + " | ".join(METRICS) + " |\n|---|---|" + "---|" * len(METRICS))
        for g, row in d["stylometry_by_group"].items():
            cells = [f"{row[m][0]} ({row[m][1]})" if row[m] else "-" for m in METRICS]
            out.append(f"| {g} | {len(row['experts'])} | " + " | ".join(cells) + " |")
        out.append("")
    if "drift" in data:
        d = data["drift"]
        out.append("## raw -> proofread\n")
        out.append(
            f"All-pairs similarity: raw {d['similarity_all'][0]} -> proofread {d['similarity_all'][1]}\n"
        )
        out.append(
            "| group | cosine raw vs proofread answer | words proofread / raw |\n|---|---|---|"
        )
        for g, c in d["raw_vs_proofread_cosine"].items():
            out.append(f"| {g} | {c} | {d['length_ratio'].get(g)} |")
    path.write_text("\n".join(out) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--raw", type=Path, default=ROOT / "data/fixtures_chips_scale/synthetic/silver")
    ap.add_argument(
        "--proofread",
        type=Path,
        default=ROOT / "data/fixtures_chips_scale_proofread/synthetic/silver",
    )
    args = ap.parse_args()
    from expert_knowledge_rag import default_embeddings

    embeddings = default_embeddings(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    data: dict = {"raw": analyse(args.raw, embeddings.embed_documents)}
    if (args.proofread / "documents").is_dir():
        data["proofread"] = analyse(args.proofread, embeddings.embed_documents)
        data["drift"] = drift(data["raw"], data["proofread"])
    args.run_dir.mkdir(parents=True, exist_ok=True)
    report(data, args.run_dir / "report.md")
    for d in (data["raw"], data.get("proofread")):
        for key in ("_vectors", "_texts"):
            if d:
                d.pop(key, None)
    (args.run_dir / "results.json").write_text(json.dumps(data, indent=1))
    print(f"wrote {args.run_dir / 'report.md'}")


if __name__ == "__main__":
    main()
