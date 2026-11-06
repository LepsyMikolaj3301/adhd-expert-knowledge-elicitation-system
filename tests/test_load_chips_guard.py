"""The synthetic loader must never write into `chips`, which holds the app's approved answers."""

import sys
from pathlib import Path

import asyncpg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "db"))
import load_chips_pg  # noqa: E402  # ty: ignore[unresolved-import]


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """Whatever the loader does here, it must not reach a real database."""

    async def refuse(*args, **kwargs):
        raise AssertionError("the loader connected to a database")

    monkeypatch.setattr(asyncpg, "connect", refuse)


def test_loader_refuses_the_application_schema():
    with pytest.raises(SystemExit) as stop:
        load_chips_pg.main(["--tier", "silver", "--schema", "chips"])
    assert stop.value.code != 0


def test_loader_refuses_it_for_the_check_too():
    with pytest.raises(SystemExit):
        load_chips_pg.main(["--tier", "silver", "--schema", "chips", "--check"])


def test_loader_defaults_to_its_own_schema():
    args = load_chips_pg.parse_args(["--tier", "silver"])
    assert args.schema == "chips_eval"
