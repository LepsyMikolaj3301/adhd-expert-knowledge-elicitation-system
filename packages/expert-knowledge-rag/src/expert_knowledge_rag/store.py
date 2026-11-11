"""The connection to the expert knowledge database. Read-only, sync and async."""

import contextlib
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

from expert_knowledge_core.retrieval import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from expert_knowledge_rag.sql import Query

Rows = list[dict[str, Any]]


class ExpertKnowledgeStore:
    """Where the approved expert units are stored (the Postgres schema `chips`).

    Give a `dsn`, or a psycopg pool (`pool=`: anything with `.connection()`, such as
    `psycopg_pool.ConnectionPool`; `async_pool=` for `AsyncConnectionPool`). Every call runs in a
    `READ ONLY` transaction, so a bug or a hostile query string can't change the knowledge base,
    and prepared statements are off, which keeps it working behind Neon's pooler.

    `schema` is `chips` for the web application's ingested answers; `chips_eval` holds the test
    data of scripts/db/load_chips_pg.py. `dimensions` must match the stored vectors.
    """

    def __init__(
        self,
        dsn: str | None = None,
        *,
        pool: Any = None,
        async_pool: Any = None,
        schema: str = "chips",
        dimensions: int = EMBEDDING_DIMENSIONS,
    ) -> None:
        if dsn is None and pool is None and async_pool is None:
            raise ValueError("give a dsn, a pool or an async_pool")
        self.dsn = dsn
        self.pool = pool
        self.async_pool = async_pool
        self.schema = schema
        self.dimensions = dimensions

    def vector_text(self, vector: Sequence[float]) -> str:
        """A query embedding as the text pgvector parses; checks its width first."""
        if len(vector) != self.dimensions:
            raise ValueError(
                f"the query embedding has {len(vector)} dimensions but the stored vectors have "
                f"{self.dimensions}: embed queries with {EMBEDDING_MODEL} "
                "(the model of config/indexing.yaml)"
            )
        return "[" + ",".join(f"{v:.8g}" for v in vector) + "]"

    # --- sync ------------------------------------------------------------------------------

    @contextlib.contextmanager
    def _connection(self) -> Iterator[psycopg.Connection]:
        if self.pool is not None:
            with self.pool.connection() as conn:
                yield conn
        else:
            assert self.dsn is not None, "this store only has an async pool"
            with psycopg.connect(self.dsn, prepare_threshold=None) as conn:
                yield conn

    def run(self, queries: Sequence[Query]) -> list[Rows]:
        """The rows of each query, run one after the other in one read-only transaction."""
        with (
            self._connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=dict_row) as cur,
        ):
            cur.execute("SET TRANSACTION READ ONLY")
            results = []
            for query, params in queries:
                cur.execute(query, params)
                results.append(cur.fetchall())
            return results

    # --- async -----------------------------------------------------------------------------

    @contextlib.asynccontextmanager
    async def _aconnection(self) -> AsyncIterator[psycopg.AsyncConnection]:
        if self.async_pool is not None:
            async with self.async_pool.connection() as conn:
                yield conn
        else:
            assert self.dsn is not None, "this store only has a sync pool"
            async with await psycopg.AsyncConnection.connect(
                self.dsn, prepare_threshold=None
            ) as conn:
                yield conn

    async def arun(self, queries: Sequence[Query]) -> list[Rows]:
        async with (
            self._aconnection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute("SET TRANSACTION READ ONLY")
            results = []
            for query, params in queries:
                await cur.execute(query, params)
                results.append(await cur.fetchall())
            return results
