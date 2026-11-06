"""Review rounds: a reviewer can ask the author for changes, and the units are cut again.

- `assignments.review_round` and `knowledge_units.review_round`: which cut of the units a row
  belongs to. Ordinals now start at 1 in each round.
- Units of an earlier round get the status `superseded`; decisions get the value `request_changes`.
- `knowledge_units.question_id` goes: the verbatim stub that used it is gone.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UNIT_STATUSES = ("pending", "approved", "rejected", "ingested")
DECISIONS = ("approve", "reject")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("review_round", sa.Integer(), server_default="1", nullable=False),
        schema="app",
    )
    op.add_column(
        "knowledge_units",
        sa.Column("review_round", sa.Integer(), server_default="1", nullable=False),
        schema="app",
    )
    op.drop_constraint(
        op.f("uq_knowledge_units_assignment_id_ordinal"),
        "knowledge_units",
        schema="app",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_knowledge_units_assignment_id_review_round_ordinal"),
        "knowledge_units",
        ["assignment_id", "review_round", "ordinal"],
        schema="app",
    )
    op.drop_column("knowledge_units", "question_id", schema="app")

    op.drop_constraint(
        op.f("ck_knowledge_units_status"), "knowledge_units", schema="app", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_knowledge_units_status"),
        "knowledge_units",
        _in("status", (*UNIT_STATUSES, "superseded")),
        schema="app",
    )
    op.drop_constraint(
        op.f("ck_unit_decisions_decision"), "unit_decisions", schema="app", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_unit_decisions_decision"),
        "unit_decisions",
        _in("decision", (*DECISIONS, "request_changes")),
        schema="app",
    )


def downgrade() -> None:
    # Rounds can't be represented before this migration, so the history is flattened: the
    # superseded units become rejected ones, and a request for changes a rejection.
    op.execute("UPDATE app.knowledge_units SET status = 'rejected' WHERE status = 'superseded'")
    op.execute(
        "UPDATE app.unit_decisions SET decision = 'reject' WHERE decision = 'request_changes'"
    )
    op.drop_constraint(
        op.f("ck_unit_decisions_decision"), "unit_decisions", schema="app", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_unit_decisions_decision"),
        "unit_decisions",
        _in("decision", DECISIONS),
        schema="app",
    )
    op.drop_constraint(
        op.f("ck_knowledge_units_status"), "knowledge_units", schema="app", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_knowledge_units_status"),
        "knowledge_units",
        _in("status", UNIT_STATUSES),
        schema="app",
    )
    op.add_column(
        "knowledge_units",
        sa.Column("question_id", sa.String(length=8), nullable=True),
        schema="app",
    )
    # Two rounds' units can share an ordinal: renumber them before the old constraint returns.
    op.execute(
        "UPDATE app.knowledge_units u SET ordinal = n.rn FROM ("
        "SELECT id, row_number() OVER (PARTITION BY assignment_id "
        "ORDER BY review_round, ordinal) AS rn FROM app.knowledge_units) n WHERE u.id = n.id"
    )
    op.drop_constraint(
        op.f("uq_knowledge_units_assignment_id_review_round_ordinal"),
        "knowledge_units",
        schema="app",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_knowledge_units_assignment_id_ordinal"),
        "knowledge_units",
        ["assignment_id", "ordinal"],
        schema="app",
    )
    op.drop_column("knowledge_units", "review_round", schema="app")
    op.drop_column("assignments", "review_round", schema="app")
