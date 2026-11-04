"""API tests run against a real database, `rag_test` in the compose Postgres (or TEST_DATABASE_URL).

The schema comes from the Alembic migrations, and `app` is emptied before each test.
"""

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.pool import NullPool

from app.core.db import Base, configure_engine, session_factory
from app.models import User  # noqa: F401  (fills Base.metadata)
from app.settings import settings

BACKEND = Path(__file__).resolve().parents[2] / "backend"
TEST_URL = os.environ.get("TEST_DATABASE_URL") or (
    settings.database_url.rsplit("/", 1)[0] + "/rag_test"
)
if not TEST_URL.rsplit("/", 1)[1].endswith("_test"):
    raise RuntimeError(f"refusing to run against a non-test database: {TEST_URL}")


def alembic_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", TEST_URL.replace("%", "%%"))
    config.attributes["configure_logging"] = False
    return config


async def _ensure_database() -> None:
    admin_url = TEST_URL.rsplit("/", 1)[0] + "/postgres"
    connection = await asyncpg.connect(admin_url, timeout=5)
    name = TEST_URL.rsplit("/", 1)[1]
    try:
        if not await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def migrated_database() -> str:
    try:
        asyncio.run(_ensure_database())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres is not reachable: {exc}")
    command.upgrade(alembic_config(), "head")
    return TEST_URL


@pytest_asyncio.fixture(autouse=True)
async def clean_database(migrated_database: str):
    # NullPool: every test has its own event loop, and connections can't move between loops.
    engine = configure_engine(migrated_database, poolclass=NullPool)
    tables = ", ".join(f"app.{table.name}" for table in Base.metadata.sorted_tables)
    async with session_factory()() as session:
        await session.execute(text(f"TRUNCATE {tables} CASCADE"))
        await session.commit()
    yield
    await engine.dispose()
