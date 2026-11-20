"""Where experts agree: groups of overlapping highlights, and the embedding model of each unit.

- `chips.fragment_groups` and `chips.fragment_group_members`: derived, recomputed per vignette
  version (app.knowledge.agreement). Existing data is filled by `python -m app.cli
  recompute-agreement`; until then retrieval simply finds no groups.
- `chips.finding_units.embedding_model`: which model made `embedding`. Existing rows were made
  with bge-m3.

A frozen copy of the end of scripts/db/chips_schema.sql; keep the two in step. The downgrade
leaves them in place, as for every `chips` table.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chips.finding_units ADD COLUMN IF NOT EXISTS embedding_model text")
    op.execute(
        "UPDATE chips.finding_units SET embedding_model = 'bge-m3' WHERE embedding_model IS NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chips.fragment_groups (
            id bigserial PRIMARY KEY,
            vignette_id text NOT NULL, vignette_version integer NOT NULL,
            span int4range NOT NULL,
            n_answered integer NOT NULL,
            n_attending integer NOT NULL,
            n_toward integer NOT NULL, n_away integer NOT NULL, n_neutral integer NOT NULL,
            n_unclear integer NOT NULL, n_mixed integer NOT NULL,
            label text NOT NULL,
            rule_version integer NOT NULL,
            computed_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS fragment_groups_vignette_idx "
        "ON chips.fragment_groups (vignette_id, vignette_version)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chips.fragment_group_members (
            group_id bigint NOT NULL REFERENCES chips.fragment_groups ON DELETE CASCADE,
            highlight_id text NOT NULL REFERENCES chips.highlights ON DELETE CASCADE,
            expert_id text NOT NULL,
            PRIMARY KEY (group_id, highlight_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS fragment_group_members_highlight_idx "
        "ON chips.fragment_group_members (highlight_id)"
    )


def downgrade() -> None:
    # Like migration 0003, this never deletes anything from `chips`: the tables are derived data
    # and the column is harmless, and upgrading again finds them and does nothing.
    pass
