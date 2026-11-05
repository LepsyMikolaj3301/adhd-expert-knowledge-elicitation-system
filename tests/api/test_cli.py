"""create-admin is the only way to get the first admin, so a bad one can't be fixed from the app."""

import asyncio
import json
from pathlib import Path

import pytest
from api_helpers import CUE, PASSWORD, VIGNETTE_TEXT, Api, admin_api, expert_api
from sqlalchemy import func, select

from app import cli
from app.audit.models import AuditEvent
from app.core.db import session_factory
from app.users.models import User
from app.vignettes.models import Vignette


async def _create_admin(monkeypatch, email: str, password: str = PASSWORD) -> int:
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: password)
    # In a thread: the command starts its own event loop.
    return await asyncio.to_thread(
        cli.main, ["create-admin", "--email", email, "--name", "First Admin"]
    )


async def _user_count() -> int:
    async with session_factory()() as db:
        return await db.scalar(select(func.count()).select_from(User))


async def test_the_created_admin_can_log_in(monkeypatch):
    assert await _create_admin(monkeypatch, "First.Admin@Example.COM") == 0
    me = await Api().ok(
        "POST", "/auth/login", json={"email": "first.admin@example.com", "password": PASSWORD}
    )
    assert me["role"] == "admin"


@pytest.mark.parametrize(
    "email", ["admin@clinic.local", "admin@localhost", "admin@corp.test", "not-an-email"]
)
async def test_an_email_the_login_would_refuse_creates_no_account(monkeypatch, capsys, email):
    assert await _create_admin(monkeypatch, email) == 1
    assert await _user_count() == 0
    assert "email" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("password", ["too short", "x" * 1025])
async def test_a_password_the_login_would_refuse_creates_no_account(monkeypatch, capsys, password):
    assert await _create_admin(monkeypatch, "admin@example.com", password) == 1
    assert await _user_count() == 0
    assert "password" in capsys.readouterr().err.lower()


ROOT = Path(__file__).resolve().parents[2]
CHIP_FIXTURES = ROOT / "data" / "fixtures_chips" / "synthetic" / "silver" / "vignettes"
CHIP_WHATIFS = ROOT / "scripts" / "elicitation" / "chip_whatifs.json"

# --- import-vignettes -----------------------------------------------------------------------


def _fixture_file(directory, code, **overrides):
    """A vignette file as the fixture builders write it, including fields the import ignores."""
    data = {
        "id": code,
        "version": 3,
        "text": VIGNETTE_TEXT,
        "framing": "forum_post",
        "question_ids": ["Q1", "Q2", "Q3", "Q5", "Q6"],
        "q4_whatif": None,
        "variant": None,
        "content_hash": "0" * 64,
        "design": {
            "purpose": f"purpose of {code}",
            "planted_cues": [{"quote": CUE, "trait": "task avoidance", "strength": "weak"}],
            "origin": "llm",
        },
    }
    data.update(overrides)
    (directory / f"{code}.json").write_text(json.dumps(data))


def _setup(tmp_path, codes=("V001", "V002"), whatifs=None):
    directory = tmp_path / "vignettes"
    directory.mkdir()
    for code in codes:
        _fixture_file(directory, code)
    whatifs = whatifs if whatifs is not None else {c: f"the writer did {c}" for c in codes}
    whatifs_file = tmp_path / "whatifs.json"
    whatifs_file.write_text(json.dumps(whatifs))
    return directory, whatifs_file


async def _import(directory, whatifs_file, email="admin@example.com") -> int:
    args = ["import-vignettes", "--dir", str(directory), "--whatifs", str(whatifs_file)]
    return await asyncio.to_thread(cli.main, [*args, "--admin-email", email])


async def _vignette_count() -> int:
    async with session_factory()() as db:
        return await db.scalar(select(func.count()).select_from(Vignette))


