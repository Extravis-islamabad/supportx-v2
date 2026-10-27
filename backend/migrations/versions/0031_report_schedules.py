"""Scheduled reports (WP-035 session 4; D-100 D3).

Tenant-scoped with RLS, soft delete only. The partial index finds what is due without reading
paused, finished or deleted schedules.

Revision ID: 0031
Revises: 0029
Created: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0031"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("report_ref", sa.String(length=100), nullable=False),
        sa.Column("frequency", sa.String(length=10), nullable=False),
        sa.Column("at_time", sa.Time(), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column(
            "weekdays", postgresql.ARRAY(sa.SmallInteger()), server_default="{}", nullable=False
        ),
        sa.Column("day_of_month", sa.SmallInteger(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "recipient_users",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "recipient_groups",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("content", sa.String(length=10), server_default="summary", nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("paused_reason", sa.String(length=60), nullable=True),
        sa.Column("failures", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result", sa.String(length=60), nullable=True),
        sa.Column("last_sent", sa.SmallInteger(), nullable=True),
        sa.Column("last_failed", sa.SmallInteger(), nullable=True),
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
            "char_length(btrim(title)) BETWEEN 1 AND 200",
            name=op.f("ck_report_schedules_title_length"),
        ),
        sa.CheckConstraint(
            "char_length(report_ref) BETWEEN 1 AND 100", name=op.f("ck_report_schedules_ref_length")
        ),
        sa.CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly')",
            name=op.f("ck_report_schedules_frequency_code"),
        ),
        sa.CheckConstraint(
            "format IN ('csv', 'xlsx', 'pdf')", name=op.f("ck_report_schedules_format_code")
        ),
        sa.CheckConstraint(
            "content IN ('summary', 'records')", name=op.f("ck_report_schedules_content_code")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'finished')",
            name=op.f("ck_report_schedules_status_code"),
        ),
        sa.CheckConstraint(
            "day_of_month IS NULL OR day_of_month BETWEEN 1 AND 28",
            name=op.f("ck_report_schedules_day_of_month_range"),
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name=op.f("ck_report_schedules_dates_order"),
        ),
        sa.CheckConstraint(
            "message IS NULL OR char_length(message) <= 2000",
            name=op.f("ck_report_schedules_message_length"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_report_schedules_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_report_schedules_owner",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_schedules")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_report_schedules_tenant_id_id"),
    )
    op.create_index(
        "ix_report_schedules_tenant_due",
        "report_schedules",
        ["tenant_id", "next_run_at"],
        postgresql_where=sa.text("status = 'active' AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_report_schedules_tenant_owner", "report_schedules", ["tenant_id", "owner_id"]
    )
    enable_tenant_rls("report_schedules")
    enable_actor_audit("report_schedules")
    grant_app("report_schedules", ("SELECT", "INSERT", "UPDATE"))  # soft delete only


def downgrade() -> None:
    op.drop_table("report_schedules")
