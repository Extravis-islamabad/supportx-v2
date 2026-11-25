"""Outside problems' incidents, one for life (WP-053 S7a, lane A; D-050), 0210.

Expand only, no data step:

- `work_item_external_keys` (RLS): `(source_kind, source_id, external_id)` names an outside
  problem (a MonetX connection's problem ID) and `work_item_id` the incident it made, with the
  newest version applied. Unique per tenant for life (not only while live): a key is never
  deleted or repointed, so the same problem can never make a second incident. `source_kind` is a
  closed list (`monetx`, `alert_webhook`). IDs and codes only: no outside text is stored here.

The downgrade stops while any tenant has a key (rule 5h), then drops the table.

Revision ID: 0210
Revises: 0205
Created: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0210"
# main's head when written; re-pointed onto main's head at its queue turn.
down_revision: str | None = "0205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_external_keys"

# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has external problem keys (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - a fixed table name, no input


def upgrade() -> None:
    """The key table, its two indexes, the kind check, RLS and the app role's grants."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("last_version", sa.BigInteger(), nullable=False),
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
        sa.CheckConstraint(
            "source_kind IN ('monetx', 'alert_webhook')", name=op.f("ck_wiek_source_kind_code")
        ),
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
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_wiek_tenant_source_external",
        TABLE,
        ["tenant_id", "source_kind", "source_id", "external_id"],
        unique=True,
    )
    op.create_index("ix_wiek_tenant_item", TABLE, ["tenant_id", "work_item_id"])
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    """Back to before (stops while any tenant has a key)."""
    op.execute(GUARD)
    op.drop_index("ix_wiek_tenant_item", table_name=TABLE)
    op.drop_index("uq_wiek_tenant_source_external", table_name=TABLE)
    op.drop_table(TABLE)
