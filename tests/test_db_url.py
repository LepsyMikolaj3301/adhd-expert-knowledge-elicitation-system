"""DATABASE_URL handling for hosted Postgres (Neon): the URL libpq tools accept must also work for asyncpg."""

from app.core.db import is_pooled, to_async_url

NEON_DIRECT = "postgresql://u:p@ep-cool-1234.eu-central-1.aws.neon.tech/rag?sslmode=require&channel_binding=require"
NEON_POOLED = NEON_DIRECT.replace("ep-cool-1234", "ep-cool-1234-pooler")


def test_plain_local_url_only_gets_the_driver():
    assert to_async_url("postgresql://rag:rag@localhost:5432/rag") == (
        "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    )


def test_neon_url_is_made_asyncpg_safe():
    url = to_async_url(NEON_DIRECT)
    assert url.startswith("postgresql+asyncpg://u:p@ep-cool-1234.eu-central-1.aws.neon.tech/rag?")
    assert "ssl=require" in url
    assert "sslmode" not in url
    assert "channel_binding" not in url


def test_other_query_options_survive():
    url = to_async_url("postgresql://u:p@h/db?sslmode=verify-full&application_name=rag")
    assert "ssl=verify-full" in url
    assert "application_name=rag" in url


def test_pooler_host_is_detected():
    assert is_pooled(NEON_POOLED)
    assert not is_pooled(NEON_DIRECT)
    assert not is_pooled("postgresql://rag:rag@localhost:5432/rag")
