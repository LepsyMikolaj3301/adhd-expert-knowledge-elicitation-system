"""Open review: every colleague who may read a submission sees it, discusses it and votes on it.
Only the admin closes a review.

- `admin_review` is gone as a state: a submission waits in `peer_review` for the admin whether or
  not anyone else looks at it. Rows in it move over.
- `review_requests` (a list of reviewers chosen up front) is replaced by `review_participants`
  (who opened the review and so read the answers). Existing peer rows are kept there, because they
  are what stops a reviewer being assigned the vignette later.
- `assignments.required_approvals` goes: peer votes are advisory.
- New: `unit_comments` (the discussion under a unit), `submission_votes` (accept or decline of the
  whole submission, per review round), `users.activity_seen_at` (what the home page marks unread),
  and an index for reading the audit trail by action.

The downgrade flattens: the comments and votes are lost (their data has no older home), the
participants become completed peer requests, and `required_approvals` returns as 1.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

STATES = (
    "assigned",
    "in_progress",
    "processing",
    "processing_failed",
    "expert_check",
    "building_units",
    "peer_review",
    "ingesting",
    "ingestion_failed",
    "ingested",
    "rejected",
    "cancelled",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _set_state_check(values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_assignments_state"), "assignments", schema="app", type_="check")
    op.create_check_constraint(
        op.f("ck_assignments_state"), "assignments", _in("state", values), schema="app"
    )


def upgrade() -> None:
    op.execute("UPDATE app.assignments SET state = 'peer_review' WHERE state = 'admin_review'")
    _set_state_check(STATES)
    op.drop_constraint(
        op.f("ck_assignments_required_approvals_min"), "assignments", schema="app", type_="check"
    )
    op.drop_column("assignments", "required_approvals", schema="app")

    op.create_table(
        "review_participants",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("expert_id", sa.Uuid(), nullable=False),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_review_participants_assignment_id_assignments"),
        ),
        sa.ForeignKeyConstraint(
            ["expert_id"], ["app.users.id"], name=op.f("fk_review_participants_expert_id_users")
        ),
        sa.PrimaryKeyConstraint("assignment_id", "expert_id", name=op.f("pk_review_participants")),
        schema="app",
    )
    op.create_index(
        op.f("ix_review_participants_expert_id"),
        "review_participants",
        ["expert_id"],
        schema="app",
    )
    op.execute(
        "INSERT INTO app.review_participants (assignment_id, expert_id, opened_at) "
        "SELECT assignment_id, reviewer_id, requested_at FROM app.review_requests "
        "WHERE stage = 'peer'"
    )
    op.drop_index(
        op.f("ix_review_requests_reviewer_id"), table_name="review_requests", schema="app"
    )
    op.drop_table("review_requests", schema="app")

    op.create_table(
        "unit_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("stance", sa.String(length=32), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in("stance", ("support", "challenge", "question")),
            name=op.f("ck_unit_comments_stance"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["app.users.id"], name=op.f("fk_unit_comments_author_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["app.unit_comments.id"],
            name=op.f("fk_unit_comments_parent_id_unit_comments"),
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["app.knowledge_units.id"],
            name=op.f("fk_unit_comments_unit_id_knowledge_units"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_unit_comments")),
        schema="app",
    )
    op.create_index(op.f("ix_unit_comments_unit_id"), "unit_comments", ["unit_id"], schema="app")
    op.create_index(
        op.f("ix_unit_comments_author_id"), "unit_comments", ["author_id"], schema="app"
    )

    op.create_table(
        "submission_votes",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("voter_id", sa.Uuid(), nullable=False),
        sa.Column("vote", sa.String(length=32), nullable=False),
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
            _in("vote", ("accept", "decline")), name=op.f("ck_submission_votes_vote")
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_submission_votes_assignment_id_assignments"),
        ),
        sa.ForeignKeyConstraint(
            ["voter_id"], ["app.users.id"], name=op.f("fk_submission_votes_voter_id_users")
        ),
        sa.PrimaryKeyConstraint(
            "assignment_id", "review_round", "voter_id", name=op.f("pk_submission_votes")
        ),
        schema="app",
    )

    op.add_column(
        "users",
        sa.Column("activity_seen_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_index(
        op.f("ix_audit_events_action_at"), "audit_events", ["action", "at"], schema="app"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_events_action_at"), table_name="audit_events", schema="app")
    op.drop_column("users", "activity_seen_at", schema="app")
    op.drop_table("submission_votes", schema="app")
    op.drop_index(op.f("ix_unit_comments_author_id"), table_name="unit_comments", schema="app")
    op.drop_index(op.f("ix_unit_comments_unit_id"), table_name="unit_comments", schema="app")
    op.drop_table("unit_comments", schema="app")

    op.create_table(
        "review_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_in("stage", ("admin", "peer")), name=op.f("ck_review_requests_stage")),
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
        op.f("ix_review_requests_reviewer_id"), "review_requests", ["reviewer_id"], schema="app"
    )
    op.execute(
        "INSERT INTO app.review_requests "
        "(id, assignment_id, reviewer_id, stage, requested_at, completed_at) "
        "SELECT gen_random_uuid(), assignment_id, expert_id, 'peer', opened_at, now() "
        "FROM app.review_participants"
    )
    op.drop_index(
        op.f("ix_review_participants_expert_id"), table_name="review_participants", schema="app"
    )
    op.drop_table("review_participants", schema="app")

    op.add_column(
        "assignments",
        sa.Column("required_approvals", sa.Integer(), server_default="1", nullable=False),
        schema="app",
    )
    op.create_check_constraint(
        op.f("ck_assignments_required_approvals_min"),
        "assignments",
        "required_approvals >= 1",
        schema="app",
    )
    _set_state_check(STATES[:6] + ("admin_review",) + STATES[6:])
