"""Fixtures for the elicitation tests: data/fixtures/synthetic/<tier>, or rebuild bronze offline.

data/ and tests/sample_inputs are gitignored. Without data/fixtures the bronze tier is rebuilt from
local sample inputs (tests/sample_inputs) with the `file` sources: no model, no network; without
either, the fixture tests are skipped.
Silver and gold tests are skipped until those tiers exist (see docs/fixtures.md).
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA_FIXTURES = ROOT / "data" / "fixtures" / "synthetic"  # edge_cases/ sits one level up
SAMPLES = ROOT / "tests" / "sample_inputs"
TIERS = ("bronze", "silver", "gold")


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory) -> Path:
    if any((DATA_FIXTURES / "bronze" / "documents").glob("DOC-SYN-*.json")):
        return DATA_FIXTURES
    if not (SAMPLES / "personas").is_dir():
        pytest.skip("no fixtures in data/ and no tests/sample_inputs (both gitignored)")
    import make_fixtures

    root = tmp_path_factory.mktemp("fixtures")
    out = root / "synthetic"
    code = make_fixtures.main(
        ["--persona-source", "file", "--answer-source", "file", "--tier", "bronze"]
        + ["--out", str(root), "--persona-dir", str(SAMPLES / "personas")]
        + ["--answer-dir", str(SAMPLES / "answers" / "bronze")]
    )
    assert code == 0
    return out


@pytest.fixture(params=TIERS)
def tier(request, fixtures_dir) -> str:
    if not (fixtures_dir / request.param / "documents").is_dir():
        pytest.skip(f"no {request.param} fixtures yet")
    return request.param


def _load(directory: Path, pattern: str) -> dict:
    return {
        p.name.split(".")[0]: json.loads(p.read_text()) for p in sorted(directory.glob(pattern))
    }


@pytest.fixture
def tier_dir(fixtures_dir, tier) -> Path:
    return fixtures_dir / tier


@pytest.fixture
def documents(tier_dir) -> dict[str, dict]:
    return _load(tier_dir / "documents", "DOC-*.json")


@pytest.fixture
def claims(tier_dir) -> dict[str, list[dict]]:
    return _load(tier_dir / "claims", "*.claims.json")


@pytest.fixture
def vignettes(tier_dir) -> dict[str, dict]:
    return _load(tier_dir / "vignettes", "V*.json")


@pytest.fixture(scope="session")
def edge_cases(fixtures_dir) -> dict[str, dict]:
    return _load(fixtures_dir.parent / "edge_cases", "*.json")
