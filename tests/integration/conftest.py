"""The frozen silver snapshot seeded into a throwaway schema of the DATABASE_URL Postgres.

The query vectors are frozen, so nothing here calls a model. Skipped without Postgres/pgvector.
"""

import os
import uuid
from pathlib import Path

import chips_snapshot
import psycopg
import pytest
from psycopg import sql

from expert_knowledge_rag import ExpertKnowledgeStore

SNAPSHOT = Path(__file__).resolve().parents[1] / "fixtures" / "retrieval_silver"


@pytest.fixture(scope="session")
def dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("needs DATABASE_URL (Postgres with pgvector)")
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            conn.execute("SELECT '[1,2]'::vector").fetchone()
    except Exception as error:
        pytest.skip(f"no usable Postgres: {error}")
    return url


@pytest.fixture(scope="session")
def silver():
    """(tables, vectors, queries) of tests/fixtures/retrieval_silver."""
    if not (SNAPSHOT / "tables.json").exists():
        pytest.skip("no snapshot: python scripts/db/chips_snapshot.py freeze")
    return chips_snapshot.load_snapshot(SNAPSHOT)


@pytest.fixture(scope="session")
def silver_schema(dsn: str, silver):
    name = f"chips_reg_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            conn.execute("BEGIN")
            chips_snapshot.seed(conn, name, SNAPSHOT)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    yield name
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def silver_store(dsn: str, silver_schema: str) -> ExpertKnowledgeStore:
    return ExpertKnowledgeStore(dsn, schema=silver_schema)


@pytest.fixture(scope="session")
def frozen(silver):
    _, vectors, queries = silver
    return chips_snapshot.FrozenEmbeddings(queries, vectors)
