"""Tables owned by identity_access."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, INET, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, Unmapped, mapped_column, unmapped_column

from app.modules.identity_access.domain.network import IP_ALLOW_MAX
from app.modules.identity_access.domain.sign_in import (
    SignInApp,
    SignInMethod,
    SignInOutcome,
    Source,
)
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
        CheckConstraint(
            "break_glass OR NOT break_glass_ip_exempt",
            name="break_glass_ip_exempt_needs_break_glass",
        ),
        CheckConstraint(
            "user_type IN ('technician', 'requester', 'service')", name="user_type_code"
        ),
        # A service identity (WP-040) has no account to sign in with, and no address to link one.
        CheckConstraint(
            "user_type <> 'service' OR (external_subject IS NULL AND email IS NULL"
            " AND NOT can_sign_in)",
            name="service_no_sign_in",
        ),
        # Synced from a directory (WP-040 session 2): its fields are the directory's to change.
        CheckConstraint(
            "directory_source IS NULL OR directory_source IN ('entra', 'ldap')",
            name="directory_source_code",
        ),
        CheckConstraint("char_length(signature) <= 2000", name="signature_length"),
        CheckConstraint("nav_layout IN ('top', 'side', 'side_compact')", name="nav_layout_code"),
        CheckConstraint("form_density IN ('comfortable', 'compact')", name="form_density_code"),
        # NULL passes both checks: not chosen, the default applies when read (0071).
        CheckConstraint(
            "ui_locale IS NULL OR ui_locale IN ('en', 'ar', 'ur')", name="ui_locale_code"
        ),
        # Personal preferences (WP-042): NULL means "the default", read at sign-in, never copied.
        CheckConstraint(
            "theme_mode IS NULL OR theme_mode IN ('light', 'dark', 'high_contrast', 'system')",
            name="theme_mode_code",
        ),
        CheckConstraint(
            "text_scale IS NULL OR (text_scale BETWEEN 90 AND 150 AND text_scale % 10 = 0)",
            name="text_scale_range",
        ),
        CheckConstraint(
            "week_start IS NULL OR week_start IN ('monday', 'sunday', 'saturday')",
            name="week_start_code",
        ),
        CheckConstraint(
            "date_format IS NULL"
            " OR date_format IN ('dd/mm/yyyy', 'mm/dd/yyyy', 'yyyy-mm-dd', 'dd.mm.yyyy')",
            name="date_format_code",
        ),
        CheckConstraint(
            "time_format IS NULL OR time_format IN ('24h', '12h')", name="time_format_code"
        ),
        CheckConstraint(
            "digits IS NULL OR digits IN ('western', 'arabic_indic')", name="digits_code"
        ),
        CheckConstraint(
            "urdu_script IS NULL OR urdu_script IN ('naskh', 'nastaliq')", name="urdu_script_code"
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
    # MFA (WP-039 session 3, domain/mfa.py): when it became required for this person here (the
    # grace period runs from it; cleared when no longer required), and when SupportX last saw
    # an authenticator on their Keycloak account (sign-in, enrolment, reset keep it current).
    mfa_required_since: Mapped[datetime | None]
    mfa_enrolled_at: Mapped[datetime | None]
    # WP-057 S1b (REQ-SEC-009): a named admin who keeps a local password with MFA while single
    # sign-on is required; optionally exempt from the IP allow-lists too. Set by tenant admins.
    break_glass: Mapped[bool] = mapped_column(server_default="false")
    break_glass_ip_exempt: Mapped[bool] = mapped_column(server_default="false")
    # Owned by SupportX, editable by the user (WP-008); identity fields above come from Keycloak.
    signature: Mapped[str | None] = mapped_column(Text)
    time_zone: Mapped[str | None] = mapped_column(String(64))
    # NULL: not chosen; read as the side bar (D-124) and comfortable forms (0071).
    nav_layout: Mapped[str | None]
    form_density: Mapped[str | None]
    # The language picked in the app (QA BUG-04); NULL: follow `locale` from Keycloak.
    ui_locale: Mapped[str | None]
    # WP-042 (REQ-ADM-059, 062). NULL: not chosen, so the default applies when read (the
    # browser's theme, 100 %, the site's or tenant's formats). A changed default never
    # overwrites anyone's own choice.
    theme_mode: Mapped[str | None] = mapped_column(String(16))
    text_scale: Mapped[int | None] = mapped_column(SmallInteger)
    week_start: Mapped[str | None] = mapped_column(String(10))
    date_format: Mapped[str | None] = mapped_column(String(12))
    time_format: Mapped[str | None] = mapped_column(String(4))
    # D-135: NULL means Western digits (0-9), the default in every language.
    digits: Mapped[str | None] = mapped_column(String(16))
    # D-137: NULL means Naskh (Noto Sans Arabic) for Urdu; `nastaliq` is Noto Nastaliq Urdu.
    urdu_script: Mapped[str | None] = mapped_column(String(16))
    # When the Keycloak roles were mapped to SupportX roles (once, D-029); NULL = not yet.
    roles_mapped_at: Mapped[datetime | None]
    # Which directory keeps this person (entra | ldap); NULL: SupportX does (WP-040 session 2).
    directory_source: Mapped[str | None] = mapped_column(String(20))
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


class GroupRole(TenantKeyed, Base):
    """A role a support group carries (WP-042, REQ-ADM-015 AC2).

    Its members hold the role while they are members of an active group. The group lives in
    organization; only its ID is kept here (no cross-module foreign key), checked through
    organization's public interface on write.
    """

    __tablename__ = "group_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="fk_group_roles_role"
        ),
        Index("ix_group_roles_tenant_role", "tenant_id", "role_id"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by: Mapped[uuid.UUID | None]


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


# Appendix A (REQ-SEC-029): defaults and caps of the per-tenant session timeouts.
SESSION_LIMITS = {
    "console": {"idle": 3600, "absolute": 43200, "max_absolute": 7 * 86400},
    "portal": {"idle": 1800, "absolute": 43200, "max_absolute": 30 * 86400},
}
MIN_IDLE_SECONDS = 300
MAX_IDLE_SECONDS = 86400


PASSWORD_POLICY_STATES = ("default", "applying", "applied", "failed")


class IdentitySettings(TenantKeyed, Timestamps, Actors, Versioned, Base):
    """A tenant's sign-in settings (WP-039, REQ-SEC-017): sessions and people creation.

    No row: the defaults of Appendix A. The password policy joined in session 2; the MFA policy
    joins in session 3.
    """

    __tablename__ = "identity_settings"
    __table_args__ = (
        CheckConstraint(
            f"console_idle_seconds BETWEEN {MIN_IDLE_SECONDS} AND {MAX_IDLE_SECONDS}"
            " AND portal_idle_seconds BETWEEN "
            f"{MIN_IDLE_SECONDS} AND {MAX_IDLE_SECONDS}",
            name="idle_range",
        ),
        CheckConstraint(
            "console_absolute_seconds BETWEEN console_idle_seconds AND "
            f"{SESSION_LIMITS['console']['max_absolute']}"
            " AND portal_absolute_seconds BETWEEN portal_idle_seconds AND "
            f"{SESSION_LIMITS['portal']['max_absolute']}",
            name="absolute_range",
        ),
        CheckConstraint("invitation_valid_days BETWEEN 1 AND 30", name="invitation_days_range"),
        CheckConstraint(
            "password_min_length BETWEEN 8 AND 64 AND password_history BETWEEN 0 AND 24"
            " AND password_expiry_days BETWEEN 0 AND 365",
            name="password_policy_range",
        ),
        CheckConstraint(
            f"password_policy_state IN {PASSWORD_POLICY_STATES!r}", name="password_policy_state"
        ),
        CheckConstraint("mfa_grace_days BETWEEN 0 AND 30", name="mfa_grace_days_range"),
        CheckConstraint(
            "sso_required IN ('off', 'technicians', 'everyone')", name="sso_required_code"
        ),
        CheckConstraint(
            f"cardinality(console_ip_allow) <= {IP_ALLOW_MAX}", name="console_ip_allow_size"
        ),
        CheckConstraint(
            f"cardinality(portal_ip_allow) <= {IP_ALLOW_MAX}", name="portal_ip_allow_size"
        ),
        CheckConstraint(f"cardinality(api_ip_allow) <= {IP_ALLOW_MAX}", name="api_ip_allow_size"),
    )

    console_idle_seconds: Mapped[int] = mapped_column(
        server_default=str(SESSION_LIMITS["console"]["idle"])
    )
    console_absolute_seconds: Mapped[int] = mapped_column(
        server_default=str(SESSION_LIMITS["console"]["absolute"])
    )
    portal_idle_seconds: Mapped[int] = mapped_column(
        server_default=str(SESSION_LIMITS["portal"]["idle"])
    )
    portal_absolute_seconds: Mapped[int] = mapped_column(
        server_default=str(SESSION_LIMITS["portal"]["absolute"])
    )
    # REQ-SEC-013: a first sign-in creates the person (as requester); off = invited or imported
    # people only.
    create_people_on_sign_in: Mapped[bool] = mapped_column(server_default="true")
    # REQ-SEC-020, Appendix A: how long an invitation link works (7 days; at most 30).
    invitation_valid_days: Mapped[int] = mapped_column(server_default="7")
    # REQ-PRT-013 AC2 (WP-028): people change their own phone and mobile; off by default.
    people_edit_contact: Mapped[bool] = mapped_column(server_default="false")
    # REQ-SEC-005, Appendix A (domain/password_policy.py): the installation's password policy,
    # which a worker writes into the realm. `default`: never edited here (the realm keeps what
    # the deploy gave it); `applying` until the worker wrote it; `failed` with the reason code.
    password_min_length: Mapped[int] = mapped_column(server_default="12")
    password_upper: Mapped[bool] = mapped_column(server_default="true")
    password_lower: Mapped[bool] = mapped_column(server_default="true")
    password_digits: Mapped[bool] = mapped_column(server_default="true")
    password_special: Mapped[bool] = mapped_column(server_default="true")
    password_history: Mapped[int] = mapped_column(server_default="5")
    password_expiry_days: Mapped[int] = mapped_column(server_default="0")
    password_breached_check: Mapped[bool] = mapped_column(server_default="true")
    password_policy_state: Mapped[str] = mapped_column(String(20), server_default="default")
    password_policy_error: Mapped[str | None] = mapped_column(String(60))
    # REQ-SEC-024, Appendix A: days a person has to enrol once MFA is required (7; 0 to 30).
    mfa_grace_days: Mapped[int] = mapped_column(server_default="7")
    # REQ-INT-019, REQ-SEC-037 (D-128): people may make API keys for themselves (off), and keys
    # without an expiry date are allowed (off: 90 days by default, at most a year).
    people_may_create_keys: Mapped[bool] = mapped_column(server_default="false")
    allow_non_expiring_keys: Mapped[bool] = mapped_column(server_default="false")
    # REQ-SEC-034 (WP-057 S1a, 0151): who may sign in or call, by address, per app. Empty = no
    # restriction; at most IP_ALLOW_MAX entries each. The API's list applies to API keys.
    console_ip_allow: Mapped[list[str]] = mapped_column(
        ARRAY(CIDR), server_default=text("'{}'::cidr[]")
    )
    portal_ip_allow: Mapped[list[str]] = mapped_column(
        ARRAY(CIDR), server_default=text("'{}'::cidr[]")
    )
    api_ip_allow: Mapped[list[str]] = mapped_column(
        ARRAY(CIDR), server_default=text("'{}'::cidr[]")
    )
    # REQ-SEC-009, REQ-SEC-026 (WP-057 S1b): single sign-on for nobody, technicians or everyone;
    # and SupportX's own MFA after a single sign-on too (off: the provider's MFA is trusted).
    sso_required: Mapped[str] = mapped_column(String(12), server_default="off")
    sso_also_require_mfa: Mapped[bool] = mapped_column(server_default="false")


MFA_MODES = ("off", "optional", "required")


class ApiKey(TenantEntity):
    """An API key (REQ-INT-019, D-128): a person's own, or a service identity's.

    Only the HMAC-SHA-256 of its secret is kept (`secret_hash`, under a server key outside the
    database) and its last four characters for the screen. A key acts as its owner, limited to
    its scopes; the owner's permissions are read live on every call, never stored here.
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 100", name="name_length"),
        CheckConstraint("cardinality(scopes) BETWEEN 1 AND 200", name="scopes_count"),
        CheckConstraint("cardinality(ip_allowlist) <= 20", name="allowlist_count"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_api_keys_owner"
        ),
        Index("ix_api_keys_tenant_owner", "tenant_id", "owner_id", "created_at"),
    )

    owner_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(100))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(80)))
    secret_hash: Mapped[bytes] = mapped_column(LargeBinary)
    last_four: Mapped[str] = mapped_column(String(4))
    expires_at: Mapped[datetime | None]
    ip_allowlist: Mapped[list[str]] = mapped_column(ARRAY(String(50)), server_default="{}")
    last_used_at: Mapped[datetime | None]
    last_used_ip: Mapped[str | None] = mapped_column(String(50))
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[uuid.UUID | None]


