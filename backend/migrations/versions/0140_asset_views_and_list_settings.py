"""Asset views and the shared list-settings store (WP-049b s4a).

REQ-AST-047 (asset list, product type tree, views), after REQ-INC-104, 106, 107. Expand only,
no data step:
- `list_settings`: per person, list and view, the columns (with widths), sort, page size and a
  favourite star; a saved view is such a row keyed `custom:<id>`, with a name and the list's own
  filter. Generic (app/shared/list_settings); assets use it first.
- `ix_assets_type_updated`: the asset list filtered by a product type tree node, newest change
  first (the default sort), over live assets only (AC1, AC3).

The downgrade refuses while any tenant keeps a list setting, per tenant with app.tenant_id set
(rule 5h); the index holds no data and is dropped.

Revision ID: 0140
Revises: 0136
Created: 2026-11-11
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0140"
down_revision: str | None = "0136"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "list_settings"


def _timestamp(name: str) -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _entity() -> list["sa.Column[Any]"]:  # Any: uuid, time and integer columns together
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


def upgrade() -> None:
    """Adds the list-settings table and the asset list's product-type index."""
    op.create_table(
        TABLE,
        *_entity(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("list_key", sa.String(60), nullable=False),
        sa.Column("view_key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("filter", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "columns",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("sort", sa.String(200), nullable=True),
        sa.Column("page_size", sa.Integer(), server_default="50", nullable=False),
        sa.Column("favourite", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint(
            "page_size IN (25, 50, 100)", name=op.f("ck_list_settings_page_size_choice")
        ),
        sa.CheckConstraint(
            "jsonb_array_length(columns) <= 40", name=op.f("ck_list_settings_columns_limit")
        ),
        sa.CheckConstraint(
            "(name IS NOT NULL) = (view_key LIKE 'custom:%')",
            name=op.f("ck_list_settings_name_when_saved_view"),
        ),
        sa.CheckConstraint(
            "filter IS NULL OR view_key LIKE 'custom:%'",
            name=op.f("ck_list_settings_filter_when_saved_view"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_list_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_list_settings_user"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_list_settings")),
    )
    op.create_index(
        "uq_list_settings_user_list_view",
        TABLE,
        ["tenant_id", "user_id", "list_key", "view_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_list_settings_view_name",
        TABLE,
        ["tenant_id", "user_id", "list_key", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND name IS NOT NULL"),
    )
    enable_tenant_rls(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))  # removal is a soft delete
    enable_actor_audit(TABLE)
    # The tree filter with the default sort (newest change first), live assets only.
    op.create_index(
        "ix_assets_type_updated",
        "assets",
        ["tenant_id", "product_type_id", "updated_at", "id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % keeps list settings or saved views (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - a fixed table name, no input


def downgrade() -> None:
    """Drops what 0140 added only while no tenant keeps a list setting; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_index("ix_assets_type_updated", table_name="assets")
    op.drop_table(TABLE)
