"""Declining balance's factor per product type (D-157 item 3), number 0136.

Expand only, no data step:
- `asset_product_types.depreciation_factor`: the factor declining balance applies to the
  straight-line rate for the assets of that type (2 by default, so declining balance is the
  usual 200 %; between 0 and 10, more than 0). Straight line, the default method when neither
  the asset nor its product names one, has no factor.

The downgrade drops it only while every tenant's types keep the default factor; otherwise it
stops, per tenant with app.tenant_id set (RLS FORCE), and keeps the data (rule 5h).

Revision ID: 0136
Revises: 0137
Created: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0136"
down_revision: str | None = "0137"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FACTOR = sa.Numeric(4, 2)
DEFAULT = "2"


def upgrade() -> None:
    """Adds the factor, 2 for every type (existing ones included)."""
    op.add_column(
        "asset_product_types",
        sa.Column("depreciation_factor", FACTOR, server_default=DEFAULT, nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_asset_product_types_depreciation_factor"),
        "asset_product_types",
        "depreciation_factor > 0 AND depreciation_factor <= 10",
    )


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (
            SELECT 1 FROM asset_product_types WHERE depreciation_factor <> {DEFAULT}
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has product types with their own declining balance factor (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed names, no input


def downgrade() -> None:
    """Drops the factor only while no tenant changed one; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_constraint(
        op.f("ck_asset_product_types_depreciation_factor"), "asset_product_types", type_="check"
    )
    op.drop_column("asset_product_types", "depreciation_factor")
