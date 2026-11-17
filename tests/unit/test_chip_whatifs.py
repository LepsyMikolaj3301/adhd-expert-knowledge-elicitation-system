"""The what-ifs written for the chip vignettes (scripts/elicitation/chip_whatifs.json)."""

import json
from pathlib import Path

from app.vignettes.service import check_construct_words

ROOT = Path(__file__).resolve().parents[2]
WHATIFS = json.loads((ROOT / "scripts" / "elicitation" / "chip_whatifs.json").read_text())
FIXTURES = ROOT / "tests" / "fixtures" / "silver_chips" / "vignettes"


def test_every_what_if_is_a_plain_clause():
    for code, whatif in WHATIFS.items():
        assert whatif == whatif.strip() and whatif, code
        assert not whatif.endswith(("?", ".")), f"{code}: the question adds its own mark"
        assert len(whatif.split()) <= 25, f"{code}: one fact, not a paragraph"
        check_construct_words("", whatif)


def test_what_ifs_are_not_all_the_same():
    assert len(set(WHATIFS.values())) >= len(WHATIFS) - 1  # only the A/B pair shares one


def test_the_ab_pair_shares_a_what_if_that_does_not_leak_its_change():
    assert WHATIFS["V013"] == WHATIFS["V014"]
    for word in ("newborn", "baby", "broken nights"):
        assert word not in WHATIFS["V013"].lower()


def test_what_ifs_cover_exactly_the_committed_vignettes():
    assert set(WHATIFS) == {p.stem for p in FIXTURES.glob("V*.json")}
