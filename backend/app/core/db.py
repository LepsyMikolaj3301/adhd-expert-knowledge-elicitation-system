"""Database engine, session and declarative base for the application tables (schema `app`)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Depends
from sqlalchemy import Enum, MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.settings import settings

APP_SCHEMA = "app"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=APP_SCHEMA, naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


def enum_column(enum_class: type[StrEnum], name: str) -> Enum:
    """A text column with a CHECK constraint: adding a value needs only a migration of the check."""
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [member.value for member in members],
    )


def to_async_url(url: str) -> str:
    """DATABASE_URL is shared with plain asyncpg code; SQLAlchemy needs the driver named.

    Hosted Postgres (Neon) hands out libpq-style options that asyncpg does not know: `sslmode`
    is spelled `ssl`, and `channel_binding` is dropped.
    """
    parts = urlsplit(url.replace("postgresql://", "postgresql+asyncpg://", 1))
    query = [
        ("ssl" if key == "sslmode" else key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "channel_binding"
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def is_pooled(url: str) -> bool:
    """Neon's pooled endpoint (PgBouncer, transaction mode) has `-pooler` in its host name."""
    host = urlsplit(url).hostname or ""
    return "-pooler" in host


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def configure_engine(url: str | None = None, **engine_options) -> AsyncEngine:
    """(Re)create the engine. Called lazily with the settings URL; tests pass their own."""
    global _engine, _session_factory
    url = url or settings.database_url
    if is_pooled(url):
        # PgBouncer in transaction mode hands each statement to any backend connection, so asyncpg's
        # per-connection prepared statements would go missing.
        connect_args = {"statement_cache_size": 0, **engine_options.pop("connect_args", {})}
        engine_options["connect_args"] = connect_args
        engine_options.setdefault("pool_pre_ping", True)
    # hide_parameters: query values are expert text, and must not reach error messages or logs.
    _engine = create_async_engine(to_async_url(url), hide_parameters=True, **engine_options)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        configure_engine()
    assert _session_factory is not None
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request. Routers commit explicitly, before the response is built."""
    async with session_factory()() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]
