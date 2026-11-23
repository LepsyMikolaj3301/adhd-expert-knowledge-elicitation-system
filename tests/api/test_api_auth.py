import asyncio
import time
from datetime import timedelta

import pytest
from api_helpers import PASSWORD, Api, admin_api, expert_api
from sqlalchemy import select, update

from app.audit.models import AuditEvent
from app.auth import service as auth_service
from app.auth.models import AuthSession, Invite
from app.core.db import session_factory, utcnow
from app.main import app
from app.settings import settings
from app.users.models import User

# Reachable without logging in: everything else must answer 401.
PUBLIC = {
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/logout"),
    ("post", "/api/v1/auth/accept-invite"),
    ("post", "/api/v1/auth/check-invite"),
    ("get", "/api/v1/health"),
}
ID = "00000000-0000-0000-0000-000000000000"


def _routes():
    for path, methods in app.openapi()["paths"].items():
        for method in methods:
            yield method, path


async def test_every_non_public_route_requires_login():
    api = Api()
    for method, path in _routes():
        if (method, path) in PUBLIC:
            continue
        url = path.removeprefix("/api/v1")
        for name in ("assignment_id", "user_id", "version_id", "vignette_id"):
            url = url.replace(f"{{{name}}}", ID)
        await api.fails(method.upper(), url, 401, "not_authenticated", json={})
    await api.close()


ADMIN_ONLY = [
    ("GET", "/users"),
    ("POST", "/users"),
    ("PATCH", f"/users/{ID}"),
    ("POST", f"/users/{ID}/invite"),
    ("GET", "/vignettes"),
    ("POST", "/vignettes"),
    ("POST", f"/vignettes/{ID}/versions"),
    ("PATCH", f"/vignette-versions/{ID}"),
    ("POST", f"/vignette-versions/{ID}/publish"),
    ("POST", f"/vignette-versions/{ID}/retire"),
    ("POST", f"/vignette-versions/{ID}/assignments"),
    ("GET", "/knowledge-units"),
    ("POST", "/knowledge-units/search"),
    ("POST", f"/assignments/{ID}/retry"),
]


async def test_admin_only_routes_refuse_experts():
    expert = await expert_api("e@example.com")
    for method, path in ADMIN_ONLY:
        await expert.fails(method, path, 403, "forbidden", json={})


async def test_login_me_logout():
    expert = await expert_api("Case@Example.com")
    me = await expert.ok("GET", "/me")
    assert me["email"] == "case@example.com"
    assert "password_hash" not in me
    await expert.ok("POST", "/auth/logout", 204)
    await expert.fails("GET", "/me", 401, "not_authenticated")


async def test_session_cookie_flags_and_hashed_token():
    await expert_api("e@example.com")
    api = Api()
    response = await api.request(
        "POST", "/auth/login", json={"email": "e@example.com", "password": PASSWORD}
    )
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    token = response.cookies["session"]
    async with session_factory()() as db:
        stored = list(await db.scalars(select(AuthSession.token_hash)))
    assert token not in stored


async def test_wrong_password_and_unknown_email_look_the_same():
    await expert_api("e@example.com")
    api = Api()
    wrong = {"email": "e@example.com", "password": "nope"}
    unknown = {"email": "nobody@example.com", "password": "nope"}
    first = await api.fails("POST", "/auth/login", 401, "invalid_credentials", json=wrong)
    second = await api.fails("POST", "/auth/login", 401, "invalid_credentials", json=unknown)
    assert first == second


async def test_lockout_after_five_failures_then_recovery():
    await expert_api("e@example.com")
    api = Api()
    wrong = {"email": "e@example.com", "password": "nope"}
    right = {"email": "e@example.com", "password": PASSWORD}
    for _ in range(5):
        await api.fails("POST", "/auth/login", 401, "invalid_credentials", json=wrong)
    await api.fails("POST", "/auth/login", 401, "invalid_credentials", json=right)
    async with session_factory()() as db:
        await db.execute(update(User).values(locked_until=utcnow() - timedelta(seconds=1)))
        await db.commit()
    await api.ok("POST", "/auth/login", json=right)


async def test_expired_session_is_rejected():
    expert = await expert_api("e@example.com")
    async with session_factory()() as db:
        await db.execute(update(AuthSession).values(expires_at=utcnow() - timedelta(seconds=1)))
        await db.commit()
    await expert.fails("GET", "/me", 401, "not_authenticated")


