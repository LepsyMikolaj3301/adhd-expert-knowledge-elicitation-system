"""Routes and rules that the other API tests left out: who may call what, what is not found, what
the query parameters accept, and the account changes the admin makes."""

from uuid import uuid4

import pytest
from api_helpers import (
    PASSWORD,
    admin_api,
    assign,
    expert_api,
    published_version,
    vignette_body,
)
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.auth import service as auth_service
from app.core.db import session_factory
from app.core.security import verify_password
from app.users.models import User

CONTENT_FIELDS = ("text", "framing", "q4_whatif", "patient_summary", "design")


def content() -> dict:
    return {k: v for k, v in vignette_body().items() if k in CONTENT_FIELDS}


# --- who may call what -------------------------------------------------------------------------

ADMIN_ONLY_TOO = [
    ("GET", "/vignettes/questions"),
    ("GET", "/knowledge-units/index"),
    ("POST", "/knowledge-units/index/refit"),
    ("DELETE", f"/knowledge-units/{uuid4()}"),
    ("DELETE", f"/knowledge-units/by-expert/{uuid4()}"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY_TOO)
async def test_more_routes_are_for_the_admin_only(method, path):
    expert = await expert_api("e@example.com")
    await expert.fails(method, path, 403, "forbidden")


# --- what is not found -------------------------------------------------------------------------

UNKNOWN = [
    ("PATCH", "/users/{id}", {"display_name": "New"}),
    ("POST", "/users/{id}/invite", None),
    ("POST", "/vignettes/{id}/versions", content),
    ("PATCH", "/vignette-versions/{id}", {"text": "New text."}),
    ("POST", "/vignette-versions/{id}/publish", None),
    ("POST", "/vignette-versions/{id}/retire", None),
    ("POST", "/vignette-versions/{id}/assignments", {"expert_ids": [str(uuid4())]}),
    ("GET", "/assignments/{id}", None),
    ("GET", "/assignments/{id}/submission", None),
    ("GET", "/assignments/{id}/events", None),
    ("DELETE", "/knowledge-units/{id}", None),
    ("DELETE", "/knowledge-units/by-expert/{id}", None),
]


@pytest.mark.parametrize(("method", "path", "body"), UNKNOWN)
async def test_an_admin_asking_for_something_that_does_not_exist_gets_a_404(method, path, body):
    admin = await admin_api()
    json = body() if callable(body) else body
    await admin.fails(method, path.format(id=uuid4()), 404, "not_found", json=json)


# --- what the parameters accept ----------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/assignments/not-a-uuid",
        "/assignments?state=nonsense",
        "/assignments?limit=0",
        "/assignments?limit=501",
        "/assignments?offset=-1",
        "/assignments?vignette_version_id=nope",
    ],
)
async def test_a_malformed_path_or_query_is_a_422_not_a_crash(path):
    admin = await admin_api()
    response = await admin.request("GET", path)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_error"


async def test_the_list_can_be_filtered_by_state_and_paged():
    admin = await admin_api()
    version = await published_version(admin)
    experts = [await expert_api(f"e{n}@example.com") for n in range(3)]
    ids = await assign(admin, version, *experts)
    await experts[0].ok("POST", f"/assignments/{ids[0]}/start")

    every = await admin.ok("GET", "/assignments")
    assert {a["id"] for a in every} == set(ids)
    started = await admin.ok("GET", "/assignments?state=in_progress")
    assert [a["id"] for a in started] == [ids[0]]
    assert await admin.ok("GET", "/assignments?state=cancelled") == []

    first = await admin.ok("GET", "/assignments?limit=2")
    rest = await admin.ok("GET", "/assignments?limit=2&offset=2")
    assert len(first) == 2 and len(rest) == 1
    assert {a["id"] for a in first + rest} == set(ids)
    assert await admin.ok("GET", "/assignments?offset=3") == []


# --- what does not exist yet -------------------------------------------------------------------