async def test_import_creates_drafts_that_ask_all_six_questions(tmp_path, capsys):
    admin = await admin_api()
    directory, whatifs_file = _setup(tmp_path)
    assert await _import(directory, whatifs_file) == 0
    listed = await admin.ok("GET", "/vignettes")
    assert [v["code"] for v in listed] == ["V001", "V002"]
    for vignette in listed:
        [version] = vignette["versions"]
        assert version["status"] == "draft"
        assert version["version"] == 1
        assert version["question_ids"] == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
        assert version["q4_whatif"] == f"the writer did {vignette['code']}"
        assert version["design"]["origin"] == "llm"
        assert version["text"] == VIGNETTE_TEXT
    async with session_factory()() as db:
        events = await db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "vignette_created")
        )
    assert events == 2
    assert "V001" in capsys.readouterr().out


async def test_importing_again_skips_what_already_exists(tmp_path, capsys):
    await admin_api()
    directory, whatifs_file = _setup(tmp_path)
    assert await _import(directory, whatifs_file) == 0
    capsys.readouterr()
    assert await _import(directory, whatifs_file) == 0
    assert await _vignette_count() == 2
    assert "skipped" in capsys.readouterr().out.lower()


async def test_one_bad_file_means_nothing_is_imported(tmp_path, capsys):
    await admin_api()
    directory, whatifs_file = _setup(tmp_path)
    bad_design = {
        "purpose": "x",
        "confounders": [{"quote": "not in text", "alternative_explanation": "y"}],
    }
    _fixture_file(directory, "V003", design=bad_design)
    whatifs = json.loads(whatifs_file.read_text()) | {"V003": "the writer did V003"}
    whatifs_file.write_text(json.dumps(whatifs))
    assert await _import(directory, whatifs_file) == 1
    assert await _vignette_count() == 0
    assert "V003" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("whatifs", "mentioned"),
    [
        ({"V001": "the writer did V001"}, "V002"),  # a vignette without a what-if
        ({"V001": "x", "V002": "  "}, "V002"),  # a blank one
        ({"V001": "x", "V002": "y", "V009": "z"}, "V009"),  # a what-if for no vignette
    ],
)
async def test_what_ifs_must_match_the_vignettes_exactly(tmp_path, capsys, whatifs, mentioned):
    await admin_api()
    directory, whatifs_file = _setup(tmp_path, whatifs=whatifs)
    assert await _import(directory, whatifs_file) == 1
    assert await _vignette_count() == 0
    assert mentioned in capsys.readouterr().err


async def test_only_an_active_admin_can_import(tmp_path, capsys):
    await admin_api()
    await expert_api("e@example.com")
    directory, whatifs_file = _setup(tmp_path)
    assert await _import(directory, whatifs_file, "e@example.com") == 1
    assert await _import(directory, whatifs_file, "nobody@example.com") == 1
    assert await _vignette_count() == 0
    assert "admin" in capsys.readouterr().err.lower()


async def test_a_missing_directory_or_whatif_file_is_reported(tmp_path, capsys):
    await admin_api()
    directory, whatifs_file = _setup(tmp_path)
    assert await _import(tmp_path / "nowhere", whatifs_file) == 1
    assert await _import(directory, tmp_path / "nowhere.json") == 1
    assert await _vignette_count() == 0
    assert capsys.readouterr().err


async def test_the_chip_vignettes_import_with_their_what_ifs(capsys):
    if not CHIP_FIXTURES.is_dir():
        pytest.skip("no data/fixtures_chips (gitignored)")
    admin = await admin_api()
    assert await _import(CHIP_FIXTURES, CHIP_WHATIFS) == 0, capsys.readouterr().err
    listed = await admin.ok("GET", "/vignettes")
    assert len(listed) == 14
    for vignette in listed:
        [version] = vignette["versions"]
        assert version["question_ids"] == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
        assert version["q4_whatif"]
    # The A/B pair keeps its design: the same what-if, and arm B still says what it changes.
    by_code = {v["code"]: v["versions"][0] for v in listed}
    assert by_code["V013"]["variant"]["arm"] == "A"
    assert by_code["V014"]["variant"]["change"]
    assert by_code["V013"]["q4_whatif"] == by_code["V014"]["q4_whatif"]
