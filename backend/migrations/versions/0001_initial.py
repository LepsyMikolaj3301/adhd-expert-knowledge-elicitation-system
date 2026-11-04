"""Initial application schema, in `app`: workflow tables, pseudonym sequence, immutability.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE app.user_pseudonym_seq")
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "admin",
                "expert",
                name="role",
                native_enum=False,
                create_constraint=True,
                length=32,
                schema="app",
            ),
            nullable=False,
        ),
        sa.Column("pseudonym", sa.String(length=32), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "is_synthetic = (pseudonym LIKE 'SYN-%')", name=op.f("ck_users_synthetic_pseudonym")
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("pseudonym", name=op.f("uq_users_pseudonym")),
        schema="app",
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=True),
        sa.Column("to_state", sa.String(length=32), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["app.users.id"], name=op.f("fk_audit_events_actor_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        schema="app",
    )
    op.create_index(
        "ix_audit_events_entity",
        "audit_events",
        ["entity_type", "entity_id", "at"],
        unique=False,
        schema="app",
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app.users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_auth_sessions")),
        schema="app",
    )
    op.create_index(
        op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False, schema="app"
    )
    op.create_table(
        "invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app.users.id"], name=op.f("fk_invites_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invites_token_hash")),
        schema="app",
    )
    op.create_index(op.f("ix_invites_user_id"), "invites", ["user_id"], unique=False, schema="app")
    op.create_table(
        "vignettes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["app.users.id"], name=op.f("fk_vignettes_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vignettes")),
        sa.UniqueConstraint("code", name=op.f("uq_vignettes_code")),
        schema="app",
    )
    op.create_table(
        "vignette_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("vignette_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "published",
                "retired",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
                schema="app",
            ),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("framing", sa.String(length=32), nullable=False),
        sa.Column("question_ids", postgresql.ARRAY(sa.String(length=8)), nullable=False),
        sa.Column("q4_whatif", sa.Text(), nullable=True),
        sa.Column("variant", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("design", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["vignette_id"],
            ["app.vignettes.id"],
            name=op.f("fk_vignette_versions_vignette_id_vignettes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vignette_versions")),
        sa.UniqueConstraint(
            "vignette_id", "version", name=op.f("uq_vignette_versions_vignette_id_version")
        ),
        schema="app",
    )
    op.create_index(
        op.f("ix_vignette_versions_vignette_id"),
        "vignette_versions",
        ["vignette_id"],
        unique=False,
        schema="app",
    )
    op.create_table(
        "assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("vignette_version_id", sa.Uuid(), nullable=False),
        sa.Column("expert_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "assigned",
                "in_progress",
                "processing",
                "processing_failed",
                "expert_check",
                "building_units",
                "admin_review",
                "peer_review",
                "ingesting",
                "ingestion_failed",
                "ingested",
                "rejected",
                "cancelled",
                name="state",
                native_enum=False,
                create_constraint=True,
                length=32,
                schema="app",
            ),
            nullable=False,
        ),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column("gate_passed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "required_approvals >= 1", name=op.f("ck_assignments_required_approvals_min")
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"], ["app.users.id"], name=op.f("fk_assignments_assigned_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["expert_id"], ["app.users.id"], name=op.f("fk_assignments_expert_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["vignette_version_id"],
            ["app.vignette_versions.id"],
            name=op.f("fk_assignments_vignette_version_id_vignette_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assignments")),
        schema="app",
    )
    op.create_index(
        op.f("ix_assignments_expert_id"), "assignments", ["expert_id"], unique=False, schema="app"
    )
    op.create_index(
        op.f("ix_assignments_state"), "assignments", ["state"], unique=False, schema="app"
    )
    op.create_index(
        "uq_assignments_active",
        "assignments",
        ["vignette_version_id", "expert_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("state <> 'cancelled'"),
    )
    op.create_table(
        "answer_drafts",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_answer_drafts_assignment_id_assignments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("assignment_id", name=op.f("pk_answer_drafts")),
        schema="app",
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "process",
                "build_units",
                "ingest",
                name="kind",
                native_enum=False,
                create_constraint=True,
                length=32,
                schema="app",
            ),
            nullable=False,
        ),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "done",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
                schema="app",
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_jobs_assignment_id_assignments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        schema="app",
    )
    op.create_index("ix_jobs_claim", "jobs", ["status", "created_at"], unique=False, schema="app")
    op.create_index(
        "uq_jobs_active",
        "jobs",
        ["assignment_id", "kind"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_table(
        "review_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "stage",
            sa.Enum(
                "admin",
                "peer",
                name="stage",
                native_enum=False,
                create_constraint=True,
                length=32,
                schema="app",
            ),
            nullable=False,
        ),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_review_requests_assignment_id_assignments"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["app.users.id"], name=op.f("fk_review_requests_requested_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["app.users.id"], name=op.f("fk_review_requests_reviewer_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_requests")),
        sa.UniqueConstraint(
            "assignment_id",
            "reviewer_id",
            "stage",
            name=op.f("uq_review_requests_assignment_id_reviewer_id_stage"),
        ),
        schema="app",
    )
    op.create_index(
        op.f("ix_review_requests_reviewer_id"),
        "review_requests",
        ["reviewer_id"],
        unique=False,
        schema="app",
    )
    op.create_table(
        "submissions",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_format", sa.Integer(), nullable=False),
        sa.Column("vignette_hash", sa.String(length=64), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_submissions_assignment_id_assignments"),
        ),
        sa.PrimaryKeyConstraint("assignment_id", name=op.f("pk_submissions")),
        schema="app",
    )
    op.create_table(
        "knowledge_units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(length=8), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "ingested",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
                schema="app",
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_knowledge_units_assignment_id_assignments"),
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["app.submissions.assignment_id"],
            name=op.f("fk_knowledge_units_submission_id_submissions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_units")),
        sa.UniqueConstraint(
            "assignment_id", "ordinal", name=op.f("uq_knowledge_units_assignment_id_ordinal")
        ),
        schema="app",
    )
    op.create_index(
        op.f("ix_knowledge_units_status"), "knowledge_units", ["status"], unique=False, schema="app"
    )
    op.create_table(
        "unit_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "stage",
            sa.Enum(
                "admin",
                "peer",
                name="stage",
                native_enum=False,
                create_constraint=True,
                length=32,
                schema="app",
            ),
            nullable=False,
        ),
        sa.Column(
            "decision",
            sa.Enum(
                "approve",
                "reject",
                name="decision",
                native_enum=False,
                create_constraint=True,
                length=32,
                schema="app",
            ),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("unit_content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["app.users.id"], name=op.f("fk_unit_decisions_reviewer_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["app.knowledge_units.id"],
            name=op.f("fk_unit_decisions_unit_id_knowledge_units"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_unit_decisions")),
        sa.UniqueConstraint(
            "unit_id",
            "reviewer_id",
            "stage",
            name=op.f("uq_unit_decisions_unit_id_reviewer_id_stage"),
        ),
        schema="app",
    )
    # Submissions and the audit trail can be inserted and (for erasure) deleted, never rewritten.
    op.execute(
        """
        CREATE FUNCTION app.reject_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME;
        END
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("submissions", "audit_events"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_update()"
        )


