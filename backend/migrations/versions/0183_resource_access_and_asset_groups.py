"""Fine-grained access to assets and CIs, and the assets' managing group (ADR-053; D-172), 0183.

Expand only, no data step:
- `role_resource_access` (RLS, audited actors): one role's rule narrowing which assets or CIs it
  shows (`resource` asset or ci, `criteria` JSONB). Rules only narrow, never grant; a removed
  rule is soft-deleted.
- `assets.managed_by_group_id`: the support group managing an asset, the real `group` scope
  (D-172, every edition). A plain ID of organization's group, checked through its interface as
  the site is (no foreign key across modules), indexed tenant-first.

The type subtree a rule names is one SQL predicate on the existing parent links (a recursive
query on the small type tables, then the indexed `type_id` match): no path column needed.

The downgrade refuses while any tenant has a rule or a managed asset (rule 5h): they are admins'
decisions about who sees what.

Revision ID: 0183
Revises: 0179
Created: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0183"
down_revision: str | None = "0179"  # main's head; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "role_resource_access"
ASSETS = "assets"

# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE})
           OR EXISTS (SELECT 1 FROM {ASSETS} WHERE managed_by_group_id IS NOT NULL)
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % uses fine-grained access (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def upgrade() -> None:
    """The rules table and the assets' managing group."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("resource", sa.String(10), nullable=False),
        sa.Column("criteria", JSONB(), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("resource IN ('asset', 'ci')", name=op.f(f"ck_{TABLE}_resource_code")),
        sa.CheckConstraint(
            "jsonb_typeof(criteria) = 'object'", name=op.f(f"ck_{TABLE}_criteria_object")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            ondelete="CASCADE",
            name="fk_role_resource_access_role",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "ix_rra_tenant_role_resource",
        TABLE,
        ["tenant_id", "role_id", "resource"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))
    op.add_column(ASSETS, sa.Column("managed_by_group_id", sa.Uuid(), nullable=True))
    op.create_index("ix_assets_managed_by_group", ASSETS, ["tenant_id", "managed_by_group_id"])


def downgrade() -> None:
    """Back to before (stops while any tenant uses fine-grained access or managing groups)."""
    op.execute(GUARD)
    op.drop_index("ix_assets_managed_by_group", table_name=ASSETS)
    op.drop_column(ASSETS, "managed_by_group_id")
    op.drop_table(TABLE)
