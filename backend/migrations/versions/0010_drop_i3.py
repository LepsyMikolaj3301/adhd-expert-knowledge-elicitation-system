"""I3 (the unit's text with the patient's words) is gone: nothing searched it.

- `app.knowledge_units.embed_text_combined` goes.
- `chips.finding_units` loses `embed_text_combined`, `embedding_combined` and `sparse_combined`.

The downgrade adds the columns back, empty (nullable): the texts and vectors are not rebuilt. A
unit ingested after this migration has no I3 to put back; re-ingest it with the older code.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

CHIPS_COLUMNS = ("embed_text_combined", "embedding_combined", "sparse_combined")


def upgrade() -> None:
    op.execute("ALTER TABLE app.knowledge_units DROP COLUMN IF EXISTS embed_text_combined")
    for column in CHIPS_COLUMNS:
        op.execute(f"ALTER TABLE chips.finding_units DROP COLUMN IF EXISTS {column}")


def downgrade() -> None:
    op.execute("ALTER TABLE app.knowledge_units ADD COLUMN IF NOT EXISTS embed_text_combined text")
    op.execute("ALTER TABLE chips.finding_units ADD COLUMN IF NOT EXISTS embed_text_combined text")
    op.execute(
        "ALTER TABLE chips.finding_units ADD COLUMN IF NOT EXISTS embedding_combined vector(1024)"
    )
    op.execute(
        "ALTER TABLE chips.finding_units "
        "ADD COLUMN IF NOT EXISTS sparse_combined sparsevec(1048576)"
    )