def downgrade() -> None:
    for table in ("submissions", "audit_events"):
        op.execute(f"DROP TRIGGER {table}_immutable ON app.{table}")
    op.execute("DROP FUNCTION app.reject_update()")
    op.drop_table("unit_decisions", schema="app")
    op.drop_index(op.f("ix_knowledge_units_status"), table_name="knowledge_units", schema="app")
    op.drop_table("knowledge_units", schema="app")
    op.drop_table("submissions", schema="app")
    op.drop_index(
        op.f("ix_review_requests_reviewer_id"), table_name="review_requests", schema="app"
    )
    op.drop_table("review_requests", schema="app")
    op.drop_index(
        "uq_jobs_active",
        table_name="jobs",
        schema="app",
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.drop_index("ix_jobs_claim", table_name="jobs", schema="app")
    op.drop_table("jobs", schema="app")
    op.drop_table("answer_drafts", schema="app")
    op.drop_index(
        "uq_assignments_active",
        table_name="assignments",
        schema="app",
        postgresql_where=sa.text("state <> 'cancelled'"),
    )
    op.drop_index(op.f("ix_assignments_state"), table_name="assignments", schema="app")
    op.drop_index(op.f("ix_assignments_expert_id"), table_name="assignments", schema="app")
    op.drop_table("assignments", schema="app")
    op.drop_index(
        op.f("ix_vignette_versions_vignette_id"), table_name="vignette_versions", schema="app"
    )
    op.drop_table("vignette_versions", schema="app")
    op.drop_table("vignettes", schema="app")
    op.drop_index(op.f("ix_invites_user_id"), table_name="invites", schema="app")
    op.drop_table("invites", schema="app")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions", schema="app")
    op.drop_table("auth_sessions", schema="app")
    op.drop_index("ix_audit_events_entity", table_name="audit_events", schema="app")
    op.drop_table("audit_events", schema="app")
    op.drop_table("users", schema="app")
    op.execute("DROP SEQUENCE app.user_pseudonym_seq")
