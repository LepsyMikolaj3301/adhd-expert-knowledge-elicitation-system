# ruff: noqa: E501  (long docstring and strings)
"""All answers of the scale fixture in one JSON file, outside the database (data/ is gitignored: keep
a copy somewhere else too).

Usage: python scripts/elicitation/export_scale_answers.py [--out data/exports/scale_answers.json]

Joins what make_scale_fixtures.py leaves in several folders: the raw documents (data/fixtures_chips_scale),
the proofread documents and their sidecars (data/fixtures_chips_scale_proofread), the reference claims, the
vignettes, and who wrote each expert (manifest `answer_models`, the persona files of experts 21-32).
One record per (expert, vignette) in `responses`: raw and proofread answers per question, highlights,
rating, claims and the proofread passes. Experts 1-2 are the silver documents (Claude subagents).
Reads only files; nothing here touches Postgres or the models.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import make_chip_fixtures as mcf
import make_scale_fixtures as msf
from make_fixtures import fixture_dir, write_json

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/exports/scale_answers.json"


def load(path: Path):
    return json.loads(path.read_text())


def writer(expert: int, manifest: dict) -> dict:
    """Who wrote an expert and with what prompt."""
    pid, persona = msf.ALL_PERSONAS[expert - 1]
    if expert <= 2:
        return {"model": "claude (silver, Claude Code subagents)", "prompt": mcf.ANSWER_PROMPT}
    model = manifest["answer_models"][f"SYN-{expert:03d}"]
    if expert in msf.PERSONA_EXPERTS:
        p = msf.load_persona(expert)
        return {
            "model": model, "prompt": msf.ANSWER_V5, "persona_file": f"expert_personas/E{expert}.v1",
            "role": p.meta["role"], "citation_habit": p.meta["citation"],
            "persona_system": p.system, "persona_writing": p.user,
        }  # fmt: skip
    return {
        "model": model, "prompt": mcf.ANSWER_PROMPT, "persona_id": pid, "persona": persona,
        "chip_habit": mcf.CHIP_HABITS.get(pid),
    }  # fmt: skip


def export(raw_root: Path, proofread_root: Path) -> dict:
    raw = fixture_dir(msf.TIER, "synthetic", raw_root)
    proof = fixture_dir(msf.TIER, "synthetic", proofread_root)
    manifest = load(raw / "manifest.json")
    vignettes = {p.stem: load(p) for p in sorted((raw / "vignettes").glob("V*.json"))}
    experts, responses = {}, []
    for path in sorted((raw / "documents").glob("DOC-SYN-*.json")):
        doc = load(path)
        number = int(doc["session_id"].rsplit("-", 1)[1])
        claims = load(raw / "claims" / f"{doc['session_id']}.claims.json")
        proofread_doc = load(proof / "documents" / path.name)
        sidecar = load(proof / "proofread" / path.name)
        proofread = {r["vignette_id"]: r for r in proofread_doc["responses"]}
        experts[f"SYN-{number:03d}"] = {"number": number, "session_id": doc["session_id"],
                                       **writer(number, manifest)}  # fmt: skip
        for r in doc["responses"]:
            vid = r["vignette_id"]
            passes = sidecar.get(vid, {})
            responses.append({
                "expert_id": doc["expert_id"], "session_id": doc["session_id"], "vignette_id": vid,
                "answers_raw": r["answers"],
                "answers_proofread": proofread[vid]["answers"],
                "highlights": r["highlights"], "rating": r["rating"],
                "insufficient_information": r["insufficient_information"],
                "claims": [c for c in claims if c["vignette_id"] == vid],
                "proofread": {
                    q: {"dropped": row["dropped"], "passes": row["passes"]} for q, row in passes.items()
                },
                "submitted_at": r["submitted_at"],
            })  # fmt: skip
    return {
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": "generated answers, not expert-reviewed",
        "sources": {"raw": str(raw_root), "proofread": str(proofread_root)},
        "proofread_by": manifest.get("proofread") or load(proof / "manifest.json").get("proofread"),
        "experts": experts,
        "vignettes": vignettes,
        "responses": responses,
    }  # fmt: skip


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--raw", type=Path, default=msf.OUT)
    ap.add_argument("--proofread", type=Path, default=msf.PROOFREAD_OUT)
    args = ap.parse_args(argv)
    data = export(args.raw, args.proofread)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.out, data)
    answers = sum(len(r["answers_raw"]) for r in data["responses"])
    print(
        f"wrote {args.out}: {len(data['experts'])} experts, {len(data['vignettes'])} vignettes, "
        f"{len(data['responses'])} responses, {answers} answers"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
