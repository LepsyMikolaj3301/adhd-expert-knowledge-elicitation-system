"""The answer pipeline: findings, richer units, and the RAG tables of approved answers.

- `app.answer_findings`: how a submitted answer was cut, kept apart from the immutable submission.
- `app.knowledge_units`: the columns of a unit cut by citation (all nullable: the stub's units
  have none of them, so ingesting one of those fails visibly).
- `app.review_requests.requested_by` may be null: the system asks the peers itself.
- Schema `chips`: where ingestion writes approved answers (pgvector). This is a frozen copy of
  scripts/db/chips_schema.sql, which is where the design is documented; keep the two in step by
  adding a migration here for every change. It never deletes anything: on a database that
  already has the schema (the experiments loaded synthetic data into it), the statements do nothing.

Stub-era assignments that are already in `expert_check` have no findings, so their unit build
fails for good (`NoFindings`); nothing real was ever stored by the stubs.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

CHIPS_DDL = """
CREATE SCHEMA IF NOT EXISTS chips;

CREATE TABLE IF NOT EXISTS chips.experts (
    id text PRIMARY KEY,
    role text, is_synthetic boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS chips.vignettes (
    id text NOT NULL, version integer NOT NULL, tier text NOT NULL,
    text text NOT NULL, content_hash text NOT NULL, framing text NOT NULL,
    population text NOT NULL, track text NOT NULL,
    PRIMARY KEY (id, version, tier)
);

CREATE TABLE IF NOT EXISTS chips.elicitation_sessions (
    id text PRIMARY KEY,
    expert_id text NOT NULL REFERENCES chips.experts ON DELETE CASCADE,
    is_synthetic boolean NOT NULL,
    document jsonb NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS chips.cue_keys (
    id bigserial PRIMARY KEY,
    vignette_id text NOT NULL, vignette_version integer NOT NULL, span int4range NOT NULL,
    text text NOT NULL,
    embedding vector(1024) NOT NULL, sparse sparsevec(1048576),
    UNIQUE (vignette_id, vignette_version, span)
);

CREATE TABLE IF NOT EXISTS chips.highlights (
    id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES chips.elicitation_sessions ON DELETE CASCADE,
    vignette_id text NOT NULL, vignette_version integer NOT NULL,
    chip smallint,
    span int4range NOT NULL,
    origin text NOT NULL,
    direction text,
    direction_changed_after_flag boolean NOT NULL DEFAULT false,
    cue_key_id bigint NOT NULL REFERENCES chips.cue_keys
);

CREATE TABLE IF NOT EXISTS chips.answer_sentences (
    id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES chips.elicitation_sessions ON DELETE CASCADE,
    vignette_id text NOT NULL, vignette_version integer NOT NULL,
    question_id text NOT NULL, question_version integer NOT NULL DEFAULT 1,
    idx smallint NOT NULL,
    span int4range NOT NULL,
    targets text[] NOT NULL,
    assigned_by text NOT NULL
);

CREATE TABLE IF NOT EXISTS chips.finding_units (
    id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES chips.elicitation_sessions ON DELETE CASCADE,
    expert_id text NOT NULL,
    vignette_id text NOT NULL, vignette_version integer NOT NULL,
    kind text NOT NULL,
    highlight_id text REFERENCES chips.highlights,
    direction text,
    population text NOT NULL, track text NOT NULL, framing text NOT NULL,
    is_synthetic boolean NOT NULL,
    segmenter jsonb NOT NULL,
    embed_text text NOT NULL,
    embedding vector(1024) NOT NULL, sparse sparsevec(1048576),
    embed_text_combined text,
    embedding_combined vector(1024), sparse_combined sparsevec(1048576)
);

CREATE TABLE IF NOT EXISTS chips.finding_unit_sentences (
    unit_id text REFERENCES chips.finding_units ON DELETE CASCADE,
    sentence_id text REFERENCES chips.answer_sentences ON DELETE CASCADE,
    ord smallint NOT NULL,
    PRIMARY KEY (unit_id, sentence_id)
);

CREATE TABLE IF NOT EXISTS chips.unit_cues (
    unit_id text REFERENCES chips.finding_units ON DELETE CASCADE,
    cue_key_id bigint NOT NULL REFERENCES chips.cue_keys,
    role text NOT NULL,
    PRIMARY KEY (unit_id, cue_key_id, role)
);

CREATE TABLE IF NOT EXISTS chips.review_events (
    session_id text REFERENCES chips.elicitation_sessions ON DELETE CASCADE,
    vignette_id text NOT NULL,
    kind text NOT NULL,
    payload jsonb NOT NULL,
    at timestamptz NOT NULL
);
"""


def upgrade() -> None:
    op.create_table(
        "answer_findings",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("record", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("check_outcome", sa.String(length=16), nullable=True),
        sa.Column("classifier", sa.String(length=64), nullable=True),
        sa.Column("prompt", sa.String(length=64), nullable=True),
        sa.Column("findings_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_answer_findings_assignment_id_assignments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("assignment_id", name=op.f("pk_answer_findings")),
        schema="app",
    )
    for name, type_ in (
        ("kind", sa.String(length=16)),
        ("highlight_id", sa.String(length=16)),
        ("direction", sa.String(length=16)),
        ("patient_words", sa.Text()),
        ("sentence_ids", postgresql.ARRAY(sa.String(length=16))),
        ("context", postgresql.ARRAY(sa.String(length=16))),
        ("embed_text", sa.Text()),
        ("embed_text_combined", sa.Text()),
    ):
        op.add_column("knowledge_units", sa.Column(name, type_, nullable=True), schema="app")
    op.alter_column("review_requests", "requested_by", nullable=True, schema="app")

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for statement in CHIPS_DDL.split(";"):  # asyncpg runs one statement per call
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    # `chips` stays: it holds ingested answers, and dropping it is not something to do by accident.
    op.execute(
        "UPDATE app.review_requests SET requested_by = assigned_by FROM app.assignments "
        "WHERE app.review_requests.assignment_id = app.assignments.id "
        "AND app.review_requests.requested_by IS NULL"
    )
    op.alter_column("review_requests", "requested_by", nullable=False, schema="app")
    for name in (
        "embed_text_combined",
        "embed_text",
        "context",
        "sentence_ids",
        "patient_words",
        "direction",
        "highlight_id",
        "kind",
    ):
        op.drop_column("knowledge_units", name, schema="app")
    op.drop_table("answer_findings", schema="app")
