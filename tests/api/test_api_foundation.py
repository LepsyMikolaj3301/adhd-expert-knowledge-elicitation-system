import json
from pathlib import Path

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.util.exc import CommandError
from api_helpers import Api, admin_api, answer_and_submit, assign, expert_api, published_version
from conftest import TEST_URL, alembic_config
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.cli import openapi_json
from app.core.db import session_factory
from app.main import app, create_app
from app.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


async def test_health_and_unknown_route_use_the_error_shape():
    api = Api()
    assert await api.ok("GET", "/health") == {"status": "ok"}
    await api.fails("GET", "/nope", 404, "http_error")
    await api.close()


def test_migrations_match_the_models(migrated_database):
    try:
        command.check(alembic_config())
    except CommandError as exc:
        pytest.fail(str(exc))


async def test_alembic_only_touches_the_app_schema():
    connection = await asyncpg.connect(TEST_URL)
    try:
        schemas = await connection.fetch(
            "SELECT DISTINCT table_schema FROM information_schema.tables "
            "WHERE table_name IN ('users', 'alembic_version', 'assignments')"
        )
    finally:
        await connection.close()
    assert {row["table_schema"] for row in schemas} == {"app"}


def test_downgrade_leaves_other_schemas_alone(migrated_database):
    """`chips` (the RAG tables, created by migration 0003 and kept by its downgrade) counts too."""
    import asyncio

    async def setup():
        c = await asyncpg.connect(TEST_URL)
        await c.execute("CREATE SCHEMA IF NOT EXISTS scratch")
        await c.execute("CREATE TABLE IF NOT EXISTS scratch.keep_me (id int)")
        await c.execute("CREATE TABLE IF NOT EXISTS public.keep_me (id int)")
        await c.close()

    async def tables():
        c = await asyncpg.connect(TEST_URL)
        rows = await c.fetch(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('app', 'chips', 'scratch', 'public')"
        )
        await c.close()
        return {(r["table_schema"], r["table_name"]) for r in rows}

    async def cleanup():
        c = await asyncpg.connect(TEST_URL)
        await c.execute("DROP SCHEMA scratch CASCADE")
        await c.execute("DROP TABLE public.keep_me")
        await c.close()

    # This test owns the event loop: the autouse fixture is async, so run in a fresh thread.
    import concurrent.futures

    def body():
        asyncio.run(setup())
        before = asyncio.run(tables())
        command.downgrade(alembic_config(), "base")
        after = asyncio.run(tables())
        command.upgrade(alembic_config(), "head")
        restored = asyncio.run(tables())
        asyncio.run(cleanup())
        return before, after, restored

    with concurrent.futures.ThreadPoolExecutor() as pool:
        before, after, restored = pool.submit(body).result()

    others = {t for t in before if t[0] != "app"}
    assert any(schema == "chips" for schema, _ in others), "migration 0003 creates the RAG tables"
    assert {t for t in after if t[0] != "app"} == others
    assert {t for t in after if t[0] == "app"} == {("app", "alembic_version")}
    assert restored == before


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE app.submissions SET payload_format = 2",
        "UPDATE app.audit_events SET action = 'tampered'",
    ],
)
async def test_database_rejects_rewriting_history(statement):
    admin, expert = await admin_api(), await expert_api("e@example.com")
    version = await published_version(admin)
    [assignment_id] = await assign(admin, version, expert)
    await answer_and_submit(expert, assignment_id)
    async with session_factory()() as db:
        with pytest.raises(Exception, match="immutable"):
            await db.execute(text(statement))


async def test_validation_errors_do_not_echo_input():
    api = Api()
    response = await api.request(
        "POST", "/auth/accept-invite", json={"token": "x", "password": "secret-short"[:5]}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "secre" not in response.text


def test_committed_openapi_matches_the_app():
    committed = ROOT / "frontend" / "openapi.json"
    assert committed.exists(), (
        "run: python -m app.cli export-openapi --out ../frontend/openapi.json"
    )
    assert json.loads(committed.read_text()) == json.loads(openapi_json()), (
        "API changed: re-export frontend/openapi.json and regenerate the client types"
    )


def test_every_route_documents_the_error_shape():
    for path, methods in app.openapi()["paths"].items():
        for method, operation in methods.items():
            assert "4XX" in operation["responses"], f"{method} {path}"


@pytest.mark.parametrize("value", ["prod", "Production", "PRODUCTION", ""])
def test_a_mistyped_environment_stops_the_app(value):
    with pytest.raises(ValidationError):
        Settings(environment=value)


NOT_NULL = (
    "INSERT INTO app.answer_drafts (assignment_id, payload, version, updated_at) "
    "VALUES (NULL, :value, 1, now())"
)


@pytest.mark.parametrize(
    ("statement", "error_type"),
    [
        # Postgres quotes the failing row in its own error, further down the exception chain.
        (NOT_NULL, "NotNullViolationError"),
        # The driver quotes the value in its own message, whatever SQLAlchemy hides.
        ("SELECT CAST(:value AS int)", "DataError"),
    ],
)
async def test_a_database_error_keeps_expert_text_out_of_the_logs(caplog, statement, error_type):
    secret = "patient-answer-text"
    app_with_bug = create_app()

    @app_with_bug.get("/boom")
    async def _boom():
        async with session_factory()() as db:
            await db.execute(text(statement), {"value": json.dumps({"a": secret})})

    # raise_app_exceptions stays on: the request would fail here if the error reached the server,
    # which would log the full chain itself.
    transport = httpx.ASGITransport(app=app_with_bug)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "Something went wrong.",
        "details": None,
    }
    assert error_type in caplog.text, "the error type stays there for debugging"
    assert secret not in caplog.text
    assert secret not in response.text


async def test_sqlalchemy_keeps_query_values_out_of_its_error_messages():
    async with session_factory()() as db:
        with pytest.raises(DBAPIError) as error:
            await db.execute(text(NOT_NULL), {"value": '{"a": "patient-answer-text"}'})
    assert "patient-answer-text" not in str(error.value)
