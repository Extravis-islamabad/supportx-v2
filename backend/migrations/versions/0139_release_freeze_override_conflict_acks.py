"""Release freeze override and conflict acknowledgements (WP-058b S2; REQ-REL-040, -041).

Expand only, no data step:
- `work_item_release_details`: `freeze_override_reason`, `freeze_override_by`,
  `freeze_override_at` and `freeze_override_window_ids`, the blocking freezes passed for a
  release, as a change's (0132);
- `work_item_conflict_acks`: a conflict acknowledged with a reason, keyed on the conflict as it
  is now (so it lapses when either side moves). Tenant RLS, actor audit, version, soft delete;
  one live ack per record and key.

The downgrade stops while an override or an ack exists in any tenant (rule 5h).

Revision ID: 0139
Revises: 0136
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0139"
down_revision: str | None = "0136"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACKS, DETAILS = "work_item_conflict_acks", "work_item_release_details"
OVERRIDE = (
    "freeze_override_reason",
    "freeze_override_by",
    "freeze_override_at",
    "freeze_override_window_ids",
)
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {ACKS}) OR EXISTS (
            SELECT 1 FROM {DETAILS} WHERE freeze_override_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has conflict acks or release overrides (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def _stamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]


def upgrade() -> None:
    """The release override columns and the acks table."""
    op.add_column(DETAILS, sa.Column("freeze_override_reason", sa.String(500), nullable=True))
    op.add_column(DETAILS, sa.Column("freeze_override_by", sa.Uuid(), nullable=True))
    op.add_column(
        DETAILS, sa.Column("freeze_override_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        DETAILS,
        sa.Column(
            "freeze_override_window_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.create_table(
        ACKS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("conflict_key", sa.String(300), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("acked_by", sa.Uuid(), nullable=False),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{ACKS}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["work_item_id"],
            ["work_items.id"],
            name=op.f(f"fk_{ACKS}_work_item_id_work_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ACKS}")),
    )
    op.create_index(
        "uq_work_item_conflict_acks_tenant_item_key",
        ACKS,
        ["tenant_id", "work_item_id", "conflict_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls(ACKS)
    enable_actor_audit(ACKS)
    grant_app(ACKS, ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    """Back to before (stops while an ack or a release override exists)."""
    op.execute(GUARD)
    op.drop_index("uq_work_item_conflict_acks_tenant_item_key", table_name=ACKS)
    op.drop_table(ACKS)
    for column in reversed(OVERRIDE):
        op.drop_column(DETAILS, column)
