"""Announcement tables (WP-012). All tenant-scoped with RLS; see migration 0009.

The audience link tables use same-tenant composite foreign keys to sites / support groups
(organization) and the owner to users (identity_access), like the WP-016 membership tables: the
database refuses a link to another tenant's row even though foreign-key checks bypass RLS.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import Base, TenantEntity, TenantKeyed


class Announcement(TenantEntity):
    """One announcement (statuses, severity and audience are stored as codes)."""

    __tablename__ = "announcements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_announcements_tenant_id_id"),
        UniqueConstraint("tenant_id", "display_id", name="uq_announcements_tenant_id_display_id"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_announcements_owner",
        ),
        CheckConstraint("length(btrim(title)) BETWEEN 1 AND 200", name="title_length"),
        CheckConstraint("length(btrim(body)) BETWEEN 1 AND 20000", name="body_length"),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="status_code"),
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="severity_code"),
        CheckConstraint("audience IN ('everyone', 'sites', 'groups')", name="audience_code"),
        CheckConstraint(
            "publish_until IS NULL OR publish_from IS NULL OR publish_until > publish_from",
            name="window_order",
        ),
        # Lists: tenant first, then the sort column, then id (keyset pagination).
        Index("ix_announcements_tenant_updated", "tenant_id", "updated_at", "id"),
        Index("ix_announcements_tenant_status_updated", "tenant_id", "status", "updated_at", "id"),
        Index("ix_announcements_tenant_owner", "tenant_id", "owner_id"),
        # Feeds: what is published, by window.
        Index(
            "ix_announcements_tenant_published",
            "tenant_id",
            "publish_from",
            "publish_until",
            postgresql_where="status = 'published' AND deleted_at IS NULL",
        ),
    )

    display_id: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), server_default="info")
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    audience: Mapped[str] = mapped_column(String(20), server_default="everyone")
    owner_id: Mapped[uuid.UUID]
    show_as_banner: Mapped[bool] = mapped_column(Boolean, server_default="false")
    publish_from: Mapped[datetime | None]
    publish_until: Mapped[datetime | None]
    published_at: Mapped[datetime | None]
    published_by: Mapped[uuid.UUID | None]


class AnnouncementSite(TenantKeyed, Base):
    """The announcement is for members of this site."""

    __tablename__ = "announcement_sites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "announcement_id"],
            ["announcements.tenant_id", "announcements.id"],
            ondelete="CASCADE",
            name="fk_announcement_sites_announcement",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name="fk_announcement_sites_site",
        ),
        Index("ix_announcement_sites_tenant_site", "tenant_id", "site_id"),
    )

    announcement_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


class AnnouncementGroup(TenantKeyed, Base):
    """The announcement is for members of this support group."""

    __tablename__ = "announcement_groups"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "announcement_id"],
            ["announcements.tenant_id", "announcements.id"],
            ondelete="CASCADE",
            name="fk_announcement_groups_announcement",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["support_groups.tenant_id", "support_groups.id"],
            name="fk_announcement_groups_group",
        ),
        Index("ix_announcement_groups_tenant_group", "tenant_id", "group_id"),
    )

    announcement_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    group_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


class AnnouncementSettings(TenantKeyed, Base):
    """Per-tenant settings of the module (one row, created on first change)."""

    __tablename__ = "announcement_settings"

    # Four-eyes: the owner or author of an announcement may not publish it themselves.
    require_second_publisher: Mapped[bool] = mapped_column(Boolean, server_default="false")
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_by: Mapped[uuid.UUID | None]
