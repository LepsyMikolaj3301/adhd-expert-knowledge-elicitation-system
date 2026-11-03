"""One-off: move the fixtures from the old Q4 (a quoted fragment) to the new Q4 (the author's
what-if, answered on a -2..+2 scale). Schema 1.0 -> 1.1. Idempotent.

Usage:
    python scripts/elicitation/migrate_q4_whatif.py --template  # -> data/fixtures/q4_whatifs.json
    # fill in "whatif" for the vignettes that should ask Q4 (blank = asked without Q4)
    python scripts/elicitation/migrate_q4_whatif.py --apply

--template lists every distinct vignette text that can get a what-if, keyed by content hash
(synthetic V001 and reddit V001 are different texts; gold copies share their silver entry). It keeps
what-ifs already written when run again. Synthetic bronze and tests/sample_inputs/personas are left
out: bronze stays on the v1 answer prompt, whose cached answers have no Q4 scale.

--apply, everywhere under data/fixtures/<source>/<tier>/ (and the sample personas):
  - vignettes and personas: drop q4_fragment; set q4_whatif from the template; Q4 is asked only
    with a what-if
  - documents: drop old Q4 answers (asked to a different question), Q4 and q4_fragment from the
    embedded vignettes; schema_version 1.1
  - claims: drop Q4 claims; unit keys (data/expert_units): drop Q4 units; gold drafts: drop Q4
  - regenerate data/fixtures/edge_cases/ and data/schemas/elicitation_document.schema.json
Every file is copied to data/backup/q4_v1/<path from the repo root> before its first change.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import export_schema
from make_fixtures import FIXTURES, ROOT, SOURCES, edge_cases, fixture_dir, write_json

from app.elicitation.questions import QUESTIONS
from app.elicitation.schema import (
    SCHEMA_VERSION,
    ElicitationDocument,
    ReferenceClaim,
    Vignette,
    content_hash,
)

TIERS = ("bronze", "silver", "gold")
TEMPLATE = FIXTURES / "q4_whatifs.json"
BACKUP = ROOT / "data/backup/q4_v1"
PERSONAS = ROOT / "tests/sample_inputs"
WITH_WHATIF = ("personas_silver",)  # sample persona folders whose texts can get a what-if


def eligible(source: str, tier: str) -> bool:
    """Vignettes that can ask Q4: not synthetic bronze (see the module docstring)."""
    return not (source == "synthetic" and tier == "bronze")


def tier_dirs():
    for source in SOURCES:
        for tier in TIERS:
            d = fixture_dir(tier, source)
            if d.is_dir():
                yield source, tier, d


def persona_files():
    for folder in sorted(PERSONAS.glob("personas*")):
        for path in sorted(folder.glob("persona.*.json")):
            yield folder.name, path


def save(path: Path, data) -> bool:
    """Write `data` if it differs from the file, backing the original up first. True if written."""
    if json.loads(path.read_text()) == data:
        return False
    backup = BACKUP / path.relative_to(ROOT)
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    write_json(path, data)
    return True


def with_q4(question_ids: list[str], ask: bool) -> list[str]:
    ids = set(question_ids) - {"Q4"} | ({"Q4"} if ask else set())
    return [q.id for q in QUESTIONS if q.id in ids]


# --- template ----------------------------------------------------------------------------------


def make_template() -> dict:
    old = json.loads(TEMPLATE.read_text())["vignettes"] if TEMPLATE.exists() else {}
    entries: dict[str, dict] = {}

    def add(h: str, where: str, text: str, design: dict) -> None:
        e = entries.setdefault(h, {
            "whatif": (old.get(h) or {}).get("whatif", ""),
            "used_in": [],
            "purpose": design.get("purpose"),
            "knowledge_target": design.get("knowledge_target"),
            "confounders": [c.get("alternative_explanation")
                            for c in design.get("confounders", [])],
            "text_start": text[:300],
        })  # fmt: skip
        e["used_in"].append(where)

    for source, tier, d in tier_dirs():
        if not eligible(source, tier):
            continue
        for path in sorted((d / "vignettes").glob("V*.json")):
            raw = json.loads(path.read_text())
            add(raw["content_hash"], f"{source}/{tier}/{raw['id']}", raw["text"], raw["design"])
    for folder, path in persona_files():
        if folder in WITH_WHATIF:
            raw = json.loads(path.read_text())
            text = str(raw.get("text", "")).strip()
            add(content_hash(text), f"tests/sample_inputs/{folder}/{path.name}", text, raw)
    return {
        "how": "Write one what-if per text: a clause that completes 'how would your hypothesis "
        "change if ...?', e.g. 'the writer had an exam earlier that day'. One concrete fact the "
        "text does not state, plausible for this writer, not a diagnosis. Leave blank to ask the "
        "vignette without Q4. Then run migrate_q4_whatif.py --apply.",
        "vignettes": entries,
    }


# --- apply -------------------------------------------------------------------------------------


def migrate_vignette(raw: dict, whatif: str | None) -> dict:
    raw = {k: v for k, v in raw.items() if k not in ("q4_fragment", "q4_whatif")}
    if whatif:
        raw["q4_whatif"] = whatif
    raw["question_ids"] = with_q4(raw["question_ids"], bool(whatif))
    Vignette.model_validate(raw)
    return raw


def migrate_document(raw: dict) -> dict:
    """1.0 -> 1.1. A 1.1 document is returned as it is: its Q4 answers are the new kind."""
    if raw.get("schema_version") == SCHEMA_VERSION:
        ElicitationDocument.model_validate(raw)
        return raw
    raw = json.loads(json.dumps(raw))
    raw["schema_version"] = SCHEMA_VERSION
    raw["vignettes"] = [migrate_vignette(v, None) for v in raw["vignettes"]]
    for r in raw["responses"]:
        r["answers"].pop("Q4", None)
        r.pop("q4", None)
    ElicitationDocument.model_validate(raw)
    return raw


def migrate_draft(draft: dict) -> dict:
    """Drop old-style Q4 answers (text with no scale answer); keep new ones (with `q4`)."""
    draft = json.loads(json.dumps(draft))
    for entry in draft["answers"].values():
        if "q4" not in entry:
            entry["answers"].pop("Q4", None)
    return draft


def apply() -> dict[str, int]:
    if not TEMPLATE.exists():
        raise SystemExit(f"{TEMPLATE.relative_to(ROOT)} is missing: run --template first")
    whatifs = {
        h: e["whatif"].strip()
        for h, e in json.loads(TEMPLATE.read_text())["vignettes"].items()
        if e.get("whatif", "").strip()
    }
    changed: dict[str, int] = {}

    def count(kind: str, written: bool) -> None:
        changed[kind] = changed.get(kind, 0) + written

    for source, tier, d in tier_dirs():
        for path in sorted((d / "vignettes").glob("V*.json")):
            raw = json.loads(path.read_text())
            whatif = whatifs.get(raw["content_hash"]) if eligible(source, tier) else None
            count("vignettes", save(path, migrate_vignette(raw, whatif)))
        for path in sorted((d / "documents").glob("DOC-*.json")):
            count("documents", save(path, migrate_document(json.loads(path.read_text()))))
        for path in sorted((d / "claims").glob("*.claims.json")):
            claims = [c for c in json.loads(path.read_text()) if c.get("question_id") != "Q4"]
            for c in claims:
                ReferenceClaim.model_validate(c)
            count("claims files", save(path, claims))
        for path in sorted((d / "drafts").glob("*.json")):
            count("drafts", save(path, migrate_draft(json.loads(path.read_text()))))
        for path in sorted((ROOT / "data/expert_units" / source / tier).glob("DOC-*.json")):
            raw = json.loads(path.read_text())
            raw["keys"] = {k: v for k, v in raw["keys"].items() if ":Q4:" not in k}
            raw["units"] = [u for u in raw["units"] if u["question_id"] != "Q4"]
            count("unit-key files", save(path, raw))
    for folder, path in persona_files():
        raw = json.loads(path.read_text())
        new = {k: v for k, v in raw.items() if k not in ("q4_fragment", "q4_whatif")}
        whatif = whatifs.get(content_hash(str(raw.get("text", "")).strip()))
        if folder in WITH_WHATIF and whatif:
            new["q4_whatif"] = whatif
        count("personas", save(path, new))
    for name, case in edge_cases().items():
        write_json(FIXTURES / "edge_cases" / f"{name}.json", case)
    export_schema.main()
    return changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--template", action="store_true", help="write the what-if template")
    mode.add_argument("--apply", action="store_true", help="migrate every fixture")
    args = ap.parse_args(argv)
    if args.template:
        template = make_template()
        write_json(TEMPLATE, template)
        filled = sum(bool(e["whatif"]) for e in template["vignettes"].values())
        print(f"wrote {TEMPLATE.relative_to(ROOT)}: {len(template['vignettes'])} texts, "
              f"{filled} with a what-if")  # fmt: skip
        return 0
    changed = apply()
    print("migrated: " + ", ".join(f"{n} {k}" for k, n in changed.items()))
    print(f"originals in {BACKUP.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
