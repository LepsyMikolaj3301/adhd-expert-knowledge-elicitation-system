"""Step 3 of docs/new-chips-knowledge.md: a local model files the sentences that carry no chip.

Usage:
    python scripts/elicitation/classify_sentence_targets.py --tier silver --model qwen3.5:9b
    python scripts/elicitation/classify_sentence_targets.py --tier silver --model qwen3.6:35b-a3b
    python scripts/elicitation/classify_sentence_targets.py --tier silver --model qwen3.5:9b \
        --masked-eval        # accuracy proxy: chips hidden, the classifier must find them again
    (35b: set OLLAMA_REQUEST_TIMEOUT=1800, a cold load takes about 13 minutes)

One JSON-mode call per response (prompt Expert_sentence_targets.v1): the numbered vignette, the
highlights with ids, every sentence of the expert's answers (known targets shown), the ids still
open. The reply is ids only; code rejects unknown ids, missing sentences and a misplaced `prev`, and
asks again with a new seed. A sentence still wrong after the retries becomes `case` (counted).
Writes data/expert_units_chips/synthetic/<tier>/<tag>/labels/<session>.json.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import chip_findings as cf
from chips_schema import ChipDocument, ChipResponse, render_chips
from llm_clients import CachedGenerator, GenRequest, ModelRefused, OllamaGenerator
from make_fixtures import Rejected, fixture_dir, parse_json, write_json
from prompt_loader import load_prompt

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "data/expert_units_chips/synthetic"
FIXTURES = ROOT / "data/fixtures_chips"
PROMPT = "Expert_sentence_targets.v1"
OPTIONS = {"temperature": 0.2, "num_predict": 600, "num_ctx": 8192}


def model_tag(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", model).strip("-")


def prompt_for(vignette: str, highlights: list[dict], sentences: list[dict], left: list[str]):
    numbered = "\n".join(
        f"[{n}] {vignette[a:b].strip()}" for n, (a, b) in enumerate(cf.split_sentences(vignette), 1)
    )
    marks = []
    for h in highlights:
        note = (
            "" if h["origin"] == "expert" else " (quoted in the answers, not marked as a highlight)"
        )
        marks.append(f'{h["id"]}: "{h["text"]}"{note}')
    lines = []
    for s in sentences:
        known = f" -> {', '.join(s['targets'])}" if s["targets"] else ""
        lines.append(f"{s['id']}{known}  {' '.join(s['text'].split())}")
    return load_prompt(PROMPT).fill(
        VIGNETTE=numbered, HIGHLIGHTS="\n".join(marks), SENTENCES="\n".join(lines),
        UNRESOLVED=", ".join(left),
    )  # fmt: skip


def check_labels(
    raw: str, sentences: list[dict], left: list[str], allowed: set[str]
) -> tuple[dict[str, list[str]], list[str]]:
    """(valid entries, errors). A valid entry is a non-empty list of allowed ids; `prev` alone and
    never for the first sentence of an answer."""
    data = parse_json(raw)
    first = {
        s["id"]
        for i, s in enumerate(sentences)
        if not i or sentences[i - 1]["question_id"] != s["question_id"]
    }
    good, errors = {}, []
    for sid in left:
        value = data.get(sid)
        if not isinstance(value, list) or not value or not all(isinstance(x, str) for x in value):
            errors.append(f"{sid}: missing or not a list of ids")
            continue
        ids = [x.strip().lower() for x in value]
        unknown = [x for x in ids if x not in allowed]
        if unknown:
            errors.append(f"{sid}: unknown ids {unknown}")
        elif "prev" in ids and (len(ids) > 1 or sid in first):
            errors.append(f"{sid}: 'prev' must be alone and not on the first sentence")
        else:
            good[sid] = list(dict.fromkeys(ids))
    return good, errors


def classify(
    gen, resp: ChipResponse, vignette: str, retries: int, seed: int = 1
) -> tuple[list[dict], list[dict], dict]:
    """Assign, classify the rest, apply. Returns (highlights, sentences, info)."""
    highlights, sentences = cf.assign(resp, vignette)
    left = cf.unresolved(sentences)
    info = {"left": left, "attempts": 0, "errors": [], "fallback": []}
    labels: dict[str, list[str]] = {}
    if left:
        allowed = {h["id"] for h in highlights} | {cf.CASE, "prev"}
        p = prompt_for(vignette, highlights, sentences, left)
        for attempt in range(retries + 1):
            req = GenRequest(
                key=f"targets:{resp.vignette_id}", system=p.system, user=p.user, json_mode=True,
                seed=seed + attempt * 7919, options=OPTIONS,
            )  # fmt: skip
            info["attempts"] = attempt + 1
            try:
                good, errors = check_labels(gen.generate(req), sentences, left, allowed)
            except (Rejected, ModelRefused) as e:
                good, errors = {}, [str(e)]
            if len(good) > len(labels):
                labels = good
            info["errors"] = errors
            if not errors:
                break
    info["fallback"] = cf.apply_classification(sentences, labels)
    info["labels"] = labels
    return highlights, sentences, info


def documents(tier: str, fixtures: Path):
    for path in sorted(
        fixture_dir(tier, "synthetic", fixtures).joinpath("documents").glob("DOC-*.json")
    ):
        yield ChipDocument.model_validate_json(path.read_text())


def masked_eval(gen, doc: ChipDocument, retries: int) -> list[dict]:
    """Rows (one per chip-assigned sentence): truth targets vs what the classifier says when the
    chips are hidden ('that'). A proxy: sentences with chips may differ from those without."""
    vignettes = {v.id: v.text for v in doc.vignettes}
    rows = []
    for resp in doc.responses:
        text = vignettes[resp.vignette_id]
        _, truth = cf.assign(resp, text)
        masked = resp.model_copy(
            update={
                "answers": {
                    q: render_chips(a, resp.highlights, "mask") for q, a in resp.answers.items()
                }
            }
        )
        _, pred, info = classify(gen, masked, text, retries)
        if [s["id"] for s in truth] != [s["id"] for s in pred]:
            print(
                f"  {resp.vignette_id}: sentence split differs after masking, skipped",
                file=sys.stderr,
            )
            continue
        for t, p in zip(truth, pred, strict=True):
            if t["assigned_by"] == "chip":
                row = dict(session=doc.session_id, vignette=resp.vignette_id, sentence=t["id"])
                row |= dict(truth=t["targets"], pred=p["targets"])
                row["fallback"] = t["id"] in info["fallback"]
                rows.append(row)
    return rows


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    exact = sum(set(r["truth"]) == set(r["pred"]) for r in rows)
    hit = sum(bool(set(r["truth"]) & set(r["pred"])) for r in rows)
    case_only = sum(r["pred"] == [cf.CASE] for r in rows)
    extra = sum(bool(set(r["pred"]) - set(r["truth"]) - {cf.CASE}) for r in rows)
    fallback = sum(r["fallback"] for r in rows) / n
    return {"n": n, "exact": exact / n, "overlap": hit / n, "predicted_case_only": case_only / n,
            "extra_wrong_highlight": extra / n, "fallback": fallback}  # fmt: skip


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier", required=True, choices=["bronze", "silver"])
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--tag", help="default: derived from the model")
    ap.add_argument(
        "--base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    ap.add_argument("--fixtures", type=Path, default=FIXTURES)
    ap.add_argument("--out", type=Path, default=UNITS)
    ap.add_argument("--cache", type=Path, default=ROOT / "data/cache")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--masked-eval", action="store_true")
    ap.add_argument("--limit", type=int, help="only the first N responses per document")
    args = ap.parse_args(argv)

    tag = args.tag or model_tag(args.model)
    gen = CachedGenerator(OllamaGenerator(args.base_url, args.model), args.cache)
    folder = args.out / args.tier / tag
    all_rows, totals = [], {"responses": 0, "left": 0, "fallback": 0, "retried": 0}
    for doc in documents(args.tier, args.fixtures):
        if args.limit:
            doc = doc.model_copy(update={"responses": doc.responses[: args.limit]})
        if args.masked_eval:
            all_rows += masked_eval(gen, doc, args.retries)
            continue
        vignettes = {v.id: v.text for v in doc.vignettes}
        out = {"model": args.model, "prompt": PROMPT, "responses": {}}
        for resp in doc.responses:
            _, _, info = classify(gen, resp, vignettes[resp.vignette_id], args.retries)
            out["responses"][resp.vignette_id] = info
            totals["responses"] += 1
            totals["left"] += len(info["left"])
            totals["fallback"] += len(info["fallback"])
            totals["retried"] += info["attempts"] > 1
            note = f"{len(info['left'])} to file, {info['attempts']} call(s)"
            print(
                f"{doc.session_id} {resp.vignette_id}: {note}, {len(info['fallback'])} fallback",
                file=sys.stderr,
            )
        write_json(folder / "labels" / f"{doc.session_id}.json", out)
    if args.masked_eval:
        summary = summarise(all_rows)
        write_json(
            folder / "masked_eval.json", {"model": args.model, "summary": summary, "rows": all_rows}
        )
        print(json.dumps(summary, indent=1))
        return 0
    print(f"{args.tier}/{tag}: {totals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
