"""No synthetic flag: every expert and every answer is treated the same.

- `app.users.is_synthetic` and the check that tied it to a `SYN-` pseudonym go.
- `chips.experts`, `chips.elicitation_sessions` and `chips.finding_units` lose `is_synthetic`.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

CHIPS_TABLES = ("experts", "elicitation_sessions", "finding_units")


def upgrade() -> None:
    op.drop_constraint(op.f("ck_users_synthetic_pseudonym"), "users", schema="app", type_="check")
    op.drop_column("users", "is_synthetic", schema="app")
    for table in CHIPS_TABLES:
        op.execute(f"ALTER TABLE chips.{table} DROP COLUMN IF EXISTS is_synthetic")


def downgrade() -> None:
    for table in CHIPS_TABLES:
        op.execute(
            f"ALTER TABLE chips.{table} "
            "ADD COLUMN IF NOT EXISTS is_synthetic boolean NOT NULL DEFAULT false"
        )
    op.add_column(
        "users",
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="app",
    )
    op.execute("UPDATE app.users SET is_synthetic = (pseudonym LIKE 'SYN-%')")
    op.create_check_constraint(
        op.f("ck_users_synthetic_pseudonym"),
        "users",
        "is_synthetic = (pseudonym LIKE 'SYN-%')",
        schema="app",
    )
