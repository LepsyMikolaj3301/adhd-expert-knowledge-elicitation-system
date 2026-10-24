"""Apply backend/db/init.sql to the running Postgres (idempotent).

Usage: python scripts/init_db.py

Docker only runs init.sql when the postgres volume is first created; use this to add new tables
to an existing database.
"""

import asyncio
from pathlib import Path

import asyncpg

from app.settings import settings

INIT_SQL = Path(__file__).resolve().parent.parent / "backend" / "db" / "init.sql"


async def main() -> None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(INIT_SQL.read_text())
    finally:
        await conn.close()
    print(f"applied {INIT_SQL.name}")


if __name__ == "__main__":
    asyncio.run(main())
