#!/bin/sh
# Creates the S3 bucket and a dedicated app user in MinIO. Safe to re-run.
set -eu

: "${MINIO_URL:?MINIO_URL is required}"
: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"
: "${S3_BUCKET:?S3_BUCKET is required}"
: "${S3_ACCESS_KEY_ID:?S3_ACCESS_KEY_ID is required}"
: "${S3_SECRET_ACCESS_KEY:?S3_SECRET_ACCESS_KEY is required}"

mc alias set local "$MINIO_URL" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null

mc mb --ignore-existing "local/$S3_BUCKET"
echo "Bucket '$S3_BUCKET' is ready."

# Dedicated app credentials (mirrors an IAM user on real AWS) instead of the root account.
# 'user add' on an existing user just updates the secret, so this is idempotent.
mc admin user add local "$S3_ACCESS_KEY_ID" "$S3_SECRET_ACCESS_KEY" >/dev/null
mc admin policy attach local readwrite --user "$S3_ACCESS_KEY_ID" >/dev/null 2>&1 \
    || echo "Policy 'readwrite' already attached to '$S3_ACCESS_KEY_ID'."
echo "App user '$S3_ACCESS_KEY_ID' is ready."
