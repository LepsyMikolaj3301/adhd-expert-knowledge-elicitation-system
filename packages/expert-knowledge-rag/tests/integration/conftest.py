# ruff: noqa: E501  (SQL strings)
"""A throwaway schema shaped like the web application's `chips`, seeded with the V001 example.

Two sessions of the same case: S1 by expert X1, S2 by expert X2. Dense vectors are
fake (same text, same vector); BM25 is fitted for real with expert_knowledge_core.bm25.
"""

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from psycopg import sql

from expert_knowledge_core import bm25
from expert_knowledge_core.bm25 import Bm25Config
from expert_knowledge_core.example import example_record
from expert_knowledge_rag import ExpertKnowledgeStore

REPO = Path(__file__).resolve().parents[4]
SCHEMA_SQL = REPO / "scripts" / "db" / "chips_schema.sql"
SNAPSHOT = REPO / "tests" / "fixtures" / "retrieval_silver"
sys.path.insert(0, str(REPO / "scripts" / "db"))
EMB = DeterministicFakeEmbedding(size=1024)
VID = "V001"


def vec(text: str) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in EMB.embed_query(text)) + "]"


def pid(session: str, local: str) -> str:
    return f"{session}-{VID}-{local}"


def seed(conn: psycopg.Connection, schema: str) -> None:
    conn.execute(SCHEMA_SQL.read_text().format(schema=schema))  # ty: ignore[no-matching-overload]
    conn.execute(sql.SQL("SET search_path = {}, public").format(sql.Identifier(schema)))
    cue_ids: dict[tuple[bool, int | None], int] = {}
    for session, expert in (("S1", "X1"), ("S2", "X2")):
        rec = example_record(session, expert)
        conn.execute("INSERT INTO experts VALUES (%s, NULL)", (expert,))
        conn.execute(
            "INSERT INTO elicitation_sessions VALUES (%s, %s, %s::jsonb, %s)",
            (session, expert, json.dumps(rec), datetime.now(UTC)),
        )
        for h in rec["highlights"]:
            a, b = h["span"]
            row = conn.execute(
                "INSERT INTO cue_keys (vignette_id, vignette_version, span, text, embedding) "
                "VALUES (%s, 1, int4range(%s, %s), %s, CAST(%s AS vector)) "
                "ON CONFLICT (vignette_id, vignette_version, span) DO UPDATE SET text = EXCLUDED.text "
                "RETURNING id",
                (VID, a, b, h["text"], vec(h["text"])),
            ).fetchone()
            assert row is not None
            cue_ids[(session == "S2", h["chip"])] = row[0]
            conn.execute(
                "INSERT INTO highlights (id, session_id, vignette_id, vignette_version, chip, span, "
                "origin, direction, cue_key_id) VALUES (%s, %s, %s, 1, %s, int4range(%s, %s), "
                "'expert', %s, %s)",
                (pid(session, h["id"]), session, VID, h["chip"], a, b, h["direction"], row[0]),
            )
        meta = rec["meta"]
        for u in rec["units"]:
            conn.execute(
                "INSERT INTO finding_units (id, session_id, expert_id, vignette_id, vignette_version, "
                "kind, highlight_id, direction, population, track, framing, segmenter, "
                "embed_text, embedding) VALUES (%s, %s, %s, %s, 1, "
                "%s, %s, %s, %s, 'general', %s, '{}'::jsonb, %s, CAST(%s AS vector))",
                (
                    pid(session, u["id"]), session, expert, VID, u["kind"],
                    pid(session, u["highlight"]) if u["highlight"] else None, u["direction"],
                    meta["population"], meta["framing"], u["i1"], vec(u["i1"]),
                ),
            )  # fmt: skip
            hl = {h["id"]: h for h in rec["highlights"]}
            roles = ([(u["highlight"], "cue")] if u["highlight"] else []) + [
                (c, "context") for c in u["context"]
            ]
            for hid, role in roles:
                conn.execute(
                    "INSERT INTO unit_cues VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (pid(session, u["id"]), cue_ids[(session == "S2", hl[hid]["chip"])], role),
                )
    refit_sparse(conn)


def refit_sparse(conn: psycopg.Connection) -> None:
    cfg = Bm25Config()
    units = conn.execute("SELECT id, embed_text FROM finding_units ORDER BY id").fetchall()
    keys = conn.execute("SELECT id, text FROM cue_keys ORDER BY id").fetchall()
    for (uid, _), a in zip(units, bm25.fit([u[1] for u in units], cfg), strict=True):
        conn.execute(
            "UPDATE finding_units SET sparse = CAST(%s AS sparsevec) WHERE id = %s",
            (a.to_text(), uid),
        )
    for (kid, _), v in zip(keys, bm25.fit([k[1] for k in keys], cfg), strict=True):
        conn.execute(
            "UPDATE cue_keys SET sparse = CAST(%s AS sparsevec) WHERE id = %s", (v.to_text(), kid)
        )


@pytest.fixture(scope="session")
def dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url or not SCHEMA_SQL.exists():
        pytest.skip("needs DATABASE_URL and the repository's scripts/db/chips_schema.sql")
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            conn.execute("SELECT '[1,2]'::vector").fetchone()
    except Exception as error:  # unreachable, or no pgvector
        pytest.skip(f"no usable Postgres: {error}")
    return url


@pytest.fixture(scope="session")
def schema(dsn: str):
    name = f"chips_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            conn.execute("BEGIN")
            seed(conn, name)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    yield name
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def store(dsn: str, schema: str) -> ExpertKnowledgeStore:
    return ExpertKnowledgeStore(dsn, schema=schema)


@pytest.fixture(scope="session")
def embeddings() -> DeterministicFakeEmbedding:
    return EMB


# --- the frozen silver snapshot: 198 real units with bge-m3 vectors (scripts/db/chips_snapshot.py) -


@pytest.fixture(scope="session")
def silver(dsn: str):
    """(tables, vectors, queries) of tests/fixtures/retrieval_silver."""
    if not (SNAPSHOT / "tables.json").exists():
        pytest.skip(
            "no tests/fixtures/retrieval_silver: python scripts/db/chips_snapshot.py freeze"
        )
    import chips_snapshot

    return chips_snapshot.load_snapshot(SNAPSHOT)


@pytest.fixture(scope="session")
def silver_schema(dsn: str, silver):
    import chips_snapshot

    name = f"chips_silver_{uuid.uuid4().hex[:8]}"
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
    """The real query embeddings of the snapshot; any other text raises instead of calling a model."""
    import chips_snapshot

    _, vectors, queries = silver
    return chips_snapshot.FrozenEmbeddings(queries, vectors)


# --- the snapshot with many experts per vignette (synthetic copies, see chips_snapshot.crowded) --

CROWD = 4  # copies of each of the two experts: ten answers to every vignette


@pytest.fixture(scope="session")
def crowd_schema(dsn: str, silver):
    import chips_snapshot

    name = f"chips_crowd_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            conn.execute("BEGIN")
            chips_snapshot.seed(conn, name, SNAPSHOT, crowd=CROWD)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    yield name
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def crowd_store(dsn: str, crowd_schema: str) -> ExpertKnowledgeStore:
    return ExpertKnowledgeStore(dsn, schema=crowd_schema)
