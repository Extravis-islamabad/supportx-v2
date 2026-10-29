"""Event contracts published by identity_access (WP-007; docs/architecture/events.md).

Payloads carry IDs and codes only (architecture.md §8.2): no email address, name, token or
session ID ever goes into an event. Consumers that need more ask identity_access.
"""

import uuid
from typing import ClassVar, Literal

from app.shared.events import DomainEvent

ClientApp = Literal["console", "portal"]


class UserProvisioned(DomainEvent):
    """A user signed in to a tenant for the first time and got a user record there."""

    event_type: ClassVar[str] = "identity_access.user.provisioned"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    user_type: Literal["technician", "requester"]
    locale: str


class UserUpdated(DomainEvent):
    """Profile fields changed (names only, never values).

    Preferences edited by the user (WP-008), the person record edited by an admin (WP-021), or
    `sign_in_linked` when a person added by an admin first signs in (D-092).
    """

    event_type: ClassVar[str] = "identity_access.user.updated"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    changed_fields: list[str]


class UserLoggedIn(DomainEvent):
    """A user started a session in this tenant."""

    event_type: ClassVar[str] = "identity_access.user.logged_in"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    client: ClientApp


class UserLoggedOut(DomainEvent):
    """A user ended their session in this tenant."""

    event_type: ClassVar[str] = "identity_access.user.logged_out"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    client: ClientApp


class SessionTenantSwitched(DomainEvent):
    """A signed-in user moved their session into this tenant.

    Published in the tenant switched TO only; the previous tenant is deliberately not named, so
    one tenant's subscribers never learn which other tenants a user belongs to.
    """

    event_type: ClassVar[str] = "identity_access.session.tenant_switched"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"  # the session ID is a secret; the user is the subject

    user_id: uuid.UUID
    client: ClientApp


class RoleChanged(DomainEvent):
    """A role was created, edited (name, description, permissions) or deleted (WP-016)."""

    event_type: ClassVar[str] = "identity_access.role.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "role"

    role_id: uuid.UUID
    change: Literal["created", "updated", "deleted"]
    changed_fields: list[str]


class UserRoleChanged(DomainEvent):
    """A role was assigned to or removed from a user (WP-016)."""

    event_type: ClassVar[str] = "identity_access.user_role.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    role_id: uuid.UUID
    change: Literal["assigned", "removed"]


class UserCreated(DomainEvent):
    """An admin or an import added a person before their first sign-in (WP-021)."""

    event_type: ClassVar[str] = "identity_access.user.created"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    user_type: Literal["technician", "requester"]
    source: Literal["admin", "import"]


class UserCreatedV2(DomainEvent):
    """As UserCreated, with `email` as a source: a mail sender made a requester (WP-024).

    A new allowed value retypes a field, so a new schema version (docs/architecture/events.md
    "Versioning"); v1 stays registered for anything that still reads it. Published from WP-024 on.
    """

    event_type: ClassVar[str] = "identity_access.user.created"
    schema_version: ClassVar[int] = 2
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    user_type: Literal["technician", "requester"]
    source: Literal["admin", "import", "email"]


class UserStatusChanged(DomainEvent):
    """A person was deactivated or reactivated (WP-021); a deactivated person cannot sign in."""

    event_type: ClassVar[str] = "identity_access.user.status_changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    status: Literal["active", "disabled"]


class PeopleImportProgressed(DomainEvent):
    """A people import moved on (WP-021): counts only, for the live progress bar."""

    event_type: ClassVar[str] = "identity_access.people_import.progressed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "people_import"

    import_id: uuid.UUID
    status: Literal["queued", "running", "done", "failed"]
    processed: int
    total: int


class AccessSettingsChanged(DomainEvent):
    """The tenant's access defaults changed (WP-021, D-073): compiled permissions refresh."""

    event_type: ClassVar[str] = "identity_access.access_settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "tenant"

    changed_fields: list[str]


class IdentitySettingsChanged(DomainEvent):
    """The tenant's sign-in settings changed (WP-039).

    Sessions, people creation, invitations, the password policy, or the worker's result
    applying it (`password_policy_state`).
    """

    event_type: ClassVar[str] = "identity_access.identity_settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "tenant"

    changed_fields: list[str]


class PasswordPolicyChanged(DomainEvent):
    """An admin saved the password policy, or asked to apply it again.

    The worker writes it into the realm, reading it from the settings when applied, so only the
    newest policy is ever written.
    """

    event_type: ClassVar[str] = "identity_access.password_policy.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "tenant"


class MfaChanged(DomainEvent):
    """An MFA policy, a person's enrolment or an admin reset changed (WP-039 session 3)."""

    event_type: ClassVar[str] = "identity_access.mfa.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "tenant"

    change: Literal["policy", "enrolled", "reset"]
    role_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None


class SsoProviderChanged(DomainEvent):
    """A single sign-on set-up was added, changed, tested, switched on or off, or removed."""

    event_type: ClassVar[str] = "identity_access.sso_provider.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sso_provider"

    change: Literal["added", "updated", "tested", "switched_on", "switched_off", "removed"]
    state: Literal["draft", "tested", "on", "off"]


class InvitationChanged(DomainEvent):
    """An invitation was sent, resent, accepted or revoked (WP-039 session 2)."""

    event_type: ClassVar[str] = "identity_access.invitation.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "invitation"

    change: Literal["sent", "resent", "accepted", "revoked"]
    status: Literal["pending", "accepted", "revoked"]


EVENTS: tuple[type[DomainEvent], ...] = (
    UserProvisioned,
    UserUpdated,
    UserLoggedIn,
    UserLoggedOut,
    SessionTenantSwitched,
    RoleChanged,
    UserRoleChanged,
    UserCreated,
    UserCreatedV2,
    UserStatusChanged,
    PeopleImportProgressed,
    AccessSettingsChanged,
    IdentitySettingsChanged,
    PasswordPolicyChanged,
    MfaChanged,
    SsoProviderChanged,
    InvitationChanged,
)
