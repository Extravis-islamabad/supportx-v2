"""Vendor support: the grant's "Mask names too" tick (D-180, WP-057 S4c follow-up).

- support_grants.mask_names: when true, the engineer's session sees no person names either. E-mail
  and phone are always masked for support, whatever the grant says. Every existing grant keeps
  names visible (the server default fills them), as D-180 decided for the default.

The downgrade refuses while any tenant has a grant with the tick on, counting per tenant with
`app.tenant_id` set (forced RLS), as 0180 and 0187 do: dropping the column would show those
engineers the names the admin chose to hide.

Revision ID: 0188
Revises: 0194 (main's head now; re-pointed at its queue turn)
Created: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0188"
down_revision: str | None = "0194"  # main's head now; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "support_grants"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("mask_names", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE} WHERE mask_names) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has support grants that mask names', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - a fixed table name, no input


def downgrade() -> None:
    """Drops the tick only while no tenant has a grant with it on (see the module docstring)."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_column(TABLE, "mask_names")
