"""Upload everything under data/raw/ to the S3 (MinIO) documents bucket.

Usage: python scripts/upload_raw_documents.py [--source data/raw] [--prefix raw/] [--force]

Object keys are the file paths relative to --source, prefixed with --prefix. Files already in
the bucket with the same size are skipped unless --force is given.
"""

import argparse
import mimetypes
from pathlib import Path

from botocore.exceptions import ClientError

from app.settings import settings
from app.storage import get_s3_client


def remote_size(key: str) -> int | None:
    try:
        return get_s3_client().head_object(Bucket=settings.s3_bucket, Key=key)["ContentLength"]
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


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
        if not args.force and remote_size(key) == path.stat().st_size:
            print(f"skip    {key}")
            continue
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        s3.upload_file(str(path), settings.s3_bucket, key, ExtraArgs={"ContentType": content_type})
        print(f"upload  {key}")


if __name__ == "__main__":
    main()
