"""Frozen snapshots seeded into throwaway schemas of the DATABASE_URL Postgres.

silver  tests/fixtures/retrieval_silver (in git): the retrieval regression
scale   the 32-expert scale snapshot under data/ (local only): the scale regression

The query vectors are frozen, so nothing here calls a model. Skipped without Postgres/pgvector, or
without the snapshot.
"""

import json
import os
import uuid
from pathlib import Path

import chips_snapshot
import numpy as np
import psycopg
import pytest
from psycopg import sql

from expert_knowledge_rag import ExpertKnowledgeStore

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "tests" / "fixtures" / "retrieval_silver"


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


def seeded_schema(dsn: str, prefix: str, snapshot: Path):
    """A throwaway schema seeded from `snapshot`; dropped afterwards (a generator for fixtures)."""
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            conn.execute("BEGIN")
            chips_snapshot.seed(conn, name, snapshot)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    yield name
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def silver_schema(dsn: str, silver):
    yield from seeded_schema(dsn, "chips_reg", SNAPSHOT)


@pytest.fixture(scope="session")
def silver_store(dsn: str, silver_schema: str) -> ExpertKnowledgeStore:
    return ExpertKnowledgeStore(dsn, schema=silver_schema)


@pytest.fixture(scope="session")
def frozen(silver):
    _, vectors, queries = silver
    return chips_snapshot.FrozenEmbeddings(queries, vectors)


# --- the scale snapshot (32 experts): local only, data/ is not in git ----------------------------

SCALE_SNAPSHOT = Path(
    os.environ.get("SCALE_SNAPSHOT")
    or ROOT / "data" / "expert_units_chips_scale_proofread" / "synthetic_snapshot"
)


@pytest.fixture(scope="session")
def scale_snapshot() -> dict:
    """The questions frozen next to the scale snapshot (scale_queries.json) and their vectors."""
    missing = [
        f for f in ("tables.json", "vectors.npz", "scale_queries.json", "scale_queries.npz")
        if not (SCALE_SNAPSHOT / f).exists()
    ]  # fmt: skip
    if missing:
        pytest.skip(
            f"no scale snapshot in {SCALE_SNAPSHOT} ({', '.join(missing)}): "
            "python scripts/elicitation/make_scale_fixtures.py --stage build --proofread, then "
            "python scripts/rag/eval_scale_retrieval.py --schema chips_scale --freeze-queries "
            f"{SCALE_SNAPSHOT}"
        )
    frozen = json.loads((SCALE_SNAPSHOT / "scale_queries.json").read_text())
    if frozen["snapshot_sha"] != chips_snapshot.snapshot_digest(SCALE_SNAPSHOT):
        pytest.skip("the snapshot changed after its questions were frozen: rerun --freeze-queries")
    return frozen


@pytest.fixture(scope="session")
def scale_schema(dsn: str, scale_snapshot):
    yield from seeded_schema(dsn, "chips_scale", SCALE_SNAPSHOT)


@pytest.fixture(scope="session")
def scale_store(dsn: str, scale_schema: str) -> ExpertKnowledgeStore:
    return ExpertKnowledgeStore(dsn, schema=scale_schema)


@pytest.fixture(scope="session")
def scale_frozen(scale_snapshot):
    matrix = np.load(SCALE_SNAPSHOT / "scale_queries.npz")["queries"].astype(np.float32)
    return chips_snapshot.FrozenEmbeddings.of(scale_snapshot["texts"], matrix)
