"""An index on field_changes by save: (tenant_id, change_id).

The lifecycle audit (WP-064) and the 409 messages read all the rows of one save by its change
ID; without this index each such read scans the record's whole history. field_changes is the
largest table, so the index is built CONCURRENTLY (no write lock), outside the migration's
transaction, and dropped the same way. Nothing else changes; no data step.

Revision ID: 0135
Revises: 0134
Created: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0135"
down_revision: str | None = "0134"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_field_changes_change"


def upgrade() -> None:
    # CONCURRENTLY cannot run inside a transaction block: alembic's autocommit block.
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX,
            "field_changes",
            ["tenant_id", "change_id"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    """Drops only the index (CONCURRENTLY); the table and its rows stay."""
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX, table_name="field_changes", postgresql_concurrently=True, if_exists=True
        )
