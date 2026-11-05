"""Write retrieval keys for expert units with a local model (docs/expert-knowledge.md, option D).

Usage: python scripts/elicitation/make_unit_keys.py --tier silver [--model qwen3.5:9b] [--limit N]

For every unit of every document in data/fixtures/<source>/<tier>/documents, one JSON-mode call
returns {reading_rule, questions, traits, direction}. The keys are only embedded and searched; the
unit's own verbatim text is what reaches the answer generator, so a bad key costs recall, not
faithfulness.
A reply that is not valid or leaks a name from the vignette is retried with a new seed.
Writes data/expert_units/<source>/<tier>/<session>.json (units + keys); a cache makes reruns free.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from chips_schema import load_document
from llm_clients import CachedGenerator, GenRequest, ModelRefused, OllamaGenerator
from make_fixtures import PERSONAS, Rejected, fixture_dir, parse_json, write_json
from prompt_loader import load_prompt

from app.elicitation.units import ExpertUnit, build_units, render_unit

ROOT = Path(__file__).resolve().parents[2]
PROMPT = "Expert_unit_keys.v1"
OPTIONS = {"temperature": 0.3, "num_predict": 500, "num_ctx": 8192}
DIRECTIONS = {"raises", "lowers", "neutral"}


def role_for(
    tier: str, session_id: str, expert_id: str | None = None, source: str = "synthetic"
) -> str | None:
    """Short role line for the header: silver, from the persona that wrote document N (C1, C2);
    gold, from the role the expert gave in data/fixtures/<source>/gold/experts.json."""
    if tier == "gold":
        path = fixture_dir("gold", source) / "experts.json"
        return json.loads(path.read_text()).get(expert_id) if path.exists() else None
    personas = PERSONAS.get(tier)
    index = int(session_id.rsplit("-", 1)[1]) - 1
    if not personas or not 0 <= index < len(personas):
        return None
    return ", ".join(personas[index][1].split(";")[0].split(",")[:2])


def load_units(
    tier: str, fixtures: Path = ROOT / "data/fixtures", source: str = "synthetic", **context
) -> list[ExpertUnit]:
    """Units of every document of a tier; `context` is passed to build_units (lean contexts)."""
    units: list[ExpertUnit] = []
    for path in sorted(
        fixture_dir(tier, source, fixtures).joinpath("documents").glob("DOC-*.json")
    ):
        doc = load_document(path)
        role = role_for(tier, doc.session_id, doc.expert_id, source)
        units += build_units(doc, role, **context)
    return units


def vignette_names(text: str) -> set[str]:
    """Capitalised words that do not start a sentence: the names a general rule must not carry."""
    words = re.findall(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]+\b", text)
    return {w for w in words if w != "I"}


def check_keys(raw: str, names: set[str]) -> dict:
    data = parse_json(raw)
    rule = data.get("reading_rule")
    questions = data.get("questions")
    if not isinstance(rule, str) or not rule.strip():
        raise Rejected("no reading_rule")
    if not isinstance(questions, list) or not 2 <= len(questions) <= 3:
        raise Rejected("questions must be a list of 2-3")
    if not all(isinstance(q, str) and q.strip() for q in questions):
        raise Rejected("blank question")
    traits = data.get("traits", [])
    if not isinstance(traits, list) or not all(isinstance(t, str) for t in traits):
        raise Rejected("traits must be a list of strings")
    if data.get("direction") not in DIRECTIONS:
        raise Rejected(f"direction {data.get('direction')!r}")
    leaked = sorted(n for n in names if re.search(rf"\b{n}\b", " ".join([rule, *questions])))
    if leaked:
        raise Rejected(f"names from the vignette in the keys: {leaked}")
    return {
        "reading_rule": rule.strip(),
        "questions": [q.strip() for q in questions],
        "traits": traits,
        "direction": data["direction"],
    }


def make_keys(unit: ExpertUnit, vignette: str, by_id, gen, retries: int, seed: int) -> dict:
    prompt = load_prompt(PROMPT).fill(VIGNETTE_TEXT=vignette, UNIT=render_unit(unit, by_id))
    names = vignette_names(vignette)
    result = {"keys": None, "attempts": 0, "name_leak_first_try": False}
    for attempt in range(retries + 1):
        req = GenRequest(
            key=f"keys:{unit.unit_id}",
            system=prompt.system,
            user=prompt.user,
            json_mode=True,
            seed=seed + attempt * 7919,
            options=OPTIONS,
        )
        result["attempts"] = attempt + 1
        try:
            result["keys"] = check_keys(gen.generate(req), names)
            return result
        except (Rejected, ModelRefused) as e:
            result["name_leak_first_try"] |= attempt == 0 and "names from" in str(e)
            print(f"  rejected {unit.unit_id} (attempt {attempt + 1}): {e}", file=sys.stderr)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier", required=True, choices=["bronze", "silver", "gold"])
    ap.add_argument("--source", default="synthetic", choices=["synthetic", "reddit", "chips"])
    ap.add_argument("--fixtures", type=Path, default=ROOT / "data/fixtures")
    ap.add_argument("--out", type=Path, default=ROOT / "data/expert_units")
    ap.add_argument("--cache", type=Path, default=ROOT / "data/cache")
    ap.add_argument(
        "--base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--limit", type=int, help="only the first N units (smoke test)")
    args = ap.parse_args(argv)

    gen = CachedGenerator(OllamaGenerator(args.base_url, args.model), args.cache)
    units = load_units(args.tier, args.fixtures, args.source)[: args.limit]
    by_id = {u.unit_id: u for u in units}
    vignettes = {}
    for path in (fixture_dir(args.tier, args.source, args.fixtures) / "documents").glob(
        "DOC-*.json"
    ):
        doc = load_document(path)
        vignettes |= {(doc.session_id, v.id): v.text for v in doc.vignettes}

    results = {}
    for i, unit in enumerate(units, 1):
        print(f"[{i}/{len(units)}] {unit.unit_id}", file=sys.stderr)
        text = vignettes[(unit.session_id, unit.vignette_id)]
        results[unit.unit_id] = make_keys(unit, text, by_id, gen, args.retries, args.seed)

    for session in sorted({u.session_id for u in units}):
        write_json(
            args.out / args.source / args.tier / f"{session}.json",
            {
                "model": gen.name,
                "prompt": PROMPT,
                "units": [u.model_dump() for u in units if u.session_id == session],
                "keys": {k: v for k, v in results.items() if k.startswith(session)},
            },
        )
    failed = [k for k, v in results.items() if v["keys"] is None]
    leaks = sum(v["name_leak_first_try"] for v in results.values())
    print(
        f"{len(units)} units, {len(failed)} without keys, name-leak rate {leaks / len(units):.1%}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
