"""Remove sources from Postgres and S3 (raw/, parsed/, chunked/), e.g. after excluding them.

Usage: python scripts/corpus/purge_sources.py [ID ...] [--dry-run]

Without ids, purges every source listed with an `id` under `excluded:` in config/sources.yaml.
Ids still listed under `sources:` are refused. Deleting the `documents` rows cascades to their
`chunks`. Local files under data/raw/ are left alone (the stages skip excluded ids anyway).
"""

import argparse
import asyncio
from pathlib import Path

import asyncpg

from app.settings import settings
from app.sources import load_manifest
from app.storage import s3_delete_prefix, s3_list_keys

PREFIXES = ("raw/", "parsed/", "chunked/")


async def run(ids: list[str], dry_run: bool) -> None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        for source_id in ids:
            docs = await conn.fetchval(
                "SELECT count(*) FROM documents WHERE source_id = $1", source_id
            )
            chunks = await conn.fetchval(
                "SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE d.source_id = $1",
                source_id,
            )
            print(f"{source_id}: {docs} documents, {chunks} chunks")
            for prefix in PREFIXES:
                key_prefix = f"{prefix}{source_id}/"
                if dry_run:
                    print(f"  would delete {len(s3_list_keys(key_prefix))} objects {key_prefix}")
                else:
                    print(f"  deleted {s3_delete_prefix(key_prefix)} objects {key_prefix}")
            if not dry_run:
                await conn.execute("DELETE FROM documents WHERE source_id = $1", source_id)
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ids", nargs="*", metavar="ID", help="source ids (default: excluded)")
    parser.add_argument("--dry-run", action="store_true", help="only report what would go")
    args = parser.parse_args()

    manifest = load_manifest(Path("config/sources.yaml"))
    ids = args.ids or sorted(manifest.excluded_ids)
    if live := set(ids) & {s.id for s in manifest.sources}:
        raise SystemExit(f"Still listed under sources, refusing to purge: {sorted(live)}")
    asyncio.run(run(ids, args.dry_run))


if __name__ == "__main__":
    main()
