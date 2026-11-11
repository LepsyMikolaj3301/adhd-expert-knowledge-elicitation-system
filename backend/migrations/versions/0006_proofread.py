"""Proofread before review, review per answer, no Q1-Q3 gate.

- The gate is gone: `assignments.gate_passed_at` and `locked_highlights` go.
- Submitted answers are proofread (job `proofread`) and checked by their author
  (`proofread_check`) before review. New: `proofread_rounds` and `answer_revisions` (the original,
  the proposed and the author's text of each answer, per review round, with each line's links).
- Reviewers read and vote on answers, not units. New: `answer_comments`, `answer_votes`,
  `answer_decisions`. The unit tables stay as history.
- Units are cut only from approved answers, after review: `processing` now comes after
  `peer_review`, and `expert_check` and `building_units` are gone.

Rows move over:
- Every submission from `expert_check` on gets a round built from its submission and findings (one
  sentence per line, with its targets). `expert_check` and `building_units` land in
  `proofread_check`; the later states keep theirs, with the round submitted, so that their reviews
  can still be read.
- `processing` (waiting for the classifier) becomes `proofreading`, and every `process` or
  `build_units` job becomes a `proofread` job: retrying one proofreads the submission again.

The downgrade maps the states back and drops the new tables; their data has no older home.

Revision ID: 0006
Revises: 0005
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

OLD_STATES = (
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
NEW_STATES = (
    "assigned",
    "in_progress",
    "proofreading",
    "proofread_check",
    "peer_review",
    "processing",
    "processing_failed",
    "ingesting",
    "ingestion_failed",
    "ingested",
    "rejected",
    "cancelled",
)
OLD_KINDS = ("process", "build_units", "ingest")
NEW_KINDS = ("proofread", "process", "ingest")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _set_check(table: str, column: str, values: tuple[str, ...]) -> None:
    name = op.f(f"ck_{table}_{column}")
    op.drop_constraint(name, table, schema="app", type_="check")
    op.create_check_constraint(name, table, _in(column, values), schema="app")


def _drop_check(table: str, column: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{column}"), table, schema="app", type_="check")


def _jsonb(name: str) -> sa.Column:
    return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), nullable=False)


def _now(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _create_tables() -> None:
    op.create_table(
        "proofread_rounds",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        _jsonb("highlights"),
        _jsonb("flags"),
        _jsonb("passes"),
        sa.Column("classifier", sa.String(length=64), nullable=True),
        sa.Column("prompt", sa.String(length=64), nullable=True),
        _jsonb("feedback"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_proofread_rounds_assignment_id_assignments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("assignment_id", "review_round", name=op.f("pk_proofread_rounds")),
        schema="app",
    )
    op.create_table(
        "answer_revisions",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(length=8), nullable=False),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("proposed", sa.Text(), nullable=False),
        sa.Column("final", sa.Text(), nullable=False),
        _jsonb("lines"),
        _jsonb("dropped"),
        sa.ForeignKeyConstraint(
            ["assignment_id", "review_round"],
            ["app.proofread_rounds.assignment_id", "app.proofread_rounds.review_round"],
            name=op.f("fk_answer_revisions_assignment_id_review_round_proofread_rounds"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "assignment_id", "review_round", "question_id", name=op.f("pk_answer_revisions")
        ),
        schema="app",
    )
    op.create_table(
        "answer_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(length=8), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("stance", sa.String(length=32), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        _now("created_at"),
        sa.CheckConstraint(
            _in("stance", ("support", "challenge", "question")),
            name=op.f("ck_answer_comments_stance"),
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_answer_comments_assignment_id_assignments"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["app.users.id"], name=op.f("fk_answer_comments_author_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["app.answer_comments.id"],
            name=op.f("fk_answer_comments_parent_id_answer_comments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_answer_comments")),
        schema="app",
    )
    op.create_index(
        "ix_answer_comments_answer",
        "answer_comments",
        ["assignment_id", "review_round"],
        schema="app",
    )
    op.create_index(
        op.f("ix_answer_comments_author_id"), "answer_comments", ["author_id"], schema="app"
    )
    op.create_table(
        "answer_votes",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(length=8), nullable=False),
        sa.Column("voter_id", sa.Uuid(), nullable=False),
        sa.Column("vote", sa.String(length=32), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint(
            _in("vote", ("approve", "disapprove")), name=op.f("ck_answer_votes_vote")
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_answer_votes_assignment_id_assignments"),
        ),
        sa.ForeignKeyConstraint(
            ["voter_id"], ["app.users.id"], name=op.f("fk_answer_votes_voter_id_users")
        ),
        sa.PrimaryKeyConstraint(
            "assignment_id", "review_round", "question_id", "voter_id", name=op.f("pk_answer_votes")
        ),
        schema="app",
    )
    op.create_table(
        "answer_decisions",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(length=8), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        _now("decided_at"),
        sa.CheckConstraint(
            _in("decision", ("approve", "reject", "request_changes")),
            name=op.f("ck_answer_decisions_decision"),
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["app.assignments.id"],
            name=op.f("fk_answer_decisions_assignment_id_assignments"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["app.users.id"], name=op.f("fk_answer_decisions_reviewer_id_users")
        ),
        sa.PrimaryKeyConstraint(
            "assignment_id", "review_round", "question_id", name=op.f("pk_answer_decisions")
        ),
        schema="app",
    )


def _is_filed(question_id: str) -> bool:
    return question_id in ("Q1", "Q2", "Q3", "Q5")


def _seed_rounds() -> None:
    """A round for every submission that was being checked or reviewed, built from what it had:
    the submitted text, and the findings' sentences (one per line) with their targets."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT a.id, a.state, a.review_round, s.payload, f.record "
            "FROM app.assignments a "
            "JOIN app.submissions s ON s.assignment_id = a.id "
            "LEFT JOIN app.answer_findings f ON f.assignment_id = a.id "
            "WHERE a.state IN ('expert_check', 'building_units', 'peer_review', 'ingesting', "
            "'ingestion_failed', 'ingested', 'rejected')"
        )
    ).all()
    for assignment_id, state, review_round, payload, record in rows:
        record = record or {"highlights": [], "sentences": [], "flags": []}
        bind.execute(
            sa.text(
                "INSERT INTO app.proofread_rounds (assignment_id, review_round, version, "
                "highlights, flags, passes, feedback, submitted_at) VALUES (:a, :r, 1, "
                "CAST(:h AS jsonb), CAST(:f AS jsonb), CAST(:p AS jsonb), '[]'::jsonb, "
                + ("NULL" if state in ("expert_check", "building_units") else "now()")
                + ")"
            ),
            {
                "a": assignment_id,
                "r": review_round,
                "h": json.dumps(record["highlights"]),
                "f": json.dumps(record["flags"]),
                "p": json.dumps({"migrated": True}),
            },
        )
        for question_id, original in payload.get("answers", {}).items():
            sentences = [s for s in record["sentences"] if s["question_id"] == question_id]
            lines = [
                {
                    "text": " ".join(s["text"].split()),
                    "targets": s["targets"],
                    "assigned_by": s["assigned_by"],
                }
                for s in sentences
            ]
            filed = _is_filed(question_id) and lines
            final = "\n".join(line["text"] for line in lines) if filed else original
            bind.execute(
                sa.text(
                    "INSERT INTO app.answer_revisions (assignment_id, review_round, question_id, "
                    "original, proposed, final, lines, dropped) VALUES (:a, :r, :q, :o, :f, :f, "
                    "CAST(:l AS jsonb), '[]'::jsonb)"
                ),
                {
                    "a": assignment_id,
                    "r": review_round,
                    "q": question_id,
                    "o": original,
                    "f": final,
                    "l": json.dumps(lines if filed else []),
                },
            )


