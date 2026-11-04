"""create-admin is the only way to get the first admin, so a bad one can't be fixed from the app."""

import asyncio

import pytest
from api_helpers import PASSWORD, Api
from sqlalchemy import func, select

from app import cli
from app.core.db import session_factory
from app.users.models import User


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
