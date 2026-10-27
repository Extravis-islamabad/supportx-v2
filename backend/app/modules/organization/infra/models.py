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


class TenantBranding(TenantEntity):
    """A tenant's brand (WP-017): colours, texts and the uploaded originals. One row per tenant.

    Empty values mean "the SupportX default". The originals are files (WP-022, owner `branding`);
    the variants every surface shows are generated from them into `branding_assets`, and
    `assets_version` (a hash of those variants) goes into their public URLs so they cache forever.
    """

    __tablename__ = "tenant_branding"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_branding_tenant_id"),
        CheckConstraint(
            "primary_colour IS NULL OR primary_colour ~ '^#[0-9a-f]{6}$'", name="primary_colour"
        ),
        CheckConstraint(
            "(gradient_start IS NULL) = (gradient_end IS NULL)", name="gradient_both_or_none"
        ),
        CheckConstraint(
            "gradient_start IS NULL OR (gradient_start ~ '^#[0-9a-f]{6}$'"
            " AND gradient_end ~ '^#[0-9a-f]{6}$')",
            name="gradient_colours",
        ),
    )

    primary_colour: Mapped[str | None]
    gradient_start: Mapped[str | None]
    gradient_end: Mapped[str | None]
    product_name: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    portal_name: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    welcome_text: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    logo_file_id: Mapped[uuid.UUID | None]
    logo_dark_file_id: Mapped[uuid.UUID | None]
    icon_file_id: Mapped[uuid.UUID | None]
    assets_version: Mapped[str | None]


class BrandingAsset(TenantKeyed, Base):
    """One generated brand image (logo per theme, icon, favicons), served publicly.

    A cache of what is made from the originals in the files service: small (kilobytes), public by
    nature (the sign-in page and e-mails show them before anyone signs in), regenerated on save.
    """

    __tablename__ = "branding_assets"
    __table_args__ = (CheckConstraint("octet_length(content) <= 1048576", name="content_size"),)

    name: Mapped[str] = mapped_column(primary_key=True)
    content_type: Mapped[str]
    content: Mapped[bytes]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TenantDomain(TenantEntity):
    """A custom domain for the tenant's console and portal (REQ-PRT-016 AC3, REQ-SEC-004).

    The subdomain `<slug>.<base domain>` needs no row. A custom domain is `pending` until the
    tenant proves it points here (an HTTP token, D-090), then `verified`; only verified domains
    resolve to the tenant. A host is unique across all tenants.
    """

    __tablename__ = "tenant_domains"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'verified', 'failed')", name="status_code"),
        CheckConstraint("tls_mode IN ('automatic', 'uploaded')", name="tls_mode_code"),
        CheckConstraint(
            "tls_status IN ('waiting', 'pending', 'issued', 'failed', 'not_managed')",
            name="tls_status_code",
        ),
        CheckConstraint("host = lower(host) AND length(host) BETWEEN 4 AND 253", name="host"),
        Index(
            "uq_tenant_domains_host",
            "host",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_tenant_domains_tenant_id_status", "tenant_id", "status"),
    )

    host: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="pending")
    verify_token: Mapped[str]
    verified_at: Mapped[datetime | None]
    checked_at: Mapped[datetime | None]
    failure_code: Mapped[str | None]
    tls_mode: Mapped[str] = mapped_column(server_default="automatic")
    tls_status: Mapped[str] = mapped_column(server_default="waiting")
    certificate_pem: Mapped[str | None]
    private_key: Mapped[bytes | None]  # AES-256-GCM with the tenant's data key (files keyring)
    private_key_key_id: Mapped[uuid.UUID | None]
    certificate_not_after: Mapped[datetime | None]
    certificate_error: Mapped[str | None]