async def test_invite_flow():
    admin = await admin_api()
    created = await admin.ok(
        "POST",
        "/users",
        201,
        json={"email": "new@example.com", "display_name": "New", "role": "expert"},
    )
    assert created["user"]["pseudonym"].startswith("E")
    token = created["invite_path"].removeprefix("/invite/")

    guest = Api()
    login = {"email": "new@example.com", "password": PASSWORD}
    await guest.fails("POST", "/auth/login", 401, "invalid_credentials", json=login)
    short = {"token": token, "password": "too-short"}
    await guest.fails("POST", "/auth/accept-invite", 422, "validation_error", json=short)
    accept = {"token": token, "password": PASSWORD}
    user = await guest.ok("POST", "/auth/accept-invite", json=accept)
    assert user["email"] == "new@example.com"
    assert (await guest.ok("GET", "/me"))["id"] == user["id"]

    other = Api()
    await other.fails("POST", "/auth/accept-invite", 400, "invalid_invite", json=accept)
    await other.ok("POST", "/auth/login", json=login)


async def test_checking_an_invite_says_whether_it_can_still_set_a_password():
    admin = await admin_api()
    created = await admin.ok(
        "POST",
        "/users",
        201,
        json={"email": "new@example.com", "display_name": "New", "role": "expert"},
    )
    first = created["invite_path"].removeprefix("/invite/")
    guest = Api()
    await guest.ok("POST", "/auth/check-invite", 204, json={"token": first})
    await guest.fails("POST", "/auth/check-invite", 400, "invalid_invite", json={"token": "nope"})

    # Re-issuing kills the first link; using the second kills it too.
    second = (await admin.ok("POST", f"/users/{created['user']['id']}/invite"))["invite_path"]
    second = second.removeprefix("/invite/")
    await guest.fails("POST", "/auth/check-invite", 400, "invalid_invite", json={"token": first})
    await guest.ok("POST", "/auth/check-invite", 204, json={"token": second})
    await guest.ok("POST", "/auth/accept-invite", json={"token": second, "password": PASSWORD})
    await Api().fails("POST", "/auth/check-invite", 400, "invalid_invite", json={"token": second})


async def test_checking_an_expired_or_deactivated_invite_fails():
    admin = await admin_api()
    created = await admin.ok(
        "POST",
        "/users",
        201,
        json={"email": "new@example.com", "display_name": "New", "role": "expert"},
    )
    token = {"token": created["invite_path"].removeprefix("/invite/")}
    await admin.ok("PATCH", f"/users/{created['user']['id']}", json={"is_active": False})
    await Api().fails("POST", "/auth/check-invite", 400, "invalid_invite", json=token)
    await admin.ok("PATCH", f"/users/{created['user']['id']}", json={"is_active": True})
    await Api().ok("POST", "/auth/check-invite", 204, json=token)
    async with session_factory()() as db:
        await db.execute(update(Invite).values(expires_at=utcnow() - timedelta(seconds=1)))
        await db.commit()
    await Api().fails("POST", "/auth/check-invite", 400, "invalid_invite", json=token)


async def test_reissued_invite_replaces_the_old_one_and_expiry_applies():
    admin = await admin_api()
    created = await admin.ok(
        "POST",
        "/users",
        201,
        json={"email": "new@example.com", "display_name": "New", "role": "expert"},
    )
    old = created["invite_path"].removeprefix("/invite/")
    new = (await admin.ok("POST", f"/users/{created['user']['id']}/invite"))["invite_path"]
    new = new.removeprefix("/invite/")
    guest = Api()
    await guest.fails(
        "POST",
        "/auth/accept-invite",
        400,
        "invalid_invite",
        json={"token": old, "password": PASSWORD},
    )
    async with session_factory()() as db:
        await db.execute(update(Invite).values(expires_at=utcnow() - timedelta(seconds=1)))
        await db.commit()
    await guest.fails(
        "POST",
        "/auth/accept-invite",
        400,
        "invalid_invite",
        json={"token": new, "password": PASSWORD},
    )


async def test_duplicate_email_is_a_conflict():
    admin = await admin_api()
    body = {"email": "Same@example.com", "display_name": "A", "role": "expert"}
    await admin.ok("POST", "/users", 201, json=body)
    await admin.fails("POST", "/users", 409, "email_taken", json=body)


async def test_a_bad_field_is_named_in_the_message():
    admin = await admin_api()
    body = {"email": "not-an-email", "display_name": "A", "role": "expert"}
    error = await admin.fails("POST", "/users", 422, "validation_error", json=body)
    assert error["message"].startswith("Email:")


async def test_deactivating_ends_sessions_and_blocks_login():
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    await admin.ok("PATCH", f"/users/{expert.user_id}", json={"is_active": False})
    await expert.fails("GET", "/me", 401, "not_authenticated")
    await expert.fails(
        "POST",
        "/auth/login",
        401,
        "invalid_credentials",
        json={"email": "e@example.com", "password": PASSWORD},
    )
    async with session_factory()() as db:
        assert (
            list(
                await db.scalars(
                    select(AuthSession.token_hash).where(AuthSession.user_id == expert.user_id)
                )
            )
            == []
        )


async def test_admin_cannot_deactivate_self():
    admin = await admin_api()
    await admin.fails(
        "PATCH",
        f"/users/{admin.user_id}",
        409,
        "cannot_deactivate_self",
        json={"is_active": False},
    )


