from functools import cache

import boto3
from botocore.client import BaseClient
from botocore.config import Config

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