async def test_the_submission_and_the_findings_do_not_exist_before_they_are_made():
    admin = await admin_api()
    version = await published_version(admin)
    expert = await expert_api("e@example.com")
    (assignment_id,) = await assign(admin, version, expert)
    await expert.ok("POST", f"/assignments/{assignment_id}/start")
    for who in (expert, admin):
        body = await who.fails("GET", f"/assignments/{assignment_id}/submission", 404, "not_found")
        assert body["details"] == {"resource": "Submission"}
    body = await admin.fails("GET", f"/assignments/{assignment_id}/findings", 404, "not_found")
    assert body["details"] == {"resource": "Findings"}
    await expert.fails("GET", f"/assignments/{assignment_id}/findings", 404, "not_found")


async def test_a_draft_cannot_be_retired():
    admin = await admin_api()
    vignette = await admin.ok("POST", "/vignettes", 201, json=vignette_body())
    version_id = vignette["versions"][0]["id"]
    await admin.fails(
        "POST", f"/vignette-versions/{version_id}/retire", 409, "version_not_published"
    )
    await admin.ok("POST", f"/vignette-versions/{version_id}/publish")
    await admin.ok("POST", f"/vignette-versions/{version_id}/retire")
    await admin.fails(
        "POST", f"/vignette-versions/{version_id}/retire", 409, "version_not_published"
    )


# --- accounts ----------------------------------------------------------------------------------


async def _actions(user_id: str) -> list[str]:
    async with session_factory()() as db:
        rows = await db.scalars(
            select(AuditEvent.action).where(AuditEvent.entity_id == user_id).order_by(AuditEvent.at)
        )
        return list(rows)


async def test_an_account_is_renamed_deactivated_and_reactivated():
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    user_id = expert.user_id
    assert user_id

    renamed = await admin.ok("PATCH", f"/users/{user_id}", json={"display_name": "Evelyn Q"})
    assert renamed["display_name"] == "Evelyn Q" and renamed["is_active"] is True

    off = await admin.ok("PATCH", f"/users/{user_id}", json={"is_active": False})
    assert off["is_active"] is False
    await expert.fails("GET", "/me", 401, "not_authenticated")  # their sessions ended
    again = expert.client
    await again.post("/auth/login", json={"email": "e@example.com", "password": PASSWORD})
    assert (await again.get("/me")).status_code == 401

    on = await admin.ok("PATCH", f"/users/{user_id}", json={"is_active": True})
    assert on["is_active"] is True
    await expert.ok("POST", "/auth/login", json={"email": "e@example.com", "password": PASSWORD})
    await expert.ok("GET", "/me")

    assert await _actions(user_id) == ["user_created", "user_deactivated", "user_activated"]


async def test_setting_the_state_an_account_already_has_records_nothing():
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    await admin.ok("PATCH", f"/users/{expert.user_id}", json={"is_active": True})
    assert await _actions(expert.user_id) == ["user_created"]  # and nothing for the no-op


async def test_the_admin_cannot_deactivate_their_own_account():
    admin = await admin_api()
    await admin.fails(
        "PATCH", f"/users/{admin.user_id}", 409, "cannot_deactivate_self", json={"is_active": False}
    )
    await admin.ok("GET", "/me")


async def test_a_login_with_an_out_of_date_hash_stores_a_fresh_one(monkeypatch):
    expert = await expert_api("e@example.com")
    async with session_factory()() as db:
        before = await db.scalar(select(User.password_hash).where(User.id == expert.user_id))
    monkeypatch.setattr(auth_service, "needs_rehash", lambda _: True)
    await expert.ok("POST", "/auth/login", json={"email": "e@example.com", "password": PASSWORD})
    async with session_factory()() as db:
        after = await db.scalar(select(User.password_hash).where(User.id == expert.user_id))
    assert after != before
    assert verify_password(after, PASSWORD)


async def test_a_login_with_a_current_hash_keeps_it(monkeypatch):
    expert = await expert_api("e@example.com")
    async with session_factory()() as db:
        before = await db.scalar(select(User.password_hash).where(User.id == expert.user_id))
    monkeypatch.setattr(auth_service, "needs_rehash", lambda _: False)
    await expert.ok("POST", "/auth/login", json={"email": "e@example.com", "password": PASSWORD})
    async with session_factory()() as db:
        assert (
            await db.scalar(select(User.password_hash).where(User.id == expert.user_id)) == before
        )