class MfaPolicy(TenantEntity):
    """MFA mode for one role of the tenant (REQ-SEC-024). No row: domain/mfa.py's default."""

    __tablename__ = "mfa_policies"
    __table_args__ = (
        CheckConstraint(f"mode IN {MFA_MODES!r}", name="mode_code"),
        ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="fk_mfa_policies_role"
        ),
        UniqueConstraint("tenant_id", "role_id", name="uq_mfa_policies_tenant_role"),
    )

    role_id: Mapped[uuid.UUID]
    mode: Mapped[str] = mapped_column(String(10))


SSO_PROTOCOLS = ("oidc", "saml")
SSO_PRESETS = ("entra", "okta", "google", "oidc", "saml")
SSO_STATES = ("draft", "tested", "on", "off")


class SsoProvider(TenantEntity):
    """One single sign-on set-up of a tenant (WP-039, REQ-SEC-007/008, D-094).

    Mirrors a Keycloak identity provider linked to the tenant's organization (`alias`). The
    client secret lives only in Keycloak (write-only, REQ-SEC-042): never in this row.
    """

    __tablename__ = "sso_providers"
    __table_args__ = (
        CheckConstraint("protocol IN ('oidc', 'saml')", name="protocol_code"),
        CheckConstraint(
            "preset IN ('entra', 'okta', 'google', 'oidc', 'saml')", name="preset_code"
        ),
        CheckConstraint("state IN ('draft', 'tested', 'on', 'off')", name="state_code"),
        UniqueConstraint("tenant_id", "alias", name="uq_sso_providers_tenant_alias"),
        # Lets the expiry marks point at a provider of their own tenant only (0158).
        UniqueConstraint("tenant_id", "id", name="uq_sso_providers_tenant_id_id"),
        Index("ix_sso_providers_tenant_state", "tenant_id", "state"),
    )

    alias: Mapped[str] = mapped_column(String(60))
    protocol: Mapped[str] = mapped_column(String(10))
    preset: Mapped[str] = mapped_column(String(10))
    display_name: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(10), server_default="draft")
    # Non-secret connection settings and attribute mapping (shape per protocol: service/sso.py).
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    domains: Mapped[list[str]] = mapped_column(ARRAY(String(253)), server_default="{}")
    # Send people whose email domain matches straight to this provider (off by default, D-094).
    email_redirect: Mapped[bool] = mapped_column(server_default="false")
    # The last connection check: {"ok": bool, "problems": [codes], "checked_at": iso}.
    last_check: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tested_at: Mapped[datetime | None]
    tested_by: Mapped[uuid.UUID | None]
    switched_on_at: Mapped[datetime | None]
    # When the OIDC client secret runs out (REQ-SEC-011, WP-057 S2b-2; 0158): entered by an admin
    # from the identity provider's own console. SupportX never reads the secret itself.
    client_secret_expires_at: Mapped[datetime | None]


