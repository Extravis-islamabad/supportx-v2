"""Approvals on work items (WP-030 s2, plan D4; REQ-SR-021..028, -063).

One row per approver of a record's approval stage. `approver_id` NULL means the tenant's
approval administrators hold it (never nobody, REQ-SR-023); `route_reason` keeps why. Tenant
scoped with RLS (FORCE) and actor audit; soft delete only (no DELETE grant); same-tenant foreign
keys to the record and the people. Expand only, no data step; the downgrade drops the table.

Revision ID: 0065
Revises: 0064
Created: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATES = ("pending", "approved", "rejected", "withdrawn", "not_needed")
ORIGINS = ("named", "manager", "backup", "administrators")
REASONS = ("no_manager", "approver_inactive", "self_approval_blocked")
CHANNELS = ("app", "portal", "email_link")
TABLE = "work_item_approvals"


def _codes(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """Create the approvals table with RLS."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("work_item_id", sa.UUID(), nullable=False),
        sa.Column("stage", sa.Integer(), server_default="1", nullable=False),
        sa.Column("approver_id", sa.UUID(), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("route_reason", sa.String(length=30), nullable=True),
        sa.Column("state", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("comment_private", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("self_approval", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("comments_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_codes("state", STATES), name=op.f(f"ck_{TABLE}_state_code")),
        sa.CheckConstraint(_codes("origin", ORIGINS), name=op.f(f"ck_{TABLE}_origin_code")),
        sa.CheckConstraint(
            "route_reason IS NULL OR " + _codes("route_reason", REASONS),
            name=op.f(f"ck_{TABLE}_reason_code"),
        ),
        sa.CheckConstraint(
            "channel IS NULL OR " + _codes("channel", CHANNELS),
            name=op.f(f"ck_{TABLE}_channel_code"),
        ),
        sa.CheckConstraint(
            "(origin = 'administrators') = (approver_id IS NULL)",
            name=op.f(f"ck_{TABLE}_administrators_no_person"),
        ),
        sa.CheckConstraint(
            "comment IS NULL OR char_length(comment) <= 4000",
            name=op.f(f"ck_{TABLE}_comment_length"),
        ),
        sa.CheckConstraint("stage >= 1", name=op.f(f"ck_{TABLE}_stage_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_wia_work_item",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approver_id"], ["users.tenant_id", "users.id"], name="fk_wia_approver"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decided_by"], ["users.tenant_id", "users.id"], name="fk_wia_decided_by"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index("ix_wia_tenant_item", TABLE, ["tenant_id", "work_item_id", "stage", "id"])
    op.create_index(
        "ix_wia_tenant_approver_pending",
        TABLE,
        ["tenant_id", "approver_id"],
        postgresql_where=sa.text("deleted_at IS NULL AND state = 'pending'"),
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    """Drop the approvals table."""
    op.drop_table(TABLE)
