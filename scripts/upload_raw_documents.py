"""Upload everything under data/raw/ to the S3 (MinIO) documents bucket.

Usage: python scripts/upload_raw_documents.py [--source data/raw] [--prefix raw/] [--force]

Object keys are the file paths relative to --source, prefixed with --prefix, so a source fetched
by fetch_sources.py lands at raw/<source_id>/<file>. Every object carries its sha256 as user
metadata (plus source-id, source-url and retrieved-at when a meta.json describes the file);
objects whose remote sha256 matches the local file are skipped unless --force is given.
"""

import argparse
import hashlib
import json
import mimetypes
from pathlib import Path

from botocore.exceptions import ClientError

from app.settings import settings
from app.storage import get_s3_client


def remote_sha256(key: str) -> str | None:
    try:
        head = get_s3_client().head_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return head["Metadata"].get("sha256")


def source_record(path: Path) -> tuple[str, dict] | None:
    """The (source_id, file record) for `path` from its sibling meta.json, if it has one."""
    meta_path = path.parent / "meta.json"
    if path.name == "meta.json" or not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text())
    for record in meta.get("files", []):
        if record["name"] == path.name:
            return meta["source_id"], record
    return None


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
    for path in files:
        key = args.prefix + path.relative_to(args.source).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not args.force and remote_sha256(key) == digest:
            print(f"skip    {key}")
            continue

        metadata = {"sha256": digest}
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if found := source_record(path):
            source_id, record = found
            metadata |= {
                "source-id": source_id,
                "source-url": record["url"],
                "retrieved-at": record["retrieved_at"],
            }
            content_type = record.get("content_type") or content_type
        s3.upload_file(
            str(path),
            settings.s3_bucket,
            key,
            ExtraArgs={"ContentType": content_type, "Metadata": metadata},
        )
        print(f"upload  {key}")


if __name__ == "__main__":
    main()