INVITATION_STATES = ("pending", "accepted", "revoked")
INVITATION_DELIVERY = ("email", "existing_account")


class Invitation(TenantEntity):
    """An invitation of a person to sign in (WP-039 session 2; REQ-SEC-018..020, D-099).

    Keycloak sends the e-mail (its update-password e-mail in the tenant's brand); SupportX keeps
    the life cycle. "Expired" is not stored: a pending invitation past `expires_at` is expired.
    """

    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'accepted', 'revoked')", name="status_code"),
        CheckConstraint("delivery IN ('email', 'existing_account')", name="delivery_code"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_invitations_user"
        ),
        Index("ix_invitations_tenant_user", "tenant_id", "user_id", "status"),
        CheckConstraint(
            "link_token_hash IS NULL OR octet_length(link_token_hash) = 32",
            name="link_token_hash_length",
        ),
        Index(
            "uq_invitations_link_token",
            "tenant_id",
            "link_token_hash",
            unique=True,
            postgresql_where=text("link_token_hash IS NOT NULL"),
        ),
        Index("ix_invitations_tenant_created", "tenant_id", "created_at", "id"),
    )

    user_id: Mapped[uuid.UUID]
    email: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(10), server_default="pending")
    delivery: Mapped[str] = mapped_column(String(20), server_default="email")
    keycloak_user_id: Mapped[str | None] = mapped_column(String(64))
    # SupportX made the Keycloak account for this invitation (revoking an unused one deletes it).
    created_account: Mapped[bool] = mapped_column(server_default="false")
    sent_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    sends: Mapped[int] = mapped_column(server_default="1")
    # The copied invite link (REQ-SEC-021, WP-057 S2b-2; 0158): only the SHA-256 of its token,
    # single use, valid until `expires_at`; copying again replaces it. Offered without mail only.
    link_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    link_copied_at: Mapped[datetime | None]


