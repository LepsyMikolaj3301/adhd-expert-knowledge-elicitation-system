"""The admin can remove ingested units (one, or all of an expert's), and a `refit` job refits BM25
over the whole corpus afterwards. A corpus job belongs to no assignment.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

OLD_UNIT_STATUSES = ("pending", "approved", "rejected", "ingested", "superseded")
NEW_UNIT_STATUSES = (*OLD_UNIT_STATUSES, "removed")
OLD_KINDS = ("proofread", "process", "ingest")
NEW_KINDS = (*OLD_KINDS, "refit")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _set_check(table: str, column: str, values: tuple[str, ...]) -> None:
    name = op.f(f"ck_{table}_{column}")
    op.drop_constraint(name, table, schema="app", type_="check")
    op.create_check_constraint(name, table, _in(column, values), schema="app")


def upgrade() -> None:
    _set_check("knowledge_units", "status", NEW_UNIT_STATUSES)
    _set_check("jobs", "kind", NEW_KINDS)
    op.alter_column("jobs", "assignment_id", nullable=True, schema="app")


def downgrade() -> None:
    op.execute("DELETE FROM app.jobs WHERE assignment_id IS NULL OR kind = 'refit'")
    op.alter_column("jobs", "assignment_id", nullable=False, schema="app")
    _set_check("jobs", "kind", OLD_KINDS)
    # The chips rows are gone; marking them rejected keeps them out of any re-ingestion.
    op.execute("UPDATE app.knowledge_units SET status = 'rejected' WHERE status = 'removed'")
    _set_check("knowledge_units", "status", OLD_UNIT_STATUSES)
