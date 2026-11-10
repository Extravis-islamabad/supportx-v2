"""Assets linked to work items (REQ-AST-025), number 0127 from the coordinator.

Expand only, no data step:
- `work_item_assets` (RLS): one row per asset linked to a record, soft-deleted when unlinked, so
  history keeps who linked what. Work items never read asset tables (CLAUDE.md rule e): the asset
  is only an ID here, named through `assets.asset_refs`, so there is no foreign key to assets.
  One live link per (record, asset).

The downgrade drops the table while no link exists; otherwise it stops and keeps the data
(rule 5h).

Revision ID: 0127
Revises: 0126
Created: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0127"
down_revision: str | None = "0126"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_assets"
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has linked assets (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - a fixed table name, no input


def upgrade() -> None:
    """The link table."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(20), server_default="ui", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name=op.f(f"fk_{TABLE}_work_item"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_wia_tenant_item_asset",
        TABLE,
        ["tenant_id", "work_item_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # The assets module's "linked to my tickets" scope asks by asset (D-153).
    op.create_index(
        "ix_wia_tenant_asset",
        TABLE,
        ["tenant_id", "asset_id", "work_item_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    """Drops the table while no asset is linked (stops otherwise)."""
    op.execute(GUARD)
    op.drop_index("ix_wia_tenant_asset", table_name=TABLE)
    op.drop_index("uq_wia_tenant_item_asset", table_name=TABLE)
    op.drop_table(TABLE)
