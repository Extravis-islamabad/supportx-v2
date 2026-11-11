"""Freeze and maintenance windows (WP-045c; REQ-CHG-075..077; ADR-042), number 0132.

Expand only, no data step:
- `change_windows` (RLS): a freeze or maintenance window with its mode (block or warn), its
  times, an optional weekly repeat until a date, and its scope: sites, groups, services and CIs
  (all empty: the whole tenant; services and CIs are IDs until the CMDB lands); named and
  labelled, versioned for If-Match, soft-deleted.
- `work_item_change_details`: `freeze_override_reason`, `freeze_override_by`,
  `freeze_override_at`. A blocking freeze passed for a change by someone allowed to, and why
  (D-144's pattern; the reason is personal data, as `risk_reason`).

The downgrade drops them while no window and no override exist; otherwise it stops and keeps the
data (rule 5h).

Revision ID: 0132
Revises: 0130
Created: 2026-11-11
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0132"
down_revision: str | None = "0130"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WINDOWS, DETAILS = "change_windows", "work_item_change_details"
OVERRIDE = ("freeze_override_reason", "freeze_override_by", "freeze_override_at")
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {WINDOWS}) OR EXISTS (
            SELECT 1 FROM {DETAILS} WHERE freeze_override_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has change windows or overrides (rule 5h)', t;
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


def _ids(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, postgresql.ARRAY(sa.Uuid()), server_default=sa.text("'{}'"), nullable=False
    )


def upgrade() -> None:
    """The windows, and the override on a change's details."""
    op.create_table(
        WINDOWS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=True),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("repeat_weekly", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("repeat_until", sa.DateTime(timezone=True), nullable=True),
        _ids("site_ids"),
        _ids("group_ids"),
        _ids("service_ids"),
        _ids("ci_ids"),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(
            "kind IN ('freeze', 'maintenance')", name=op.f(f"ck_{WINDOWS}_kind_code")
        ),
        sa.CheckConstraint("mode IN ('block', 'warn')", name=op.f(f"ck_{WINDOWS}_mode_code")),
        sa.CheckConstraint("ends_at > starts_at", name=op.f(f"ck_{WINDOWS}_order")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{WINDOWS}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{WINDOWS}")),
    )
    op.create_index(
        "ix_change_windows_tenant_kind_start",
        WINDOWS,
        ["tenant_id", "kind", "starts_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls(WINDOWS)
    enable_actor_audit(WINDOWS)
    grant_app(WINDOWS, ("SELECT", "INSERT", "UPDATE"))
    op.add_column(DETAILS, sa.Column("freeze_override_reason", sa.String(500), nullable=True))
    op.add_column(DETAILS, sa.Column("freeze_override_by", sa.Uuid(), nullable=True))
    op.add_column(
        DETAILS, sa.Column("freeze_override_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Back to before windows (stops while a window or an override exists)."""
    op.execute(GUARD)
    for column in reversed(OVERRIDE):
        op.drop_column(DETAILS, column)
    op.drop_index("ix_change_windows_tenant_kind_start", table_name=WINDOWS)
    op.drop_table(WINDOWS)
