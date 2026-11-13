"""Kept drafts of unsent forms (WP-046a S5c; REQ-INC-019), 0160.

Expand only, no data step:
- `work_item_drafts` (RLS): one person's unsent create form, one per (person, type, form), its
  values sealed with the tenant's field key (ADR-050, purpose `field.work_items.draft`, bound to
  the row) so no plain text of a draft is ever stored. Deleted when the record is saved, the
  draft discarded, its owner deactivated or erased, or after 30 days.

The downgrade refuses while any tenant holds a draft (rule 5h): they are a person's unsaved work.

Revision ID: 0160
Revises: 0159
Created: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0160"
down_revision: str | None = "0159"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_drafts"

GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has kept drafts (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table name, no input


def upgrade() -> None:
    """The drafts table."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("form_key", sa.String(40), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),  # sealed: never plain text
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "octet_length(body) <= 131072", name=op.f(f"ck_{TABLE}_body_size")
        ),  # 64 KB of values, sealed and encoded, with room
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_wid_owner"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_wid_tenant_owner_type_form",
        TABLE,
        ["tenant_id", "owner_id", "type", "form_key"],
        unique=True,
    )
    op.create_index("ix_wid_tenant_updated", TABLE, ["tenant_id", "updated_at"])
    enable_tenant_rls(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE", "DELETE"))


def downgrade() -> None:
    """Back to before (stops while any tenant holds a draft)."""
    op.execute(GUARD)
    op.drop_table(TABLE)
