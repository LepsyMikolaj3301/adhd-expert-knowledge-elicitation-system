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

-- One row per chunk from s3://$S3_BUCKET/chunked/, written by scripts/index_chunks.py.
-- The embedding width must match config/indexing.yaml; changing it needs DROP TABLE chunks,
-- scripts/init_db.py and a re-index.
CREATE TABLE IF NOT EXISTS chunks (
    -- "<source_id>/<stem>#0001", the chunk id from the chunked JSON.
    id              text PRIMARY KEY,
    document_id     uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_index     integer NOT NULL,
    text            text NOT NULL,
    -- "H1 > H2 > H3\n\n<text>"; this is what gets embedded by default.
    contextual_text text NOT NULL,
    heading_path    text[] NOT NULL DEFAULT '{}',
    section_ids     text[] NOT NULL DEFAULT '{}',
    block_types     text[] NOT NULL DEFAULT '{}',
    pages           integer[] NOT NULL DEFAULT '{}',
    n_tokens        integer NOT NULL,
    -- source_id, title, doi/pmid/pmcid, the manifest metadata block and the chunker config hash.
    metadata        jsonb NOT NULL DEFAULT '{}',
    embedding       vector(1024) NOT NULL,
    embedding_model text NOT NULL,
    chunked_key     text NOT NULL,
    -- Together with index_config: unchanged documents are skipped on the next run.
    chunked_sha256  text NOT NULL,
    index_config    text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
