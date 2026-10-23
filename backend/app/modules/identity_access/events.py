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

    Either synced from Keycloak at login, or SupportX-owned preferences edited by the user (WP-008).
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


EVENTS: tuple[type[DomainEvent], ...] = (
    UserProvisioned,
    UserUpdated,
    UserLoggedIn,
    UserLoggedOut,
    SessionTenantSwitched,
    RoleChanged,
    UserRoleChanged,
)