async def test_a_slow_password_check_does_not_block_other_requests(monkeypatch):
    await expert_api("e@example.com")

    def slow(*_):
        time.sleep(0.5)
        return False

    monkeypatch.setattr(auth_service, "verify_password", slow)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    await Api().fails(
        "POST",
        "/auth/login",
        401,
        "invalid_credentials",
        json={"email": "e@example.com", "password": "wrong"},
    )
    task.cancel()
    # About 50 when the check runs off the loop, at most 2 when it blocks it: room for a slow box.
    assert ticks >= 5, "the event loop was blocked during the password check"


async def test_no_lock_is_held_during_the_password_check(monkeypatch):
    await expert_api("e@example.com")
    original = auth_service.run_hash
    checked = []

    async def checking_run_hash(function, *args):
        async with session_factory()() as other:
            # Raises if the login is holding the row.
            checked.append(
                await other.scalar(
                    select(User.id)
                    .where(User.email == "e@example.com")
                    .with_for_update(nowait=True)
                )
            )
            await other.rollback()
        return await original(function, *args)

    monkeypatch.setattr(auth_service, "run_hash", checking_run_hash)
    await Api().ok("POST", "/auth/login", json={"email": "e@example.com", "password": PASSWORD})
    assert checked


async def test_a_right_guess_fails_if_the_account_was_locked_during_the_check(monkeypatch):
    """Tries in flight all pass the first look, so the lock has to be checked again afterwards."""
    await expert_api("e@example.com")
    original = auth_service.run_hash

    async def locking_run_hash(function, *args):
        result = await original(function, *args)
        async with session_factory()() as other:
            await other.execute(update(User).values(locked_until=utcnow() + timedelta(minutes=5)))
            await other.commit()
        return result

    monkeypatch.setattr(auth_service, "run_hash", locking_run_hash)
    await Api().fails(
        "POST",
        "/auth/login",
        401,
        "invalid_credentials",
        json={"email": "e@example.com", "password": PASSWORD},
    )


async def test_invite_of_a_deactivated_user_is_refused():
    admin = await admin_api()
    created = await admin.ok(
        "POST",
        "/users",
        201,
        json={"email": "new@example.com", "display_name": "New", "role": "expert"},
    )
    await admin.ok("PATCH", f"/users/{created['user']['id']}", json={"is_active": False})
    await Api().fails(
        "POST",
        "/auth/accept-invite",
        400,
        "invalid_invite",
        json={"token": created["invite_path"].removeprefix("/invite/"), "password": PASSWORD},
    )


@pytest.mark.parametrize(
    ("environment", "cookie_secure", "expected"),
    [
        ("development", False, False),
        ("development", True, True),
        ("production", False, True),
    ],
)
async def test_the_session_cookie_is_https_only_in_production(
    monkeypatch, environment, cookie_secure, expected
):
    await expert_api("e@example.com")
    monkeypatch.setattr(settings, "environment", environment)
    monkeypatch.setattr(settings, "cookie_secure", cookie_secure)
    response = await Api().request(
        "POST", "/auth/login", json={"email": "e@example.com", "password": PASSWORD}
    )
    attributes = [part.strip().lower() for part in response.headers["set-cookie"].split(";")[1:]]
    assert ("secure" in attributes) is expected


async def test_privacy_notice_confirmation_is_recorded_and_shown_to_the_admin():
    expert = await expert_api("e@example.com")
    me = await expert.ok("GET", "/me")
    assert me["privacy_version"] is None
    assert me["privacy_accepted_at"] is None

    me = await expert.ok("POST", "/me/privacy", json={"version": "2026-11-23"})
    assert me["privacy_version"] == "2026-11-23"
    assert me["privacy_accepted_at"] is not None
    assert (await expert.ok("GET", "/me"))["privacy_version"] == "2026-11-23"

    admin = await admin_api()
    row = next(u for u in await admin.ok("GET", "/users") if u["email"] == "e@example.com")
    assert row["privacy_version"] == "2026-11-23"
    assert row["privacy_accepted_at"] == me["privacy_accepted_at"]

    async with session_factory()() as db:
        events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.action == "privacy_accepted"))
        )
    assert [e.meta for e in events] == [{"version": "2026-11-23"}]
    assert str(events[0].actor_id) == me["id"]


async def test_privacy_confirmation_needs_a_login_and_a_plain_version():
    expert = await expert_api("e@example.com")
    await expert.fails("POST", "/me/privacy", 422, "validation_error", json={"version": "<script>"})
    await expert.fails("POST", "/me/privacy", 422, "validation_error", json={"version": ""})
    await expert.ok("POST", "/auth/logout", 204)
    await expert.fails("POST", "/me/privacy", 401, "not_authenticated", json={"version": "1"})
