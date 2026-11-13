"""Event contracts published by identity_access (WP-007; docs/architecture/events.md).

Payloads carry IDs and codes only (architecture.md §8.2): no email address, name, token or
session ID ever goes into an event. Consumers that need more ask identity_access. One stated
exception (ADR-051): `keycloak_session.end_pending` names Keycloak's own session ID, an identifier
that authorises nothing (ending it takes the identity service account); a SupportX session ID or
any token never.
"""

import uuid
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

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
    # The manager before and after, when the manager changed: both recount their "direct
    # reports" (WP-020d QA BUG-01). Empty otherwise.
    managers: list[uuid.UUID] = Field(default_factory=list)


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


class KeycloakSessionEndPending(DomainEvent):
    """A sign-out ended the SupportX session while Keycloak was unreachable (ADR-051).

    The person is signed out of SupportX already; this asks the consumers worker to end their
    Keycloak session too, through the admin API, once Keycloak answers again. No token: the
    session ID is enough for the admin API and authorises nothing on its own.
    """

    event_type: ClassVar[str] = "identity_access.keycloak_session.end_pending"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    keycloak_session_id: str = Field(min_length=1, max_length=128)


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


class GroupRoleChanged(DomainEvent):
    """A support group gained or lost a role: its members' access changes (WP-042)."""

    event_type: ClassVar[str] = "identity_access.group_role.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "group"

    group_id: uuid.UUID
    role_id: uuid.UUID
    change: Literal["added", "removed"]


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


class UserCreatedV3(DomainEvent):
    """As UserCreatedV2, with service identities: a connector's own identity (WP-040).

    `service` and `integration` are new allowed values, so a new schema version; v1 and v2 stay
    registered. A service identity never signs in and is never in people lists.
    """

    event_type: ClassVar[str] = "identity_access.user.created"
    schema_version: ClassVar[int] = 3
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    user_type: Literal["technician", "requester", "service"]
    source: Literal["admin", "import", "email", "integration"]


class UserCreatedV4(DomainEvent):
    """As UserCreatedV3, with `workflow` as a source: a workflow's run-as identity (WP-048b).

    A new allowed value, so a new schema version; v1 to v3 stay registered.
    """

    event_type: ClassVar[str] = "identity_access.user.created"
    schema_version: ClassVar[int] = 4
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    user_type: Literal["technician", "requester", "service"]
    source: Literal["admin", "import", "email", "integration", "workflow"]


class UserStatusChanged(DomainEvent):
    """A person was deactivated or reactivated (WP-021); a deactivated person cannot sign in.

    WP-040 (agreed with lane A, 2026-10-29) adds two defaulted fields, so the contract stays v1
    and older events still read: `reason` says who made the change (an admin, the directory sync
    or a privacy erasure) and `source` which directory, when it was the sync. Lane A's
    "needs reassignment" view flags a leaver's open incidents from `reason = "directory"`.
    """

    event_type: ClassVar[str] = "identity_access.user.status_changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    status: Literal["active", "disabled"]
    reason: Literal["admin", "directory", "erasure"] = "admin"
    source: Literal["entra", "ldap"] | None = None


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


class ApiKeyChanged(DomainEvent):
    """An API key was made or revoked (WP-041, D-128): key screens refetch. Never the key text."""

    event_type: ClassVar[str] = "identity_access.api_key.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "api_key"

    change: Literal["created", "revoked"]
    owner_id: uuid.UUID


class UserCostRateChanged(DomainEvent):
    """A person's cost per hour was set, changed or removed (REQ-INC-068).

    IDs and the kind of change only, never the amount: screens with `users.view_cost_rates`
    refetch the person's rates.
    """

    event_type: ClassVar[str] = "identity_access.user_cost_rate.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user_cost_rate"

    user_id: uuid.UUID
    change: Literal["created", "updated", "deleted"]


class SignInRecorded(DomainEvent):
    """A sign-in event was written to the tenant's log (REQ-AUD-015; WP-057 S1a).

    The outcome only, never the person, address or device: open sign-in logs refetch.
    """

    event_type: ClassVar[str] = "identity_access.sign_in.recorded"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sign_in_event"

    outcome: Literal["success", "failed", "signed_out", "locked", "mfa_failed"]


