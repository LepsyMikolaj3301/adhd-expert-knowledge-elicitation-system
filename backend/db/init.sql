CREATE EXTENSION IF NOT EXISTS vector;

-- One row per raw file stored in S3. `id` is the stable document id that later stages
-- (parsing, chunking, claims) reference; user uploads from the frontend get a row too.
-- Keep this file idempotent: it is also applied to existing databases by scripts/init_db.py.
CREATE TABLE IF NOT EXISTS documents (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    origin             text NOT NULL CHECK (origin IN ('manifest', 'user_upload')),
    -- config/sources.yaml id; groups the files of one source (NULL for user uploads).
    source_id          text,
    title              text,
    s3_bucket          text NOT NULL,
    s3_key             text NOT NULL,
    filename           text NOT NULL,
    content_type       text,
    size_bytes         bigint NOT NULL,
    -- Not unique on purpose: the same bytes may be registered twice; dedupe at ingestion.
    sha256             text NOT NULL,
    source_url         text,
    retrieved_at       timestamptz,
    release_or_version text,
    -- doi/pmid/pmcid plus the manifest metadata block (role, licence, evidence_level, ...).
    metadata           jsonb NOT NULL DEFAULT '{}',
    status             text NOT NULL DEFAULT 'uploaded'
                       CHECK (status IN ('uploaded', 'parsing', 'parsed', 'indexed', 'failed')),
    status_detail      text,
    uploaded_by        text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (s3_bucket, s3_key)
);
CREATE INDEX IF NOT EXISTS documents_sha256_idx ON documents (sha256);
CREATE INDEX IF NOT EXISTS documents_source_id_idx ON documents (source_id);
