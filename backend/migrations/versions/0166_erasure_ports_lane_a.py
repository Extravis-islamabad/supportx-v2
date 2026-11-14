"""Lane A's erasure ports (ADR-052 §4; D-171), 0166.

Expand only, no data step:
- DELETE for the app role on eight tables of a person's private rows. Erasure removes those for
  good (CLAUDE.md §6: a hard delete only through erasure; a soft delete still holds the data).
  Everywhere else they stay soft-deleted or kept: tests/test_erasure_deletes_lane_a.py fails on
  a DELETE outside the erasure ports and the purges already there.
- Two indexes on work_items for the erasure's "records this person requested" (lane B's #504
  note): requester and on-behalf-of, each led by the tenant. work_items is large, so both are
  built CONCURRENTLY (no write lock), outside the migration's transaction, as 0135 does.

The downgrade puts the old grants back and drops the indexes; neither holds data.

Revision ID: 0166
Revises: 0162 (main's head while building; re-pointed at its queue turn)
Created: 2026-11-14
"""

from collections.abc import Sequence

from alembic import op

from migrations.helpers import grant_app

revision: str = "0166"
down_revision: str | None = "0162"  # main's head while building; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Today SELECT, INSERT, UPDATE only (soft delete); erasure needs DELETE too.
PRIVATE_TABLES = (
    "work_item_followers",
    "work_item_list_settings",
    "work_item_reminders",
    "work_item_timers",
    "work_item_views",
    "work_item_reply_templates",
    "notification_preferences",
    "technician_availability",
)
REQUESTER_INDEX = "ix_wi_tenant_requester_id"
ON_BEHALF_INDEX = "ix_wi_tenant_on_behalf_id"


def upgrade() -> None:
    """The DELETE grants, then the two indexes (concurrently)."""
    for table in PRIVATE_TABLES:
        grant_app(table)  # SELECT, INSERT, UPDATE, DELETE
    # CONCURRENTLY cannot run inside a transaction block: alembic's autocommit block.
    with op.get_context().autocommit_block():
        op.create_index(
            REQUESTER_INDEX,
            "work_items",
            ["tenant_id", "requester_id", "id"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            ON_BEHALF_INDEX,
            "work_items",
            ["tenant_id", "on_behalf_of_id", "id"],
            postgresql_where="on_behalf_of_id IS NOT NULL",
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    """The indexes dropped (concurrently), the grants back to soft delete only."""
    with op.get_context().autocommit_block():
        op.drop_index(
            ON_BEHALF_INDEX, table_name="work_items", postgresql_concurrently=True, if_exists=True
        )
        op.drop_index(
            REQUESTER_INDEX, table_name="work_items", postgresql_concurrently=True, if_exists=True
        )
    for table in PRIVATE_TABLES:
        grant_app(table, ("SELECT", "INSERT", "UPDATE"))