class BreakGlassSignedIn(DomainEvent):
    """A break-glass admin signed in with a password while single sign-on is required.

    REQ-SEC-009 AC3 (WP-057 S1b): every other tenant admin is told. IDs only.
    """

    event_type: ClassVar[str] = "identity_access.break_glass.signed_in"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID


class NewDeviceSignedIn(DomainEvent):
    """A person signed in from a browser or device they have not used before (REQ-SEC-033).

    WP-057 S2b-1: they are told (a locked security notice), never on their first sign-in ever.
    Carries the device code (domain/sign_in.device, never the User-Agent) and the approximate
    place (domain/place.py's stored form), never the address: the known_devices table keeps only
    a keyed fingerprint, so the notice can only say this from the event. Internal (the outbox and
    the notification consumer), never sent to a browser.
    """

    event_type: ClassVar[str] = "identity_access.new_device.signed_in"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    device: str | None
    place: dict[str, str] | None
    signed_in_at: datetime


class PersonErasureChanged(DomainEvent):
    """A GDPR erasure was requested, approved, rejected, expired, or its job moved on (ADR-052).

    IDs, the state code and the next step only (never a name or a reason): the erasure screens
    of people who may erase refetch, and the person's own record follows the step's changes
    through its ordinary events.
    """

    event_type: ClassVar[str] = "identity_access.person_erasure.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "person_erasure"

    person_id: uuid.UUID
    state: Literal["requested", "approved", "running", "done", "rejected", "expired", "failed"]
    step: int = Field(ge=0, le=8)


class PersonErasureCompleted(DomainEvent):
    """A person was erased (ADR-052 step 7), after `user.status_changed` with reason `erasure`.

    For consumers that act once the whole erasure is done (exports, caches). The person's ID only.
    """

    event_type: ClassVar[str] = "identity_access.person_erasure.completed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    person_id: uuid.UUID
    erasure_id: uuid.UUID


class AccountSecurityChanged(DomainEvent):
    """The person's account was locked out, or its password or MFA changed (REQ-SEC-033 part 2).

    WP-057 S2b-2: read from Keycloak's user events by the events import, once per Keycloak event
    (security_notice_marks), and told to the person (a locked security notice). `opens_at` is a
    lock-out's earliest end, a lower bound (lane B). No address: the place only, as the new-device
    notice. Internal (the outbox and the notification consumer), never sent to a browser.
    """

    event_type: ClassVar[str] = "identity_access.account_security.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    kind: Literal["locked_out", "password_changed", "mfa_added", "mfa_removed"]
    occurred_at: datetime
    opens_at: datetime | None
    place: dict[str, str] | None


class SignInSecretExpiring(DomainEvent):
    """A sign-in certificate or client secret is about to run out, or has (REQ-SEC-011).

    WP-057 S2b-2: the tenant's admins are told, once per threshold (30, 7, 1 days; 0 = run out).
    IDs and codes only: the provider, which kind of item, the threshold and the date.
    """

    event_type: ClassVar[str] = "identity_access.sign_in_secret.expiring"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sso_provider"

    provider_id: uuid.UUID
    item: Literal["certificate", "client_secret"]
    days_left: int
    expires_at: datetime


class InvitationLinkCopied(DomainEvent):
    """An admin copied a single-use invite link for a pending invitation (REQ-SEC-021).

    WP-057 S2b-2. Its own event (not a new `change` of the v1 InvitationChanged contract). IDs
    only; never the link or its token.
    """

    event_type: ClassVar[str] = "identity_access.invitation.link_copied"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "invitation"


EVENTS: tuple[type[DomainEvent], ...] = (
    UserProvisioned,
    UserUpdated,
    UserLoggedIn,
    UserLoggedOut,
    KeycloakSessionEndPending,
    SessionTenantSwitched,
    RoleChanged,
    UserRoleChanged,
    GroupRoleChanged,
    UserCreated,
    UserCreatedV2,
    UserCreatedV3,
    UserCreatedV4,
    UserStatusChanged,
    PeopleImportProgressed,
    AccessSettingsChanged,
    IdentitySettingsChanged,
    PasswordPolicyChanged,
    MfaChanged,
    SsoProviderChanged,
    InvitationChanged,
    ApiKeyChanged,
    UserCostRateChanged,
    SignInRecorded,
    BreakGlassSignedIn,
    NewDeviceSignedIn,
    PersonErasureChanged,
    PersonErasureCompleted,
    AccountSecurityChanged,
    SignInSecretExpiring,
    InvitationLinkCopied,
)
