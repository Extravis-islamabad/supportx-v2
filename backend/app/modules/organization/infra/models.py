"""Tables owned by the organization module.

`tenants` is a platform table, not a tenant-scoped one: its `id` *is* the tenant. RLS is still
enabled and forced on it (migration 0001):
- supportx_app may SELECT only the row whose id equals the transaction's `app.tenant_id`, and has
  no INSERT/UPDATE/DELETE privilege at all;
- supportx_migrator (provisioning, seeding) may manage all rows.

`sites`, `support_groups` and their member tables are ordinary tenant-scoped tables (WP-016):
they give the authorization policy its `site` and `group` scopes. Full admin screens come later.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, func, text
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


class Site(TenantEntity):
    """A location of the tenant (office, data centre, branch). Basis of the `site` scope."""

    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_sites_tenant_id_id"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        Index(
            "uq_sites_tenant_id_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str]


class SupportGroup(TenantEntity):
    """A team that works tickets together (Service Desk ...). Basis of the `group` scope."""

    __tablename__ = "support_groups"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        UniqueConstraint("tenant_id", "id", name="uq_support_groups_tenant_id_id"),
        Index(
            "uq_support_groups_tenant_id_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str]


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
