"""DATABASE_URL is shared with plain asyncpg code: SQLAlchemy only needs the driver named."""

from app.core.db import to_async_url


def test_the_url_only_gets_the_driver():
    assert to_async_url("postgresql://rag:rag@localhost:5432/rag") == (
        "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    )


def test_a_url_with_the_driver_is_left_alone():
    url = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    assert to_async_url(url) == url
