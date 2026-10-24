"""Upload everything under data/raw/ to the S3 (MinIO) documents bucket and register it.

Usage: python scripts/upload_raw_documents.py [--source data/raw] [--prefix raw/] [--force]

Object keys are the file paths relative to --source, prefixed with --prefix, so a source fetched
by fetch_sources.py lands at raw/<source_id>/<file>. Every object carries its sha256 as user
metadata (plus source-id, source-url and retrieved-at when a meta.json describes the file);
objects whose remote sha256 matches the local file are skipped unless --force is given.

Every file described by a meta.json is also upserted into the Postgres `documents` table (also
when the upload itself was skipped), keyed by (bucket, key) so its document id stays stable.
Files without a meta.json (and the meta.json / _fetch_report.json sidecars) are uploaded but not
registered as documents.
"""

import argparse
import asyncio
import hashlib
import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import asyncpg
from botocore.exceptions import ClientError

from app.settings import settings
from app.storage import get_s3_client

UPSERT_DOCUMENT = """
INSERT INTO documents (origin, source_id, title, s3_bucket, s3_key, filename, content_type,
                       size_bytes, sha256, source_url, retrieved_at, release_or_version, metadata)
VALUES ('manifest', $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)
ON CONFLICT (s3_bucket, s3_key) DO UPDATE SET
    title = EXCLUDED.title,
    content_type = EXCLUDED.content_type,
    size_bytes = EXCLUDED.size_bytes,
    source_url = EXCLUDED.source_url,
    retrieved_at = EXCLUDED.retrieved_at,
    release_or_version = EXCLUDED.release_or_version,
    metadata = EXCLUDED.metadata,
    -- New bytes invalidate whatever was parsed from the old ones.
    status = CASE WHEN documents.sha256 = EXCLUDED.sha256 THEN documents.status ELSE 'uploaded' END,
    status_detail = CASE WHEN documents.sha256 = EXCLUDED.sha256 THEN documents.status_detail END,
    sha256 = EXCLUDED.sha256,
    updated_at = now()
RETURNING id, (xmax = 0) AS inserted
"""


@dataclass
class SourceFile:
    """A raw file described by the meta.json next to it."""

    meta: dict
    record: dict


def remote_sha256(key: str) -> str | None:
    try:
        head = get_s3_client().head_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return head["Metadata"].get("sha256")


def source_file(path: Path) -> SourceFile | None:
    meta_path = path.parent / "meta.json"
    if path.name == "meta.json" or not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text())
    for record in meta.get("files", []):
        if record["name"] == path.name:
            return SourceFile(meta, record)
    return None


async def register(documents: list[tuple[str, Path, SourceFile]]) -> None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        async with conn.transaction():
            for key, path, found in documents:
                meta, record = found.meta, found.record
                row = await conn.fetchrow(
                    UPSERT_DOCUMENT,
                    meta["source_id"],
                    meta.get("title"),
                    settings.s3_bucket,
                    key,
                    path.name,
                    record.get("content_type"),
                    path.stat().st_size,
                    record["sha256"],
                    record["url"],
                    datetime.fromisoformat(record["retrieved_at"]),
                    meta.get("release_or_version"),
                    json.dumps(
                        {
                            **{k: meta[k] for k in ("doi", "pmid", "pmcid") if k in meta},
                            **meta.get("metadata", {}),
                        }
                    ),
                )
                assert row is not None
                print(f"{'insert' if row['inserted'] else 'update':<7} {row['id']}  {key}")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=Path("data/raw"))
    parser.add_argument("--prefix", default="raw/", help="key prefix in the bucket")
    parser.add_argument("--force", action="store_true", help="re-upload existing objects")
    args = parser.parse_args()

    files = sorted(p for p in args.source.rglob("*") if p.is_file())
    if not files:
        raise SystemExit(f"No files found in {args.source}")

    s3 = get_s3_client()
    to_register = []
    for path in files:
        key = args.prefix + path.relative_to(args.source).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        found = source_file(path)
        if found:
            if found.record["sha256"] != digest:
                raise SystemExit(f"{path} does not match the sha256 in its meta.json")
            to_register.append((key, path, found))

        if not args.force and remote_sha256(key) == digest:
            print(f"skip    {key}")
            continue

        metadata = {"sha256": digest}
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if found:
            metadata |= {
                "source-id": found.meta["source_id"],
                "source-url": found.record["url"],
                "retrieved-at": found.record["retrieved_at"],
            }
            content_type = found.record.get("content_type") or content_type
        s3.upload_file(
            str(path),
            settings.s3_bucket,
            key,
            ExtraArgs={"ContentType": content_type, "Metadata": metadata},
        )
        print(f"upload  {key}")

    unregistered = len(files) - len(to_register)
    print(f"registering {len(to_register)} documents ({unregistered} files are not documents)")
    asyncio.run(register(to_register))


if __name__ == "__main__":
    main()
