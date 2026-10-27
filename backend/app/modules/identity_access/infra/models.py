"""Tables owned by identity_access."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, Unmapped, mapped_column, unmapped_column

from app.shared.db.models import Actors, Base, TenantEntity, TenantKeyed, Timestamps, Versioned

# Name and email; the email also split at its punctuation, so "ahmed" finds ahmed.ali@x.com.
# Since WP-021 (REQ-ADM-001) also the employee ID and phone numbers.
SEARCH_VECTOR = (
    "sx_search_vector(display_name, coalesce(email, '') || ' '"
    " || translate(coalesce(email, ''), '@._-+', '     ')"
    " || ' ' || coalesce(employee_id, '') || ' ' || coalesce(phone, '')"
    " || ' ' || coalesce(mobile, ''))"
)


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
        CheckConstraint("form_density IN ('comfortable', 'compact')", name="form_density_code"),
        CheckConstraint(
            "ui_locale IS NULL OR ui_locale IN ('en', 'ar', 'ur')", name="ui_locale_code"
        ),
        CheckConstraint("length(btrim(first_name)) BETWEEN 1 AND 100", name="first_name_length"),
        CheckConstraint("manager_id IS NULL OR manager_id <> id", name="not_own_manager"),
        CheckConstraint(
            "request_visibility IS NULL OR request_visibility IN ('site')",
            name="request_visibility_code",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"], name="fk_users_site"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_users_department",
            use_alter=True,  # departments point back at users (head): break the cycle
        ),
        ForeignKeyConstraint(
            ["tenant_id", "manager_id"], ["users.tenant_id", "users.id"], name="fk_users_manager"
        ),
        Index(
            "uq_users_tenant_employee_id",
            "tenant_id",
            "employee_id",
            unique=True,
            postgresql_where=text("employee_id IS NOT NULL"),
        ),
        Index("ix_users_tenant_manager", "tenant_id", "manager_id"),
        # Keyset pagination for the sortable columns of GET /users (tenant first, ID last).
        Index("ix_users_tenant_created", "tenant_id", "created_at", "id"),
        Index("ix_users_tenant_display_name", "tenant_id", "display_name", "id"),
        Index("ix_users_tenant_last_login", "tenant_id", "last_login_at", "id"),
        # People search (WP-027, ADR-029): name and email words, and trigrams of the name.
        Index("ix_users_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_users_search_name",
            "search_name",
            postgresql_using="gin",
            postgresql_ops={"search_name": "gin_trgm_ops"},
        ),
    )

    # NULL for people added by an admin or an import (WP-021) until their first sign-in, which
    # links them by email address.
    external_subject: Mapped[str | None]
    # The primary address (sign-in, notifications). A contact may have none (REQ-ADM-004).
    email: Mapped[str | None]
    # Shown everywhere: "first last", or the admin's own `display_name` when `name_custom`.
    display_name: Mapped[str]
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    name_custom: Mapped[bool] = mapped_column(server_default="false")
    locale: Mapped[str] = mapped_column(server_default="en")
    status: Mapped[str] = mapped_column(server_default="active")
    user_type: Mapped[str]
    last_login_at: Mapped[datetime | None]
    # Owned by SupportX, editable by the user (WP-008); identity fields above come from Keycloak.
    signature: Mapped[str | None] = mapped_column(Text)
    time_zone: Mapped[str | None] = mapped_column(String(64))
    nav_layout: Mapped[str] = mapped_column(server_default="top")
    form_density: Mapped[str] = mapped_column(server_default="comfortable")
    # The language picked in the app (QA BUG-04); NULL: follow `locale` from Keycloak.
    ui_locale: Mapped[str | None]
    # When the Keycloak roles were mapped to SupportX roles (once, D-029); NULL = not yet.
    roles_mapped_at: Mapped[datetime | None]
    # The person record (WP-021, REQ-ADM-002): owned by SupportX from then on (D-092).
    employee_id: Mapped[str | None] = mapped_column(String(50))
    job_title: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(50))
    mobile: Mapped[str | None] = mapped_column(String(50))
    vip: Mapped[bool] = mapped_column(server_default="false")
    site_id: Mapped[uuid.UUID | None]
    department_id: Mapped[uuid.UUID | None]
    manager_id: Mapped[uuid.UUID | None]
    # May sign in (REQ-ADM-004); without it the person is a contact (requester by email).
    can_sign_in: Mapped[bool] = mapped_column(server_default="true")
    invited_at: Mapped[datetime | None]
    # Per-person override of what a manager sees in the portal (REQ-ADM-035, used by WP-028):
    # NULL = the tenant's rule; "site" = all requests of their site.
    request_visibility: Mapped[str | None] = mapped_column(String(20))
    # People search (migration 0020): generated by the database. Columns of the table, not of the
    # mapped object (never loaded or returned); queries use `User.__table__.c`.
    search_vector: Unmapped[Any] = unmapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR, persisted=True)
    )
    search_name: Unmapped[str] = unmapped_column(
        Text, Computed("sx_search_normalize(display_name)", persisted=True)
    )


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


class AccessSettings(TenantKeyed, Timestamps, Actors, Versioned, Base):
    """A tenant's access defaults (WP-021): what the built-in technician role sees (D-052, D-073).

    No row (or `answered_at` NULL): the first-run question has not been answered yet; the
    least-privileged answer "group" applies meanwhile.
    """

    __tablename__ = "access_settings"
    __table_args__ = (
        CheckConstraint("technician_scope IN ('group', 'all')", name="technician_scope_code"),
    )

    technician_scope: Mapped[str] = mapped_column(String(20), server_default="group")
    answered_at: Mapped[datetime | None]


IMPORT_STATUSES = ("queued", "running", "done", "failed")


class PeopleImport(TenantEntity):
    """One CSV or Excel file of people, imported in the background (WP-021, REQ-ADM-003).

    The file waits in `content` until the import job has read it, then is cleared. Results keep
    counts and per-row problems (row, field, code), never the rows' values.
    """

    __tablename__ = "people_imports"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name="status_code"),
        CheckConstraint("file_format IN ('csv', 'xlsx')", name="file_format_code"),
        CheckConstraint("match_on IN ('email', 'employee_id')", name="match_on_code"),
        Index("ix_people_imports_tenant_status", "tenant_id", "status"),
        Index("ix_people_imports_tenant_created", "tenant_id", "created_at", "id"),
    )

    file_name: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(10))
    content: Mapped[bytes | None]
    status: Mapped[str] = mapped_column(String(20), server_default="queued")
    # Matching column for existing people: "email" or "employee_id".
    match_on: Mapped[str] = mapped_column(String(20), server_default="email")
    total: Mapped[int] = mapped_column(server_default="0")
    processed: Mapped[int] = mapped_column(server_default="0")
    created_count: Mapped[int] = mapped_column(server_default="0")
    updated_count: Mapped[int] = mapped_column(server_default="0")
    failed_count: Mapped[int] = mapped_column(server_default="0")
    problems: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    failure: Mapped[str | None] = mapped_column(String(50))
    finished_at: Mapped[datetime | None]
