"""Who holds an asset, what it was held by, and how assets relate (WP-049a s4; REQ-AST-018,
019, 026, 027).

- `assets` gains its holder: a person (`owner_user_id`, a same-tenant foreign key to users), a
  department (a plain ID, organization's record) and a parent asset (`parent_asset_id`, the
  workstation a monitor is fitted to). All empty for every existing asset: nothing changes.
- `asset_assignments`: one row per holding, from when to when, by whom and from where (the
  assignment history, never rewritten; a dispute never removes it).
- `asset_relationships`: typed links between two assets (connected to, depends on, runs on,
  backs up), shown from both ends; removing one keeps it (soft delete).

The downgrade refuses while any tenant has an assignment, a relationship or an asset with a
holder (rule 5h).

Revision ID: 0111
Revises: 0125
Created: 2026-11-06
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0111"
down_revision: str | None = "0125"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The same lists as app/modules/assets/domain/ownership.py.
HOLDER_KINDS = ("user", "department", "asset")
RELATIONSHIP_KINDS = ("connected_to", "depends_on", "runs_on", "backs_up")


def _timestamp(name: str) -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _entity_columns() -> list["sa.Column[Any]"]:  # Any: uuid, time and integer columns together
    return [
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column("assets", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    op.add_column("assets", sa.Column("department_id", sa.Uuid(), nullable=True))
    op.add_column("assets", sa.Column("parent_asset_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_assets_owner_user",
        "assets",
        "users",
        ["tenant_id", "owner_user_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_assets_parent_asset",
        "assets",
        "assets",
        ["tenant_id", "parent_asset_id"],
        ["tenant_id", "id"],
    )
    op.create_check_constraint(
        "ck_assets_not_own_parent", "assets", "parent_asset_id IS NULL OR parent_asset_id <> id"
    )
    op.create_index("ix_assets_owner_user", "assets", ["tenant_id", "owner_user_id"])
    op.create_index("ix_assets_department", "assets", ["tenant_id", "department_id"])
    op.create_index("ix_assets_parent", "assets", ["tenant_id", "parent_asset_id"])

    op.create_table(
        "asset_assignments",
        *_entity_columns(),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("holder_kind", sa.String(20), nullable=False),
        sa.Column("holder_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.CheckConstraint(
            _in("holder_kind", HOLDER_KINDS), name=op.f("ck_asset_assignments_holder_kind")
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name=op.f("ck_asset_assignments_dates")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_asset_assignments_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_assignments_asset",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_assignments")),
    )
    op.create_index(
        "ix_asset_assignments_asset", "asset_assignments", ["tenant_id", "asset_id", "started_at"]
    )
    op.create_index(
        "ix_asset_assignments_holder",
        "asset_assignments",
        ["tenant_id", "holder_kind", "holder_id", "started_at"],
    )
    # At most one current holding per asset.
    op.create_index(
        "uq_asset_assignments_current",
        "asset_assignments",
        ["tenant_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL AND deleted_at IS NULL"),
    )
    enable_tenant_rls("asset_assignments")
    grant_app("asset_assignments", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("asset_assignments")

    op.create_table(
        "asset_relationships",
        *_entity_columns(),
        sa.Column("from_asset_id", sa.Uuid(), nullable=False),
        sa.Column("to_asset_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.CheckConstraint(
            _in("kind", RELATIONSHIP_KINDS), name=op.f("ck_asset_relationships_kind")
        ),
        sa.CheckConstraint(
            "from_asset_id <> to_asset_id", name=op.f("ck_asset_relationships_not_self")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_asset_relationships_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "from_asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_relationships_from",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "to_asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_relationships_to",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_relationships")),
    )
    op.create_index(
        "uq_asset_relationships_link",
        "asset_relationships",
        ["tenant_id", "from_asset_id", "to_asset_id", "kind"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_asset_relationships_to", "asset_relationships", ["tenant_id", "to_asset_id"]
    )
    enable_tenant_rls("asset_relationships")
    grant_app("asset_relationships", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("asset_relationships")


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM asset_assignments)
           OR EXISTS (SELECT 1 FROM asset_relationships)
           OR EXISTS (
               SELECT 1 FROM assets
                WHERE owner_user_id IS NOT NULL OR department_id IS NOT NULL
                   OR parent_asset_id IS NOT NULL
           ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has asset holders (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops what 0111 added only while no tenant uses it; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table("asset_relationships")
    op.drop_table("asset_assignments")
    op.drop_index("ix_assets_parent", table_name="assets")
    op.drop_index("ix_assets_department", table_name="assets")
    op.drop_index("ix_assets_owner_user", table_name="assets")
    op.drop_constraint("ck_assets_not_own_parent", "assets", type_="check")
    op.drop_constraint("fk_assets_parent_asset", "assets", type_="foreignkey")
    op.drop_constraint("fk_assets_owner_user", "assets", type_="foreignkey")
    op.drop_column("assets", "parent_asset_id")
    op.drop_column("assets", "department_id")
    op.drop_column("assets", "owner_user_id")
