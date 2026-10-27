"""Report tables (WP-035). All tenant-scoped with RLS; see migration 0027.

Built-in reports are not rows: they ship as definitions in code (domain/builtin.py), read-only,
so an upgrade can improve them without touching customer copies (REQ-RPT-014 AC4). Saved reports
are rows. A report with no folder is in its owner's "My reports" and private; a report in a
folder is visible to everyone who may run reports (folders are shared at MVP; sharing by role,
group or user is V1, REQ-RPT-046).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import Base, TenantEntity, TenantKeyed


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
