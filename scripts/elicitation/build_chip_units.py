"""Chip documents + classifier labels -> fragment/case units, cue keys and their embeddings.

Usage:
    python scripts/elicitation/build_chip_units.py --tier silver --classifier qwen3.5:9b
    python scripts/elicitation/build_chip_units.py --tier silver --classifier qwen3.6:35b-a3b
    python scripts/elicitation/build_chip_units.py --tier bronze --classifier qwen3.5:9b --no-embed

Runs steps 2 to 7 of notes/new-chips-knowledge.md (chip_findings.py) on every response, using the
labels classify_sentence_targets.py wrote for the sentences without a chip. Then embeds with bge-m3
in the order of the doc: I1 (unit text), I2 (cue keys: the patient's words, shared across experts).
Writes, in data/expert_units_chips/synthetic/<tier>/<tag>/:
    units.json       records (highlights, sentences, units, flags), cue_keys, unit_cues, events
    embeddings.npz   i1, i2 (float32, one row per unit / cue key, same order as units.json)
Review (step 5) has no screen here: flags are logged as `flag_shown`, the review as `skipped`, and
toggles and groupings stay as the expert wrote them.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import chip_findings as cf
import numpy as np
from classify_sentence_targets import FIXTURES, PROMPT, UNITS, documents, model_tag
from make_fixtures import write_json
from make_unit_keys import role_for

from app.indexing import build_embedder, load_indexing_config

ROOT = Path(__file__).resolve().parents[2]


def build_tier(tier: str, tag: str, model: str, fixtures: Path, out: Path) -> dict:
    labels_dir = out / tier / tag / "labels"
    records, cue_index, cue_keys, unit_cues, events = [], {}, [], [], []
    for doc in documents(tier, fixtures):
        labels_path = labels_dir / f"{doc.session_id}.json"
        if not labels_path.exists():
            raise SystemExit(f"{labels_path} is missing: run classify_sentence_targets.py first")
        saved = json.loads(labels_path.read_text())["responses"]
        vignettes = {v.id: v for v in doc.vignettes}
        role = role_for(tier, doc.session_id, doc.expert_id)
        for resp in doc.responses:
            v = vignettes[resp.vignette_id]
            info = saved[resp.vignette_id]
            rec = cf.build_record(
                resp, v.text, doc.session_id, doc.expert_id, role, v.framing,
                v.design.population, info["labels"],
            )  # fmt: skip
            rec |= dict(track=v.design.track, origin=v.design.origin)
            records.append(rec)
            at = resp.submitted_at.isoformat()
            events += [
                dict(
                    session_id=doc.session_id, vignette_id=v.id, kind="flag_shown", payload=f, at=at
                )
                for f in rec["flags"]
            ]
            events.append(
                dict(session_id=doc.session_id, vignette_id=v.id, kind="skipped",
                     payload={"reason": "no review screen in the synthetic test"}, at=at)
            )  # fmt: skip
            cue_of = {}
            for h in rec["highlights"]:
                key = (v.id, v.version, tuple(h["span"]))
                if key not in cue_index:
                    cue_index[key] = len(cue_keys)
                    cue_keys.append(
                        dict(id=len(cue_keys), vignette_id=v.id, vignette_version=v.version,
                             span=list(h["span"]), text=h["text"])
                    )  # fmt: skip
                cue_of[h["id"]] = cue_index[key]
            for u in rec["units"]:
                if u["highlight"]:
                    unit_cues.append(dict(unit=u["id"], cue_key=cue_of[u["highlight"]], role="cue"))
                unit_cues += [
                    dict(unit=u["id"], cue_key=cue_of[c], role="context") for c in u["context"]
                ]
    units = [u for r in records for u in r["units"]]
    sentences = [s for r in records for s in r["sentences"]]
    stats = dict(
        responses=len(records), units=len(units), cue_keys=len(cue_keys),
        sentences=len(sentences), assigned_by=dict(Counter(s["assigned_by"] for s in sentences)),
        fallback=sum(len(r["fallback"]) for r in records),
        implicit_highlights=sum(
            h["origin"] == "implicit" for r in records for h in r["highlights"]
        ),
        flags=dict(Counter(f["kind"] for r in records for f in r["flags"])),
        case_units=sum(u["kind"] == "case" for u in units),
    )  # fmt: skip
    return dict(
        tier=tier, classifier=model, tag=tag, prompt=PROMPT, findings_version=cf.FINDINGS_VERSION,
        records=records, cue_keys=cue_keys, unit_cues=unit_cues, events=events, stats=stats,
    )  # fmt: skip


def embed_all(built: dict) -> dict[str, np.ndarray]:
    """I1, then I2 (the order of the doc)."""
    embedder = build_embedder(load_indexing_config(ROOT / "config/indexing.yaml"))
    units = [u for r in built["records"] for u in r["units"]]
    arrays = {}
    for name, texts in (
        ("i1", [u["i1"] for u in units]),
        ("i2", [k["text"] for k in built["cue_keys"]]),
    ):
        print(f"embedding {name}: {len(texts)} texts", file=sys.stderr)
        arrays[name] = np.asarray(embedder.embed(texts), dtype=np.float32)
    return arrays


def load_built(tier: str, tag: str, out: Path = UNITS) -> tuple[dict, dict[str, np.ndarray]]:
    folder = out / tier / tag
    built = json.loads((folder / "units.json").read_text())
    npz = np.load(folder / "embeddings.npz")
    return built, {k: npz[k] for k in npz.files}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier", required=True, choices=["bronze", "silver"])
    ap.add_argument("--classifier", default="qwen3.5:9b", help="the model whose labels to use")
    ap.add_argument("--tag", help="default: derived from the classifier")
    ap.add_argument("--fixtures", type=Path, default=FIXTURES)
    ap.add_argument("--out", type=Path, default=UNITS)
    ap.add_argument("--no-embed", action="store_true")
    args = ap.parse_args(argv)

    tag = args.tag or model_tag(args.classifier)
    built = build_tier(args.tier, tag, args.classifier, args.fixtures, args.out)
    folder = args.out / args.tier / tag
    write_json(folder / "units.json", built)
    if not args.no_embed:
        np.savez_compressed(folder / "embeddings.npz", allow_pickle=True, **embed_all(built))
    print(json.dumps(built["stats"], indent=1))
    print(f"wrote {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
