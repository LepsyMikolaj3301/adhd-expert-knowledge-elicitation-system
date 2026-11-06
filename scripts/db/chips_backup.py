"""Back up, check, restore and empty the tables of schema `chips` (binary COPY, no pg_dump needed).

Usage: python scripts/db/chips_backup.py backup  --out data/backup/chips_synthetic_2026-11-05
       python scripts/db/chips_backup.py verify  --out data/backup/chips_synthetic_2026-11-05
       python scripts/db/chips_backup.py empty   --out data/backup/chips_synthetic_2026-11-05
       python scripts/db/chips_backup.py restore --out data/backup/chips_synthetic_2026-11-05

`backup` refuses to run if any row is not synthetic. `verify` loads every file back into temporary
tables (nothing in `chips` changes) and compares row counts and a checksum of each table. `empty`
only runs if `verify` passes. `restore` needs empty tables.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

from app.settings import settings

SCHEMA = "chips"
# Parents before children.
TABLES = (
    "experts",
    "vignettes",
    "elicitation_sessions",
    "cue_keys",
    "highlights",
    "answer_sentences",
    "finding_units",
    "finding_unit_sentences",
    "unit_cues",
    "review_events",
)
SYNTHETIC_CHECKS = {
    "experts": "SELECT count(*) FROM chips.experts WHERE NOT is_synthetic",
    "elicitation_sessions": (
        "SELECT count(*) FROM chips.elicitation_sessions WHERE NOT is_synthetic"
    ),
    "finding_units": "SELECT count(*) FROM chips.finding_units WHERE NOT is_synthetic",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def count(conn: asyncpg.Connection, table: str) -> int:
    return await conn.fetchval(f'SELECT count(*) FROM {SCHEMA}."{table}"')


async def backup(conn: asyncpg.Connection, out: Path) -> None:
    for table, query in SYNTHETIC_CHECKS.items():
        if real := await conn.fetchval(query):
            raise SystemExit(f"{table} holds {real} rows that are not synthetic: not backing up")
    await asyncio.to_thread(out.mkdir, parents=True, exist_ok=True)
    manifest = {"created_at": datetime.now(UTC).isoformat(), "schema": SCHEMA, "tables": {}}
    async with conn.transaction(isolation="repeatable_read", readonly=True):
        for table in TABLES:
            path = out / f"{table}.bin"
            await conn.copy_from_table(table, output=str(path), schema_name=SCHEMA, format="binary")
            manifest["tables"][table] = {"rows": await count(conn, table), "sha256": sha256(path)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({t: v["rows"] for t, v in manifest["tables"].items()}))


async def _fingerprint(conn: asyncpg.Connection, relation: str) -> str:
    """A checksum of a table's content, independent of the physical order of its rows."""
    return await conn.fetchval(
        f"SELECT md5(coalesce(string_agg(r::text, E'\\n' ORDER BY r::text), '')) "
        f"FROM {relation} AS r"
    )


async def verify(conn: asyncpg.Connection, out: Path) -> bool:
    manifest = json.loads((out / "manifest.json").read_text())
    ok = True
    async with conn.transaction():
        for table in TABLES:
            path = out / f"{table}.bin"
            want = manifest["tables"][table]
            if sha256(path) != want["sha256"]:
                print(f"{table}: file changed since the backup")
                ok = False
                continue
            scratch = f"_verify_{table}"
            await conn.execute(
                f'CREATE TEMP TABLE "{scratch}" (LIKE {SCHEMA}."{table}") ON COMMIT DROP'
            )
            await conn.copy_to_table(scratch, source=str(path), format="binary")
            rows = await conn.fetchval(f'SELECT count(*) FROM "{scratch}"')
            same = await _fingerprint(conn, f'"{scratch}"')
            live = await _fingerprint(conn, f'{SCHEMA}."{table}"')
            # The live table may already be empty: then only the count is compared.
            live_rows = await count(conn, table)
            match = rows == want["rows"] and (live_rows == 0 or same == live)
            ok &= match
            verdict = "OK" if match else "MISMATCH"
            print(f"{table}: {rows} rows restored, expected {want['rows']}: {verdict}")
    return ok


async def empty(conn: asyncpg.Connection) -> None:
    tables = ", ".join(f'{SCHEMA}."{t}"' for t in reversed(TABLES))
    await conn.execute(f"TRUNCATE {tables}")
    print("emptied", {t: await count(conn, t) for t in TABLES})


async def restore(conn: asyncpg.Connection, out: Path) -> None:
    async with conn.transaction():
        if full := [t for t in TABLES if await count(conn, t)]:
            raise SystemExit(f"not empty: {full}")
        for table in TABLES:
            await conn.copy_to_table(
                table, source=str(out / f"{table}.bin"), schema_name=SCHEMA, format="binary"
            )
        await conn.execute(
            "SELECT setval(pg_get_serial_sequence('chips.cue_keys', 'id'), "
            "coalesce((SELECT max(id) FROM chips.cue_keys), 1))"
        )
    print("restored", {t: await count(conn, t) for t in TABLES})


async def main(args: argparse.Namespace) -> int:
    conn = await asyncpg.connect(settings.database_url)
    try:
        from pgvector.asyncpg import register_vector

        await conn.execute(f"SET search_path = {SCHEMA}, public")
        await register_vector(conn)
        if args.action == "backup":
            await backup(conn, args.out)
        elif args.action == "verify":
            return 0 if await verify(conn, args.out) else 1
        elif args.action == "empty":
            if not await verify(conn, args.out):
                print("the backup does not verify: nothing was emptied")
                return 1
            await empty(conn)
        else:
            await restore(conn, args.out)
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["backup", "verify", "empty", "restore"])
    ap.add_argument("--out", type=Path, required=True)
    sys.exit(asyncio.run(main(ap.parse_args())))
