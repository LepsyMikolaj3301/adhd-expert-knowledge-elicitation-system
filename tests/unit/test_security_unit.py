"""Password hashing, tokens, the login lock and the session cookie, without a database."""

from datetime import timedelta

import pytest
from argon2 import PasswordHasher
from starlette.responses import Response

from app.auth import service
from app.core import security
from app.core.db import utcnow
from app.settings import settings


def test_a_password_verifies_only_against_its_own_hash():
    stored = security.hash_password("correct horse battery")
    assert security.verify_password(stored, "correct horse battery")
    assert not security.verify_password(stored, "wrong")
    assert security.hash_password("same") != security.hash_password("same")  # salted


@pytest.mark.parametrize("stored", [None, "", "not a hash", "$argon2id$broken"])
def test_an_unknown_account_or_a_broken_hash_never_verifies(stored):
    assert not security.verify_password(stored, "anything")


def test_a_hash_made_with_weaker_settings_needs_a_rehash_but_still_verifies():
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("pw")
    assert security.needs_rehash(weak) and security.verify_password(weak, "pw")
    assert not security.needs_rehash(security.hash_password("pw"))


def test_tokens_are_random_and_only_their_hash_is_comparable():
    a, b = security.new_token(), security.new_token()
    assert a != b and len(a) >= 40
    assert security.hash_token(a) == security.hash_token(a) != security.hash_token(b)
    assert len(security.hash_token(a)) == 64 and security.hash_token(a) != a


def test_a_content_hash_is_the_sha256_of_the_utf8_text():
    assert security.content_hash("é") == security.content_hash("é") != security.content_hash("e")
    assert len(security.content_hash("")) == 64


async def test_hashing_runs_off_the_event_loop_thread():
    import threading

    name = await security.run_hash(lambda: threading.current_thread().name)
    assert name.startswith("argon2")


@pytest.mark.parametrize(
    ("offset", "locked"),
    [(None, False), (timedelta(seconds=-1), False), (timedelta(minutes=5), True)],
)
def test_an_account_is_locked_until_its_time_has_passed(offset, locked):
    until = None if offset is None else utcnow() + offset  # now, not when the tests were collected
    assert service._is_locked(until) is locked


@pytest.mark.parametrize(
    ("secure", "environment", "flag"), [(False, "development", False), (True, "development", True)]
)
def test_the_session_cookie_is_http_only_and_secure_when_asked(
    monkeypatch, secure, environment, flag
):
    monkeypatch.setattr(settings, "cookie_secure", secure)
    monkeypatch.setattr(settings, "environment", environment)
    response = Response()
    service.set_session_cookie(response, "token-value")
    cookie = response.headers["set-cookie"]
    assert "token-value" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Path=/" in cookie and f"Max-Age={settings.session_ttl_hours * 3600}" in cookie
    assert ("Secure" in cookie) is flag


def test_production_always_sets_the_secure_flag(monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(settings, "environment", "production")
    response = Response()
    service.set_session_cookie(response, "t")
    assert "Secure" in response.headers["set-cookie"]
