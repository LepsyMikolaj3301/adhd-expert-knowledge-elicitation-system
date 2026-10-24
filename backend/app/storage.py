from functools import cache

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from app.settings import settings


@cache
def get_s3_client() -> BaseClient:
    """S3 client pointed at MinIO locally; unset S3_ENDPOINT_URL to use real AWS S3."""
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
        # MinIO needs path-style URLs (http://host/bucket/key), not bucket subdomains.
        config=Config(s3={"addressing_style": "path"}),
    )


def s3_head(key: str) -> dict | None:
    try:
        return get_s3_client().head_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def s3_get(key: str) -> bytes:
    return get_s3_client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def s3_put(key: str, body: bytes, content_type: str, metadata: dict[str, str]) -> None:
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
        Metadata=metadata,
    )


def s3_list_keys(prefix: str) -> list[str]:
    paginator = get_s3_client().get_paginator("list_objects_v2")
    return [
        obj["Key"]
        for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
    ]
