"""A short description of the patient on every vignette version, shown to experts.

Existing versions get an empty summary: a draft must have one to be published, but versions
that are already published keep working.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vignette_versions",
        sa.Column("patient_summary", sa.Text(), server_default="", nullable=False),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("vignette_versions", "patient_summary", schema="app")
