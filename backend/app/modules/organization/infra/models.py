"""Tables owned by the organization module.

`tenants` is a platform table, not a tenant-scoped one: its `id` *is* the tenant. RLS is still
enabled and forced on it (migration 0001):
- supportx_app may SELECT only the row whose id equals the transaction's `app.tenant_id`, and has
  no INSERT/UPDATE/DELETE privilege at all;
- supportx_migrator (provisioning, seeding) may manage all rows.

`sites`, `support_groups` and their member tables are ordinary tenant-scoped tables (WP-016):
they give the authorization policy its `site` and `group` scopes. WP-021 (ADR-032) adds their
details, departments, the sites a group serves, and desks: every record belongs to a desk
(REQ-ESM-002, D-061); a tenant starts with one IT desk.
"""

import uuid
from datetime import datetime

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

from app.modules.organization.domain.tenant import SLUG_PATTERN
from app.shared.db.models import Base, TenantEntity, TenantKeyed, UuidPrimaryKey


class Tenant(UuidPrimaryKey, Base):
    """A customer organisation (one row per tenant)."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="slug_format"),
        CheckConstraint("status IN ('active', 'suspended')", name="status_code"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
    )

    name: Mapped[str]
    slug: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Desk(TenantEntity):
    """A service desk (IT, HR, Facilities ...): every record belongs to one (REQ-ESM-002).

    A tenant starts with the IT desk (`is_default`). More desks need the ESM feature and count
    against the licence limit `desks` (D-061, D-092). Shown only to tenants with ESM.
    """

    __tablename__ = "desks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_desks_tenant_id_id"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,39}$'", name="code_format"),
        Index(
            "uq_desks_tenant_code",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_desks_tenant_default",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default AND deleted_at IS NULL"),
        ),
    )

    code: Mapped[str] = mapped_column(String(40))
    labels: Mapped[dict[str, str]] = mapped_column(JSONB)
    is_default: Mapped[bool] = mapped_column(server_default="false")
    disabled_at: Mapped[datetime | None]


class Site(TenantEntity):
    """A location of the tenant (office, data centre, branch). Basis of the `site` scope.

    Its time zone and default language apply to the people and records at the site
    (REQ-ADM-037). A tenant has one default site.
    """

    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_sites_tenant_id_id"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint(
            "default_language IS NULL OR default_language IN ('en', 'ar', 'ur')",
            name="default_language_code",
        ),
        Index(
            "uq_sites_tenant_id_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_sites_tenant_default",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default AND deleted_at IS NULL"),
        ),
    )

    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(100))
    time_zone: Mapped[str | None] = mapped_column(String(64))
    default_language: Mapped[str | None] = mapped_column(String(2))
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(320))
    is_default: Mapped[bool] = mapped_column(server_default="false")
    # Inactive: kept on the people and records that use it, not offered for new ones.
    disabled_at: Mapped[datetime | None]


class Department(TenantEntity):
    """A department (Finance, HR ...), optionally inside a parent and at a site (REQ-ADM-039).

    Its code is unique per tenant: directory sync and sign-in map a department by code or name
    (WP-039 D6, `find_department`).
    """

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_departments_tenant_id_id"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"], name="fk_departments_site"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_departments_parent",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "head_id"], ["users.tenant_id", "users.id"], name="fk_departments_head"
        ),
        Index(
            "uq_departments_tenant_name",
            "tenant_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_departments_tenant_code",
            "tenant_id",
            text("lower(code)"),
            unique=True,
            postgresql_where=text("code IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("ix_departments_tenant_site", "tenant_id", "site_id"),
    )

    name: Mapped[str]
    code: Mapped[str | None] = mapped_column(String(50))
    site_id: Mapped[uuid.UUID | None]
    head_id: Mapped[uuid.UUID | None]
    parent_id: Mapped[uuid.UUID | None]
    description: Mapped[str | None] = mapped_column(Text)
    disabled_at: Mapped[datetime | None]


class SupportGroup(TenantEntity):
    """A team that works tickets together (Service Desk ...). Basis of the `group` scope."""

    __tablename__ = "support_groups"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        UniqueConstraint("tenant_id", "id", name="uq_support_groups_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"], ["users.tenant_id", "users.id"], name="fk_support_groups_lead"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "desk_id"], ["desks.tenant_id", "desks.id"], name="fk_support_groups_desk"
        ),
        Index(
            "uq_support_groups_tenant_id_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(Text)
    lead_id: Mapped[uuid.UUID | None]
    # The group's own address and sender name, used by notifications and mail (WP-023/024).
    email: Mapped[str | None] = mapped_column(String(320))
    sender_name: Mapped[str | None] = mapped_column(String(200))
    desk_id: Mapped[uuid.UUID]
    disabled_at: Mapped[datetime | None]


class GroupSite(TenantKeyed, Base):
    """A site a support group serves (one or many, REQ-ADM-031)."""

    __tablename__ = "group_sites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["support_groups.tenant_id", "support_groups.id"],
            ondelete="CASCADE",
            name="fk_group_sites_group",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            ondelete="CASCADE",
            name="fk_group_sites_site",
        ),
        Index("ix_group_sites_tenant_site", "tenant_id", "site_id"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by: Mapped[uuid.UUID | None]


class SiteMember(TenantKeyed, Base):
    """A user belongs to a site. Same-tenant foreign keys to the site and to users."""

    __tablename__ = "site_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            ondelete="CASCADE",
            name="fk_site_members_site",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_site_members_user"
        ),
        Index("ix_site_members_tenant_user", "tenant_id", "user_id"),
    )

    site_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by: Mapped[uuid.UUID | None]


class GroupMember(TenantKeyed, Base):
    """A user belongs to a support group. Same-tenant foreign keys."""

    __tablename__ = "group_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["support_groups.tenant_id", "support_groups.id"],
            ondelete="CASCADE",
            name="fk_group_members_group",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_group_members_user"
        ),
        Index("ix_group_members_tenant_user", "tenant_id", "user_id"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by: Mapped[uuid.UUID | None]
