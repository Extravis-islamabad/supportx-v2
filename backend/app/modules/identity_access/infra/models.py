"""Tables owned by identity_access."""

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


class User(TenantEntity):
    """A person in one tenant.

    Provisioned just-in-time from the identity provider on login; one row per (tenant, Keycloak
    subject), so a member of two organizations has two rows.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_subject"),
        UniqueConstraint("tenant_id", "email"),
        # Target of the same-tenant foreign keys from user_roles and the membership tables.
        UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id_id"),
        CheckConstraint("locale IN ('en', 'ar', 'ur')", name="locale_code"),
        CheckConstraint("status IN ('active', 'disabled')", name="status_code"),
        CheckConstraint("user_type IN ('technician', 'requester')", name="user_type_code"),
        CheckConstraint("char_length(signature) <= 2000", name="signature_length"),
        CheckConstraint("nav_layout IN ('top', 'side', 'side_compact')", name="nav_layout_code"),
        CheckConstraint(
            "ui_locale IS NULL OR ui_locale IN ('en', 'ar', 'ur')", name="ui_locale_code"
        ),
        # Keyset pagination for the sortable columns of GET /users (tenant first, ID last).
        Index("ix_users_tenant_created", "tenant_id", "created_at", "id"),
        Index("ix_users_tenant_display_name", "tenant_id", "display_name", "id"),
        Index("ix_users_tenant_last_login", "tenant_id", "last_login_at", "id"),
    )

    external_subject: Mapped[str]
    email: Mapped[str]
    display_name: Mapped[str]
    locale: Mapped[str] = mapped_column(server_default="en")
    status: Mapped[str] = mapped_column(server_default="active")
    user_type: Mapped[str]
    last_login_at: Mapped[datetime | None]
    # Owned by SupportX, editable by the user (WP-008); identity fields above come from Keycloak.
    signature: Mapped[str | None] = mapped_column(Text)
    time_zone: Mapped[str | None] = mapped_column(String(64))
    nav_layout: Mapped[str] = mapped_column(server_default="top")
    # The language picked in the app (QA BUG-04); NULL: follow `locale` from Keycloak.
    ui_locale: Mapped[str | None]
    # When the Keycloak roles were mapped to SupportX roles (once, D-029); NULL = not yet.
    roles_mapped_at: Mapped[datetime | None]


SCOPE_CODES = ("all", "site", "group", "own")


class Role(TenantEntity):
    """A role of the tenant.

    System roles (tenant_admin, technician, requester) have a fixed key and code-defined
    permissions and can be neither edited nor deleted; custom roles hold their permissions in
    role_permissions.
    """

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_id_id"),
        Index(
            "uq_roles_tenant_id_key",
            "tenant_id",
            "key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("key ~ '^[a-z][a-z0-9_]{1,62}$'", name="key_format"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint("char_length(description) <= 1000", name="description_length"),
    )

    key: Mapped[str]
    # Custom roles: the admin's own text (data, not a label). System roles: shown via labels.
    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(server_default="false")


class RolePermission(TenantKeyed, Base):
    """One permission of a custom role, at a scope, optionally with an attribute condition."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            ondelete="CASCADE",
            name="fk_role_permissions_role",
        ),
        CheckConstraint("scope IN ('all', 'site', 'group', 'own')", name="scope_code"),
        CheckConstraint("permission ~ '^[a-z][a-z_]*\\.[a-z][a-z_]*$'", name="permission_format"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    permission: Mapped[str] = mapped_column(primary_key=True)
    scope: Mapped[str]
    # Attribute rule in the filter DSL (shared/api/filters.py); NULL = every record in scope.
    condition: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class UserRole(TenantKeyed, Base):
    """A role assigned to a user. Same-tenant foreign keys on both sides."""

    __tablename__ = "user_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_user_roles_user"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="fk_user_roles_role"
        ),
        Index("ix_user_roles_tenant_role", "tenant_id", "role_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by: Mapped[uuid.UUID | None]
