"""Group dashboards (D-152): a dashboard can belong to a support group.

A group dashboard is seen by the group's members and changed by the group's lead or by
`dashboards.manage_defaults`. `group_id` is a plain uuid with no foreign key: groups belong to
the organization module (rule 5e), and the service checks the group through organization's
public interface when it saves. A group dashboard is never also shared with everyone
(`ck_dashboards_group_or_shared`). If its group is deleted, it falls back to its owner's private
dashboards; dashboards.manage_defaults holders see it marked "group removed".

Expand only: a new nullable column, a check, and a partial index whose first column is
tenant_id. The downgrade drops them. It refuses while group dashboards exist, because dropping
the column would turn them into private dashboards silently (rule 5h).

Revision ID: 0123
Revises: 0121
Created: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0123"
down_revision: str | None = "0121"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add dashboards.group_id, its check and its index."""
    op.add_column("dashboards", sa.Column("group_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        op.f("ck_dashboards_group_or_shared"),
        "dashboards",
        "group_id IS NULL OR NOT shared",
    )
    op.create_index(
        "ix_dashboards_tenant_group",
        "dashboards",
        ["tenant_id", "group_id", "name"],
        postgresql_where=sa.text("group_id IS NOT NULL AND deleted_at IS NULL"),
    )


# Per tenant with app.tenant_id set: dashboards force RLS, so a check without it sees no rows.
_REFUSE_IF_ANY_GROUP_DASHBOARD = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM dashboards WHERE group_id IS NOT NULL) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has group dashboards (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drop them again, only while no dashboard belongs to a group."""
    op.execute(_REFUSE_IF_ANY_GROUP_DASHBOARD)
    op.drop_index("ix_dashboards_tenant_group", table_name="dashboards")
    op.drop_constraint(op.f("ck_dashboards_group_or_shared"), "dashboards", type_="check")
    op.drop_column("dashboards", "group_id")
