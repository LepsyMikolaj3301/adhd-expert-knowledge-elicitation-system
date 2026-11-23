"""Who confirmed the privacy notice: `app.users.privacy_version` and `privacy_accepted_at`.

Both NULL until the user presses "I understand". Each confirmation is also an audit event
(`privacy_accepted`), so the history survives a newer notice overwriting these columns.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("privacy_version", sa.String(32), nullable=True), schema="app")
    op.add_column(
        "users",
        sa.Column("privacy_accepted_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("users", "privacy_accepted_at", schema="app")
    op.drop_column("users", "privacy_version", schema="app")
