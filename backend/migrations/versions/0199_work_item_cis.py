"""Configuration items linked to work items (WP-053 S5, lane A; REQ-CMDB-019), 0199.

Expand only, no data step:

- `work_item_cis` (RLS): the CIs a record is about, by ID only (work items never read CMDB
  tables, CLAUDE.md rule e), with how each was linked (`source`) and whether it came with the
  record as it was raised (`at_creation`, a CI's "Raise" menu). Unlinking soft-deletes; one live
  link per record and CI. Indexed by the record and by the CI (the CI's Associations counters).

The downgrade stops while any tenant has a link (rule 5h), then drops the table.

Revision ID: 0199
Revises: 0200
Created: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0199"
# main's head when written; re-pointed onto main's head at its queue turn.
down_revision: str | None = "0200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_cis"

# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has CI links (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - a fixed table name, no input


def upgrade() -> None:
    """The link table, its two indexes, RLS and the app role's grants."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("ci_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(20), server_default="ui", nullable=False),
        sa.Column("at_creation", sa.Boolean(), server_default=sa.false(), nullable=False),
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
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_wic_tenant_item_ci",
        TABLE,
        ["tenant_id", "work_item_id", "ci_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_wic_tenant_ci",
        TABLE,
        ["tenant_id", "ci_id", "work_item_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    """Back to before (stops while a CI is linked anywhere)."""
    op.execute(GUARD)
    op.drop_index("ix_wic_tenant_ci", table_name=TABLE)
    op.drop_index("uq_wic_tenant_item_ci", table_name=TABLE)
    op.drop_table(TABLE)
