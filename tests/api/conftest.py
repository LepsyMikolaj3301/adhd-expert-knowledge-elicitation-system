"""API tests run against a real database, `rag_test` in the compose Postgres (or TEST_DATABASE_URL).

The schema comes from the Alembic migrations, and `app` is emptied before each test.
"""

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path

import asyncpg
import httpx
import numpy as np
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
        # The RAG tables that ingestion writes (rag_test only: the name is checked above).
        await session.execute(
            text(
                "TRUNCATE chips.experts, chips.vignettes, chips.elicitation_sessions, "
                "chips.cue_keys CASCADE"
            )
        )
        await session.commit()
    yield
    await engine.dispose()


class FakeModels:
    """Stands in for Ollama and LanguageTool: the classifier files every sentence it is asked
    about under `case` (or wherever `labels` says), embeddings are deterministic vectors of the
    text, the grammar checker finds nothing (or what `grammar_matches` says), and the enhancement
    returns the answer unchanged (or `enhance_reply`)."""

    def __init__(self) -> None:
        self.classifier_calls: list[str] = []  # the user prompt of each call
        self.embedded: list[list[str]] = []  # the texts of each call
        self.labels: dict[str, list[str]] = {}
        self.classifier_reply: str | None = None  # a raw reply, e.g. garbage
        self.down = False
        self.grammar_calls: list[str] = []
        self.grammar_matches: dict[str, list[dict]] = {}  # text -> LanguageTool matches
        self.grammar_down = False
        self.enhance_calls: list[str] = []
        self.enhance_reply: dict[str, str] = {}  # answer -> edited answer
        self.enhance_down = False

    async def check_grammar(self, text, quotes) -> dict:
        self.grammar_calls.append(text)
        if self.grammar_down:
            raise httpx.ConnectError("languagetool is down")
        return {"software": {"version": "fake"}, "matches": self.grammar_matches.get(text, [])}

    async def enhance(self, system, user) -> str:
        self.enhance_calls.append(user)
        if self.enhance_down:
            raise httpx.ConnectError("ollama is down")
        answer = re.search(r"<answer>\n(.*?)\n</answer>", user, re.DOTALL)
        text = answer.group(1) if answer else ""
        return json.dumps({"answer": self.enhance_reply.get(text, text)})

    async def ask(self, system, user, seed) -> str:
        self.classifier_calls.append(user)
        if self.down:
            raise ConnectionError("ollama is down")
        if self.classifier_reply is not None:
            return self.classifier_reply
        left = re.search(r"Sentences to file: (.*)", user)
        ids = [i.strip() for i in left.group(1).split(",")] if left else []
        return json.dumps({i: self.labels.get(i, ["case"]) for i in ids})

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.embedded.append(list(texts))
        if self.down:
            raise ConnectionError("ollama is down")
        return [self.vector(text) for text in texts]

    @staticmethod
    def vector(text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big")
        values = np.random.RandomState(seed).randn(1024)
        return (values / np.linalg.norm(values)).tolist()


@pytest.fixture(autouse=True)
def models(monkeypatch) -> FakeModels:
    fake = FakeModels()
    monkeypatch.setattr("app.knowledge.classifier.ask", fake.ask)
    monkeypatch.setattr("app.knowledge.embedding.embed_texts", fake.embed_texts)
    monkeypatch.setattr("app.proofread.grammar.ask", fake.check_grammar)
    monkeypatch.setattr("app.proofread.enhance.ask", fake.enhance)
    return fake
