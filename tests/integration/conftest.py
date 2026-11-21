"""The filled vignettes of tests/fixtures/scale_answers, ingested at test time into throwaway
schemas.

silver  experts SYN-001 and SYN-002 (whose claims label the 40 questions): the retrieval regression
scale   all 32 experts: the scale regression

Ingestion is the application's: units built from the answers and the stored classifier links,
embedded with bge-m3 through Ollama (config/indexing.yaml), BM25 fitted in Postgres. Questions are
embedded the same way. Nothing derived is stored, so these tests need Postgres with pgvector and
Ollama with bge-m3. Without them the tests skip, except when the run asks for them (`-m regression`,
`-m scale`): then a missing service is a failure, so a regression run cannot pass by not running.
"""

import os
import uuid

import chips_fixture
import psycopg
import pytest

EXPLICIT = ("regression", "scale")


def unavailable(config: pytest.Config, reason: str):
    """Skip, or fail when the run selected the regression markers."""
    if any(m in (config.getoption("markexpr") or "") for m in EXPLICIT):
        pytest.fail(f"{reason} (needed by -m {config.getoption('markexpr')})", pytrace=False)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def dsn(pytestconfig) -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        unavailable(pytestconfig, "needs DATABASE_URL (Postgres with pgvector)")
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            conn.execute("SELECT '[1,2]'::vector").fetchone()
    except Exception as error:
        unavailable(pytestconfig, f"no usable Postgres: {error}")
    return url


@pytest.fixture(scope="session")
def embedder(pytestconfig) -> chips_fixture.IndexEmbeddings:
    """bge-m3 as the application embeds; one per session, so every text is embedded once."""
    try:
        emb = chips_fixture.IndexEmbeddings()
        emb.embed_query("ping")
    except Exception as error:
        unavailable(pytestconfig, f"no embedding model (Ollama with bge-m3): {error}")
    return emb


@pytest.fixture(scope="session")
def fixture_digest() -> str:
    return chips_fixture.digest()


def seeded(dsn: str, prefix: str, corpus: chips_fixture.Corpus):
    with chips_fixture.seeded_schema(dsn, f"{prefix}_{uuid.uuid4().hex[:8]}", corpus) as name:
        yield name


# --- silver: two experts, the labelled questions ------------------------------------------------


@pytest.fixture(scope="session")
def silver(dsn, embedder) -> chips_fixture.Corpus:
    """(tables, vectors, queries) of experts SYN-001 and SYN-002."""
    return chips_fixture.ingest(chips_fixture.load(experts=chips_fixture.SILVER_EXPERTS), embedder)


@pytest.fixture(scope="session")
def silver_schema(dsn: str, silver):
    yield from seeded(dsn, "chips_reg", silver)


@pytest.fixture(scope="session")
def silver_store(dsn: str, silver_schema: str):
    from expert_knowledge_rag import ExpertKnowledgeStore

    return ExpertKnowledgeStore(dsn, schema=silver_schema)


# --- scale: all 32 experts ----------------------------------------------------------------------


@pytest.fixture(scope="session")
def scale(dsn, embedder) -> chips_fixture.Corpus:
    return chips_fixture.ingest(chips_fixture.load(), embedder, patients=False)


@pytest.fixture(scope="session")
def scale_schema(dsn: str, scale):
    yield from seeded(dsn, "chips_scale", scale)


@pytest.fixture(scope="session")
def scale_store(dsn: str, scale_schema: str):
    from expert_knowledge_rag import ExpertKnowledgeStore

    return ExpertKnowledgeStore(dsn, schema=scale_schema)