class UserCostRate(TenantEntity):
    """A person's cost per hour from a moment on (REQ-INC-068; migration 0148).

    The rate in force at a moment is the latest live row starting at or before it. The currency
    is the tenant's base currency when the rate was set. Money: only `users.view_cost_rates`
    reads it over the API; it never joins the person's record, lists, search or events.
    """

    __tablename__ = "user_cost_rates"
    __table_args__ = (
        CheckConstraint("rate >= 0", name="rate_not_negative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_code"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_user_cost_rates_user",
        ),
        Index(
            "uq_user_cost_rates_start",
            "tenant_id",
            "user_id",
            "effective_from",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_user_cost_rates_in_force", "tenant_id", "user_id", text("effective_from DESC")),
    )

    user_id: Mapped[uuid.UUID]
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    effective_from: Mapped[datetime]


class SessionKeyId(Timestamps, Actors, Base):
    """A sign-in session key ID the installation has listed (D-162, ADR-048; migration 0146).

    Platform table: no tenant_id, the ring is one per installation. IDs only, never key
    material. Not edited by people (start-up records it), so it carries no version.
    """

    __tablename__ = "session_key_ids"
    __table_args__ = (CheckConstraint("key_id ~ '^[a-z0-9_-]{1,32}$'", name="key_id_format"),)

    key_id: Mapped[str] = mapped_column(String, primary_key=True)
    first_seen_at: Mapped[datetime]
    retired_at: Mapped[datetime | None]


SESSION_KEY_ACTIONS = ("security.session_key_rotated", "security.session_key_retired")


class SessionKeyEvent(Timestamps, Actors, Base):
    """One claimed change of the sign-in key ring, waiting to be announced (D-162; 0146).

    Platform table: written by the start-up that won the claim, read by the announcer, which
    sets `announced_at` once every tenant has its entry. IDs and counts only, never material.
    """

    __tablename__ = "session_key_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('security.session_key_rotated', 'security.session_key_retired')",
            name="action_code",
        ),
        CheckConstraint("key_id ~ '^[a-z0-9_-]{1,32}$'", name="key_id_format"),
        CheckConstraint(
            "previous_key_id IS NULL OR previous_key_id ~ '^[a-z0-9_-]{1,32}$'",
            name="previous_key_id_format",
        ),
        CheckConstraint("readable_keys BETWEEN 0 AND 64", name="readable_keys_range"),
        Index(
            "ix_session_key_events_pending",
            "occurred_at",
            postgresql_where=text("announced_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    key_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    previous_key_id: Mapped[str | None] = mapped_column(String)
    readable_keys: Mapped[int] = mapped_column(SmallInteger)
    occurred_at: Mapped[datetime]
    announced_at: Mapped[datetime | None]


class SessionKeyAnnouncement(TenantKeyed, Timestamps, Actors, Base):
    """A key-ring change already written into this tenant's audit log (D-162; 0146).

    Inserted in the same transaction as the audit entry, unique per tenant and change: a crash
    rolls both back, a second run finds the row and writes nothing. Never edited.
    """

    __tablename__ = "session_key_announcements"
    __table_args__ = (
        ForeignKeyConstraint(["event_id"], ["session_key_events.id"], ondelete="RESTRICT"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    key_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)


SIGN_IN_OUTCOMES = tuple(o.value for o in SignInOutcome)
SIGN_IN_METHODS = tuple(m.value for m in SignInMethod)
SIGN_IN_APPS = tuple(a.value for a in SignInApp)
SIGN_IN_SOURCES = tuple(s.value for s in Source)


def _codes(column: str, codes: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(c) for c in codes)})"


class SignInEvent(TenantKeyed, Base):
    """One sign-in event of a tenant (REQ-AUD-015; WP-057 S1a, migration 0151).

    Append-only, like connector_runs: written by the BFF for what it decides and imported from
    Keycloak's events for what Keycloak decides, only into the tenant whose own address or
    organization the attempt carried. `ip` and `device` are personal data: nulled by erasure,
    gone with the row after the retention. `user_id` only when the person is known: never the
    name typed for an unknown one (people type passwords there).
    """

    __tablename__ = "sign_in_events"
    __table_args__ = (
        CheckConstraint(_codes("outcome", SIGN_IN_OUTCOMES), name="outcome_code"),
        CheckConstraint(_codes("method", SIGN_IN_METHODS), name="method_code"),
        CheckConstraint(_codes("app", SIGN_IN_APPS), name="app_code"),
        CheckConstraint(_codes("source", SIGN_IN_SOURCES), name="source_code"),
        CheckConstraint(
            "(source = 'keycloak') = (keycloak_event_id IS NOT NULL)", name="keycloak_event_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_sign_in_events_user",
        ),
        Index("ix_sign_in_events_recent", "tenant_id", text("occurred_at DESC")),
        Index(
            "ix_sign_in_events_person",
            "tenant_id",
            "user_id",
            text("occurred_at DESC"),
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_sign_in_events_keycloak",
            "tenant_id",
            "keycloak_event_id",
            unique=True,
            postgresql_where=text("keycloak_event_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID | None]
    occurred_at: Mapped[datetime]
    outcome: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(60))
    method: Mapped[str] = mapped_column(String(20))
    app: Mapped[str] = mapped_column(String(10))
    ip: Mapped[str | None] = mapped_column(INET)
    device: Mapped[str | None] = mapped_column(String(120))
    identity_provider: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(10))
    keycloak_event_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SignInImportCursor(Base):
    """How far the Keycloak events import got, per realm (0151). Installation-wide."""

    __tablename__ = "sign_in_import_cursor"
    __table_args__ = (CheckConstraint("last_offset >= 0", name="last_offset_not_negative"),)

    realm: Mapped[str] = mapped_column(String(60), primary_key=True)
    last_time_ms: Mapped[int]
    # Events of last_time_ms already read, when one millisecond held more than a run (0153).
    last_offset: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class SiteNetwork(TenantKeyed, Timestamps, Actors, Base):
    """An admin's address range → site, for the sign-in place (WP-057 S2b, D-170; 0157).

    Edited as one list with the tenant's identity settings (their `version` is the If-Match), so
    rows have no version of their own. The most specific prefix wins (domain/place.py). At most
    MAX_SITE_NETWORKS per tenant, checked by the service; one row per range.
    """

    __tablename__ = "site_networks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"], name="fk_site_networks_site"
        ),
        UniqueConstraint("tenant_id", "network", name="uq_site_networks_network"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    network: Mapped[str] = mapped_column(CIDR)
    site_id: Mapped[uuid.UUID]


class KnownDevice(TenantKeyed, Timestamps, Base):
    """A browser or device a person has signed in from before (REQ-SEC-033; WP-057 S2b; 0157).

    Only a keyed fingerprint: HMAC(the "known-device" key of the ADR-048 ring, user, device code,
    the address's /24 or /48). Never the address or the browser string, so the table reveals
    nothing on its own. A sign-in whose fingerprint is new sends the person a notice. Erasure
    deletes the person's rows.
    """

    __tablename__ = "known_devices"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_known_devices_user"
        ),
        UniqueConstraint("tenant_id", "user_id", "fingerprint", name="uq_known_devices_print"),
        CheckConstraint("octet_length(fingerprint) = 32", name="fingerprint_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID]
    fingerprint: Mapped[bytes] = mapped_column(LargeBinary)
    last_seen_at: Mapped[datetime]


EXPIRY_THRESHOLDS = (0, 1, 7, 30)  # domain/expiry.py: days before, 0 = run out


class SecurityExpiryMark(TenantKeyed, Base):
    """An expiry alert already sent (REQ-SEC-011; WP-057 S2b-2; 0158), so each goes once.

    `item` names what runs out: a SAML signing certificate by its SHA-256 fingerprint, or
    `client_secret`. Append-only; the daily schedule writes one row per alert (and per threshold
    a late run passes over).
    """

    __tablename__ = "security_expiry_marks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "provider_id"],
            ["sso_providers.tenant_id", "sso_providers.id"],
            name="fk_security_expiry_marks_provider",
        ),
        UniqueConstraint(
            "tenant_id", "provider_id", "item", "threshold", name="uq_security_expiry_marks_once"
        ),
        CheckConstraint(
            "threshold IN (" + ", ".join(str(t) for t in EXPIRY_THRESHOLDS) + ")",
            name="threshold_code",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    provider_id: Mapped[uuid.UUID]
    item: Mapped[str] = mapped_column(String(64))
    threshold: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
