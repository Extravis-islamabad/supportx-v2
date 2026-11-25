"""Item prices, the request's estimate and charge-back (WP-047b S1; REQ-CAT-020, -021, D-184), 0205.

Expand only, no data step. All money is the tenant's base currency (D-164).

On `catalog_items`:
- `price` and `internal_cost` (Numeric(14, 2), NULL: none; at least 0);
- `price_period`: `once`, `month` or `year` (REQ-CAT-020 AC2; default once);
- `charge_to`: who a fulfilled request charges (REQ-CAT-021): the requested-for person's
  department (default), or a form answer naming a cost centre (`charge_question_key`).

On `catalog_settings`: `requesters_see_prices` (D-184: requesters see prices and the estimate
only when the tenant turns it on; default off).

On `work_items` (service requests only; other types leave them NULL):
- `estimated_cost`, `estimate_period`: the estimate snapshotted at submission and when the answers
  or the quantity change, never on later item edits (D-184);
- `charge_department_id`, `charge_cost_centre`, `charged_amount`, `charged_at`: frozen when the
  request is fulfilled (REQ-CAT-021 AC1), so a later move of the person changes nothing.

Reversible; RLS unchanged (existing tables).

Revision ID: 0205
Revises: 0201
Created: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import grant_report_columns, revoke_report

revision: str = "0205"
# On main's head 0202 for now; re-pointed at its queue turn (after #630's 0204).
down_revision: str | None = "0201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ITEMS, SETTINGS, TABLE = "catalog_items", "catalog_settings", "work_items"
# The charge-back report names its items (lane C's condition 3): supportx_report reads only an
# item's ID and names, never its descriptions or forms (free text).
ITEM_REPORT_COLUMNS = ("id", "tenant_id", "names", "deleted_at")
MONEY = sa.Numeric(14, 2)
PERIODS = "('once', 'month', 'year')"


def upgrade() -> None:
    """The item's price and charge-to, the tenant's setting, the request's estimate and charge."""
    op.add_column(ITEMS, sa.Column("price", MONEY, nullable=True))
    op.add_column(ITEMS, sa.Column("internal_cost", MONEY, nullable=True))
    op.add_column(
        ITEMS, sa.Column("price_period", sa.String(10), nullable=False, server_default="once")
    )
    op.add_column(
        ITEMS,
        sa.Column(
            "charge_to", sa.String(30), nullable=False, server_default="requested_for_department"
        ),
    )
    op.add_column(ITEMS, sa.Column("charge_question_key", sa.String(40), nullable=True))
    op.create_check_constraint(
        op.f("ck_catalog_items_money_not_negative"),
        ITEMS,
        "(price IS NULL OR price >= 0) AND (internal_cost IS NULL OR internal_cost >= 0)",
    )
    op.create_check_constraint(
        op.f("ck_catalog_items_price_period_code"), ITEMS, f"price_period IN {PERIODS}"
    )
    op.create_check_constraint(
        op.f("ck_catalog_items_charge_to_code"),
        ITEMS,
        "charge_to IN ('requested_for_department', 'question')",
    )
    op.add_column(
        SETTINGS,
        sa.Column("requesters_see_prices", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(TABLE, sa.Column("estimated_cost", MONEY, nullable=True))
    op.add_column(TABLE, sa.Column("estimate_period", sa.String(10), nullable=True))
    op.add_column(TABLE, sa.Column("charge_department_id", sa.Uuid(), nullable=True))
    op.add_column(TABLE, sa.Column("charge_cost_centre", sa.String(100), nullable=True))
    op.add_column(TABLE, sa.Column("charged_amount", MONEY, nullable=True))
    op.add_column(TABLE, sa.Column("charged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_items_money_not_negative"),
        TABLE,
        "(estimated_cost IS NULL OR estimated_cost >= 0)"
        " AND (charged_amount IS NULL OR charged_amount >= 0)",
    )
    op.create_check_constraint(
        op.f("ck_work_items_estimate_period_code"),
        TABLE,
        f"estimate_period IS NULL OR estimate_period IN {PERIODS}",
    )
    # The monthly charge-back export reads fulfilled requests by month (REQ-CAT-021 AC2).
    op.create_index(
        "ix_work_items_charged",
        TABLE,
        ["tenant_id", "charged_at"],
        postgresql_where=sa.text("charged_at IS NOT NULL"),
    )
    grant_report_columns(ITEMS, ITEM_REPORT_COLUMNS)


def downgrade() -> None:
    """Back to before (the columns hold only what this added)."""
    revoke_report(ITEMS)
    op.drop_index("ix_work_items_charged", table_name=TABLE)
    op.drop_constraint(op.f("ck_work_items_estimate_period_code"), TABLE, type_="check")
    op.drop_constraint(op.f("ck_work_items_money_not_negative"), TABLE, type_="check")
    for column in (
        "charged_at",
        "charged_amount",
        "charge_cost_centre",
        "charge_department_id",
        "estimate_period",
        "estimated_cost",
    ):
        op.drop_column(TABLE, column)
    op.drop_column(SETTINGS, "requesters_see_prices")
    op.drop_constraint(op.f("ck_catalog_items_charge_to_code"), ITEMS, type_="check")
    op.drop_constraint(op.f("ck_catalog_items_price_period_code"), ITEMS, type_="check")
    op.drop_constraint(op.f("ck_catalog_items_money_not_negative"), ITEMS, type_="check")
    for column in ("charge_question_key", "charge_to", "price_period", "internal_cost", "price"):
        op.drop_column(ITEMS, column)
