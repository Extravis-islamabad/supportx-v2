"""Static and dynamic asset groups (WP-049a s4; REQ-AST-028).

- `asset_groups`: a named group, static (its members are listed) or dynamic (its `filter` is a
  shared filter DSL tree over the asset list's fields, evaluated when shown, so an asset whose
  warranty date now matches is in it at once).
- `asset_group_members`: a static group's members.

The downgrade refuses while any tenant has a group (rule 5h).

Revision ID: 0113
Revises: 0112
Created: 2026-11-06
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0113"
down_revision: str | None = "0112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str) -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "asset_groups",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("filter", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint("kind IN ('static', 'dynamic')", name=op.f("ck_asset_groups_kind")),
        sa.CheckConstraint(
            "(kind = 'dynamic') = (filter IS NOT NULL)", name=op.f("ck_asset_groups_filter")
        ),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 200", name=op.f("ck_asset_groups_name")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_asset_groups_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_groups")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_groups_tenant_id_id"),
    )
    op.create_index(
        "uq_asset_groups_name",
        "asset_groups",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("asset_groups")
    grant_app("asset_groups", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("asset_groups")

    op.create_table(
        "asset_group_members",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_asset_group_members_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["asset_groups.tenant_id", "asset_groups.id"],
            name="fk_asset_group_members_group",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_group_members_asset",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "group_id", "asset_id", name=op.f("pk_asset_group_members")
        ),
    )
    op.create_index(
        "ix_asset_group_members_asset", "asset_group_members", ["tenant_id", "asset_id"]
    )
    enable_tenant_rls("asset_group_members")
    # Removing a member from a static group is a real delete of the link (no history of its own:
    # the group's history says who left).
    grant_app("asset_group_members", ("SELECT", "INSERT", "DELETE"))


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM asset_groups) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has asset groups (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops the tables only while no tenant has a group; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table("asset_group_members")
    op.drop_table("asset_groups")
