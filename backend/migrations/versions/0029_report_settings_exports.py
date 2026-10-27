"""Report settings per tenant and report exports (WP-035 session 3; D-100).

Both tenant-scoped with RLS. Settings are one row per tenant (insert on first use, then update);
exports are written by the API (request) and the worker (result), never deleted by either: an
expired export keeps its row with the file removed.

Revision ID: 0029
Revises: 0027
Created: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0029"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "report_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.String(length=10), server_default="monday", nullable=False),
        sa.Column("interactive_timeout_seconds", sa.Integer(), server_default="30", nullable=False),
        sa.Column("export_link_days", sa.Integer(), server_default="7", nullable=False),
        sa.Column("max_export_rows", sa.Integer(), server_default="1000000", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "week_start IN ('monday', 'sunday')", name=op.f("ck_report_settings_week_start_code")
        ),
        sa.CheckConstraint(
            "interactive_timeout_seconds BETWEEN 5 AND 60",
            name=op.f("ck_report_settings_interactive_timeout_range"),
        ),
        sa.CheckConstraint(
            "export_link_days BETWEEN 1 AND 30",
            name=op.f("ck_report_settings_export_link_days_range"),
        ),
        sa.CheckConstraint(
            "max_export_rows BETWEEN 1000 AND 1000000",
            name=op.f("ck_report_settings_max_export_rows_range"),
        ),
        _tenant_fk("report_settings"),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_report_settings")),
    )
    enable_tenant_rls("report_settings")
    grant_app("report_settings", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "report_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("content", sa.String(length=10), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="running", nullable=False),
        sa.Column("problem", sa.String(length=60), nullable=True),
        sa.Column("object_key", sa.String(length=300), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "format IN ('csv', 'xlsx', 'pdf')", name=op.f("ck_report_exports_format_code")
        ),
        sa.CheckConstraint(
            "content IN ('summary', 'records')", name=op.f("ck_report_exports_content_code")
        ),
        sa.CheckConstraint(
            "status IN ('running', 'ready', 'failed', 'expired')",
            name=op.f("ck_report_exports_status_code"),
        ),
        sa.CheckConstraint(
            "language IN ('en', 'ar', 'ur')", name=op.f("ck_report_exports_language_code")
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200", name=op.f("ck_report_exports_title_length")
        ),
        _tenant_fk("report_exports"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by"],
            ["users.tenant_id", "users.id"],
            name="fk_report_exports_requested_by",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_exports")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_report_exports_tenant_id_id"),
    )
    op.create_index(
        "ix_report_exports_tenant_user_created",
        "report_exports",
        ["tenant_id", "requested_by", "created_at"],
    )
    op.create_index(
        "ix_report_exports_tenant_expiry",
        "report_exports",
        ["tenant_id", "expires_at"],
        postgresql_where=sa.text("status = 'ready'"),
    )
    enable_tenant_rls("report_exports")
    grant_app("report_exports", ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    op.drop_table("report_exports")
    op.drop_table("report_settings")
