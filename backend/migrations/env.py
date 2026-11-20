"""Alembic manages only the `app` schema for autogenerate. `public` (literature RAG) is left alone.

The tables of `chips` (approved answers for retrieval) are created by migration 0003 with plain
SQL, since they use pgvector types, and are written by `app.knowledge.ingest`. Autogenerate
ignores them, so changing them takes a hand-written migration.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (fills Base.metadata)
from app.core.db import APP_SCHEMA, Base, to_async_url
from app.settings import settings

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


# Tables of the unit-by-unit review that migration 0006 keeps as history. Their models are gone,
# so autogenerate would propose dropping them.
HISTORY_TABLES = frozenset({"unit_decisions", "unit_comments", "submission_votes"})


def _include_name(name, type_, parent_names) -> bool:
    if type_ == "schema":
        return name == APP_SCHEMA
    return not (type_ == "table" and name in HISTORY_TABLES)


def _run(connection: Connection) -> None:
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {APP_SCHEMA}"))
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        include_schemas=True,
        include_name=_include_name,
        version_table_schema=APP_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _main() -> None:
    url = config.get_main_option("sqlalchemy.url") or settings.database_url
    engine = create_async_engine(to_async_url(url))
    async with engine.connect() as connection:
        await connection.run_sync(_run)
        await connection.commit()
    await engine.dispose()


asyncio.run(_main())
