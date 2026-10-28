"""Report tables (WP-035). All tenant-scoped with RLS; see migration 0027.

Built-in reports are not rows: they ship as definitions in code (domain/builtin.py), read-only,
so an upgrade can improve them without touching customer copies (REQ-RPT-014 AC4). Saved reports
are rows. A report with no folder is in its owner's "My reports" and private; a report in a
folder is visible to everyone who may run reports (folders are shared at MVP; sharing by role,
group or user is V1, REQ-RPT-046).
"""

import uuid
from datetime import date, datetime
from datetime import time as time_type
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import Base, TenantEntity, TenantKeyed, TenantScoped, utc_now


class ReportFolder(TenantEntity):
    """A shared folder of saved reports."""

    __tablename__ = "report_folders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_report_folders_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_report_folders_owner",
        ),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 120", name="name_length"),
        Index(
            "uq_report_folders_tenant_name",
            "tenant_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[uuid.UUID]


class Report(TenantEntity):
    """A saved report: a definition in the shared JSON format (REQ-RPT-011)."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_reports_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_reports_owner"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "folder_id"],
            ["report_folders.tenant_id", "report_folders.id"],
            name="fk_reports_folder",
        ),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint(
            "description IS NULL OR char_length(description) <= 1000", name="description_length"
        ),
        CheckConstraint("jsonb_typeof(definition) = 'object'", name="definition_object"),
        CheckConstraint("pg_column_size(definition) <= 32768", name="definition_size"),
        # "My reports": the owner's private reports, newest change first.
        Index(
            "ix_reports_tenant_owner_private",
            "tenant_id",
            "owner_id",
            "updated_at",
            "id",
            postgresql_where=text("folder_id IS NULL AND deleted_at IS NULL"),
        ),
        Index("ix_reports_tenant_folder", "tenant_id", "folder_id", "name"),
    )

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID]
    folder_id: Mapped[uuid.UUID | None]
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The built-in report this one was copied from (REQ-RPT-019), e.g. "incidents_open_by_priority".
    copied_from: Mapped[str | None] = mapped_column(String(80))


class ReportFavourite(TenantKeyed, Base):
    """A report a user starred; `report_ref` is a saved report id or `builtin:<code>`."""

    __tablename__ = "report_favourites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_report_favourites_user",
        ),
        CheckConstraint("char_length(report_ref) BETWEEN 1 AND 100", name="ref_length"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    report_ref: Mapped[str] = mapped_column(String(100), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ReportSettings(TenantKeyed, Base):
    """Per-tenant reporting defaults (parity file 09 Appendix A; D-041: every default editable).

    Seed values, created on first use. The platform maximums in Settings cap what a tenant sets.
    """

    __tablename__ = "report_settings"
    __table_args__ = (
        CheckConstraint("week_start IN ('monday', 'sunday')", name="week_start_code"),
        CheckConstraint(
            "interactive_timeout_seconds BETWEEN 5 AND 60", name="interactive_timeout_range"
        ),
        CheckConstraint("export_link_days BETWEEN 1 AND 30", name="export_link_days_range"),
        CheckConstraint("max_export_rows BETWEEN 1000 AND 1000000", name="max_export_rows_range"),
    )

    week_start: Mapped[str] = mapped_column(String(10), server_default="monday")
    interactive_timeout_seconds: Mapped[int] = mapped_column(Integer, server_default="30")
    export_link_days: Mapped[int] = mapped_column(Integer, server_default="7")
    max_export_rows: Mapped[int] = mapped_column(Integer, server_default="1000000")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
    updated_by: Mapped[uuid.UUID | None]


class ReportExport(TenantScoped, Base):
    """One export of a report to a file, built by the worker (REQ-RPT-058).

    It keeps the definition, language and time zone of the request so the file shows what the
    screen showed; the file lives in object storage until `expires_at` (sign-in to download).
    """

    __tablename__ = "report_exports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_report_exports_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by"],
            ["users.tenant_id", "users.id"],
            name="fk_report_exports_requested_by",
        ),
        CheckConstraint("format IN ('csv', 'xlsx', 'pdf')", name="format_code"),
        CheckConstraint("content IN ('summary', 'records')", name="content_code"),
        CheckConstraint("status IN ('running', 'ready', 'failed', 'expired')", name="status_code"),
        CheckConstraint("language IN ('en', 'ar', 'ur')", name="language_code"),
        CheckConstraint("char_length(title) BETWEEN 1 AND 200", name="title_length"),
        Index("ix_report_exports_tenant_user_created", "tenant_id", "requested_by", "created_at"),
        Index(
            "ix_report_exports_tenant_expiry",
            "tenant_id",
            "expires_at",
            postgresql_where=text("status = 'ready'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    requested_by: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(200))
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    format: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(String(10))
    language: Mapped[str] = mapped_column(String(2))
    time_zone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(10), server_default="running")
    problem: Mapped[str | None] = mapped_column(String(60))
    object_key: Mapped[str | None] = mapped_column(String(300))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]


class ReportSchedule(TenantEntity):
    """A report sent by e-mail on a schedule (REQ-RPT-052 to 056; D-100 D3: minimal at MVP).

    Each run builds one file per recipient with that recipient's permissions and language
    (REQ-RPT-053). Recipients are users and groups of the tenant; external addresses are V1.
    """

    __tablename__ = "report_schedules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_report_schedules_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_report_schedules_owner",
        ),
        CheckConstraint("char_length(btrim(title)) BETWEEN 1 AND 200", name="title_length"),
        CheckConstraint("char_length(report_ref) BETWEEN 1 AND 100", name="ref_length"),
        CheckConstraint("frequency IN ('daily', 'weekly', 'monthly')", name="frequency_code"),
        CheckConstraint("format IN ('csv', 'xlsx', 'pdf')", name="format_code"),
        CheckConstraint("content IN ('summary', 'records')", name="content_code"),
        CheckConstraint("status IN ('active', 'paused', 'finished')", name="status_code"),
        CheckConstraint(
            "day_of_month IS NULL OR day_of_month BETWEEN 1 AND 28", name="day_of_month_range"
        ),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="dates_order"),
        CheckConstraint("message IS NULL OR char_length(message) <= 2000", name="message_length"),
        Index(
            "ix_report_schedules_tenant_due",
            "tenant_id",
            "next_run_at",
            postgresql_where=text("status = 'active' AND deleted_at IS NULL"),
        ),
        Index("ix_report_schedules_tenant_owner", "tenant_id", "owner_id"),
    )

    owner_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(200))
    # `builtin:<code>` or a saved report's id; the definition is read at each run.
    report_ref: Mapped[str] = mapped_column(String(100))
    frequency: Mapped[str] = mapped_column(String(10))
    at_time: Mapped[time_type]
    time_zone: Mapped[str] = mapped_column(String(64))
    weekdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), server_default="{}")
    day_of_month: Mapped[int | None] = mapped_column(SmallInteger)
    start_date: Mapped[date]
    end_date: Mapped[date | None]
    recipient_users: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    recipient_groups: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    format: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(String(10), server_default="summary")
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="active")
    paused_reason: Mapped[str | None] = mapped_column(String(60))
    failures: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    next_run_at: Mapped[datetime | None]
    last_run_at: Mapped[datetime | None]
    last_result: Mapped[str | None] = mapped_column(String(60))  # "sent" or a problem code
    last_sent: Mapped[int | None] = mapped_column(SmallInteger)
    last_failed: Mapped[int | None] = mapped_column(SmallInteger)


class Dashboard(TenantEntity):
    """A user-made dashboard (WP-036): its widgets and filter defaults in one document.

    Private to its owner until shared with everyone (REQ-DSH-026). Built-in dashboards are code
    (domain/dashboard.py), never rows.
    """

    __tablename__ = "dashboards"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_dashboards_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_dashboards_owner"
        ),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint(
            "description IS NULL OR char_length(description) <= 1000", name="description_length"
        ),
        CheckConstraint("jsonb_typeof(body) = 'object'", name="body_object"),
        CheckConstraint("pg_column_size(body) <= 262144", name="body_size"),
        Index("ix_dashboards_tenant_owner", "tenant_id", "owner_id", "name"),
        Index(
            "ix_dashboards_tenant_shared",
            "tenant_id",
            "name",
            postgresql_where=text("shared AND deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(120))
    # Translations of the name ({"ar": ...}); a missing language falls back to `name` (DSH-045).
    names: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID]
    shared: Mapped[bool] = mapped_column(Boolean, server_default="false")
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The dashboard this one was copied from: "builtin:<code>" or an id (REQ-DSH-021).
    copied_from: Mapped[str | None] = mapped_column(String(100))


class DashboardPreference(TenantKeyed, Base):
    """One person's dashboard choices: their home (REQ-DSH-002) and favourites (REQ-DSH-005)."""

    __tablename__ = "dashboard_preferences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_dashboard_preferences_user",
        ),
        CheckConstraint(
            "home_ref IS NULL OR char_length(home_ref) BETWEEN 1 AND 100", name="home_ref_length"
        ),
        CheckConstraint("cardinality(favourites) <= 200", name="favourites_count"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    home_ref: Mapped[str | None] = mapped_column(String(100))
    favourites: Mapped[list[str]] = mapped_column(ARRAY(String(100)), server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)


class DashboardRoleDefault(TenantKeyed, Base):
    """The home dashboard an admin chose for a role (REQ-DSH-002)."""

    __tablename__ = "dashboard_role_defaults"
    __table_args__ = (
        # By role key: the key is what a signed-in person's permissions carry (roles' (tenant,
        # key) is unique only among live roles, so no foreign key; a deleted role's row is unused).
        CheckConstraint("role_key ~ '^[a-z][a-z0-9_]{1,62}$'", name="role_key_format"),
        CheckConstraint(
            "char_length(dashboard_ref) BETWEEN 1 AND 100", name="dashboard_ref_length"
        ),
    )

    role_key: Mapped[str] = mapped_column(String(63), primary_key=True)
    dashboard_ref: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
