"""Connector defaults per tenant (WP-040, D-041; the D-118 defaults made editable).

- connector_settings (new, RLS with FORCE): one row per tenant once an admin saves. No row means
  Appendix A's defaults: "failing" after 3 failed runs in a row (or at once on an
  authentication failure, which is not editable), errors kept 90 days, and a new directory
  synced every 30 minutes. (The secret rotation reminder, 180 days, joins when the reminder is
  built.)

Revision ID: 0057
Revises: 0050 (main's head after #158 and #190; re-pointed again if another migration lands first)
Created: 2026-11-04
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0057"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "connector_settings"
REFUSE_IF_SAVED = """
DO $$
DECLARE
    t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM connector_settings WHERE tenant_id = t) THEN
            RAISE EXCEPTION 'saved connector defaults exist: going below 0057 would lose them';
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""


def _timestamp(name: str) -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("failing_after_runs", sa.Integer(), server_default="3", nullable=False),
        sa.Column("error_retention_days", sa.Integer(), server_default="90", nullable=False),
        sa.Column("sync_minutes", sa.Integer(), server_default="30", nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "failing_after_runs BETWEEN 1 AND 20"
            " AND error_retention_days BETWEEN 7 AND 365"
            " AND sync_minutes BETWEEN 15 AND 1440",
            name=op.f("ck_connector_settings_ranges"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_connector_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_connector_settings")),
    )
    enable_tenant_rls(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit(TABLE)


def downgrade() -> None:
    # A tenant's saved defaults would be lost: refused while any exists (CLAUDE.md rule 5h),
    # checked under every tenant (FORCE RLS hides rows from a statement without a tenant).
    op.execute(REFUSE_IF_SAVED)
    op.drop_table(TABLE)