def upgrade() -> None:
    _create_tables()
    _seed_rounds()

    _drop_check("assignments", "state")
    op.execute(
        "UPDATE app.assignments SET state = 'proofread_check' "
        "WHERE state IN ('expert_check', 'building_units')"
    )
    op.execute("UPDATE app.assignments SET state = 'proofreading' WHERE state = 'processing'")
    op.create_check_constraint(
        op.f("ck_assignments_state"), "assignments", _in("state", NEW_STATES), schema="app"
    )
    _drop_check("jobs", "kind")
    op.execute("UPDATE app.jobs SET kind = 'proofread' WHERE kind IN ('process', 'build_units')")
    op.create_check_constraint(op.f("ck_jobs_kind"), "jobs", _in("kind", NEW_KINDS), schema="app")

    op.drop_column("assignments", "gate_passed_at", schema="app")
    op.drop_column("assignments", "locked_highlights", schema="app")


def downgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("locked_highlights", sa.Integer(), server_default=sa.text("0"), nullable=False),
        schema="app",
    )
    op.add_column(
        "assignments",
        sa.Column("gate_passed_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    _drop_check("jobs", "kind")
    op.execute("UPDATE app.jobs SET kind = 'build_units' WHERE kind = 'process'")
    op.execute("UPDATE app.jobs SET kind = 'process' WHERE kind = 'proofread'")
    op.create_check_constraint(op.f("ck_jobs_kind"), "jobs", _in("kind", OLD_KINDS), schema="app")
    _drop_check("assignments", "state")
    op.execute("UPDATE app.assignments SET state = 'building_units' WHERE state = 'processing'")
    op.execute("UPDATE app.assignments SET state = 'processing' WHERE state = 'proofreading'")
    op.execute("UPDATE app.assignments SET state = 'expert_check' WHERE state = 'proofread_check'")
    op.create_check_constraint(
        op.f("ck_assignments_state"), "assignments", _in("state", OLD_STATES), schema="app"
    )
    op.drop_table("answer_decisions", schema="app")
    op.drop_table("answer_votes", schema="app")
    op.drop_index(op.f("ix_answer_comments_author_id"), table_name="answer_comments", schema="app")
    op.drop_index("ix_answer_comments_answer", table_name="answer_comments", schema="app")
    op.drop_table("answer_comments", schema="app")
    op.drop_table("answer_revisions", schema="app")
    op.drop_table("proofread_rounds", schema="app")
