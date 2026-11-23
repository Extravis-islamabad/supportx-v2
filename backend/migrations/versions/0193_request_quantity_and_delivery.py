"""A service request's quantity, needed-by date and expected delivery (WP-047a S1), 0193.

REQ-SR-014 and REQ-SR-015. Expand only, no data step.

On `catalog_items`, what the item asks:

- `max_quantity`: the most one request may ask for (1..10,000); NULL: the item asks no
  quantity, as every item before this.
- `asks_needed_by`: whether the form asks when it is needed (default false).

On `work_items`, three nullable columns, set on service requests only (other types leave them
NULL):

- `quantity`: how many of the item (1..10,000; the item's own maximum is checked by the
  service). NULL is one, as every request raised before this.
- `needed_by`: when the requester needs it, if the item asks.
- `expected_delivery_at`: when it should be delivered, from the item's SLA and its calendar;
  worked out on create and again when approval completes. The "needed earlier than expected"
  flag is read from the two dates, never stored.

The downgrade drops the five columns: the quantities and dates go, the items and requests stay.

Revision ID: 0193
Revises: 0187
Created: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0193"
down_revision: str | None = "0187"  # main's head at its queue turn (… 0184 → 0187)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_items"
ITEMS = "catalog_items"
QUANTITY_MAX = 10_000


def upgrade() -> None:
    """Add the item's two settings, the request's three columns, and the range checks."""
    op.add_column(ITEMS, sa.Column("max_quantity", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_catalog_items_max_quantity_range"),
        ITEMS,
        f"max_quantity IS NULL OR (max_quantity >= 1 AND max_quantity <= {QUANTITY_MAX})",
    )
    op.add_column(
        ITEMS,
        sa.Column("asks_needed_by", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(TABLE, sa.Column("quantity", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_items_quantity_range"),
        TABLE,
        f"quantity IS NULL OR (quantity >= 1 AND quantity <= {QUANTITY_MAX})",
    )
    op.add_column(TABLE, sa.Column("needed_by", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        TABLE, sa.Column("expected_delivery_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Drop the five columns (each check goes with its column)."""
    op.drop_column(TABLE, "expected_delivery_at")
    op.drop_column(TABLE, "needed_by")
    op.drop_column(TABLE, "quantity")
    op.drop_column(ITEMS, "asks_needed_by")
    op.drop_column(ITEMS, "max_quantity")
