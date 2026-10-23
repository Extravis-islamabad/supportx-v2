"""Event contracts published by the organization module (WP-016).

Sites and support groups and their memberships: memberships change what users may see
(`site`/`group` scopes), so identity_access consumes the membership events to refresh compiled
permissions. Payloads carry IDs only (architecture.md §8.2).
"""

import uuid
from typing import ClassVar, Literal

from app.shared.events import DomainEvent

UnitKind = Literal["site", "group"]


class SiteChanged(DomainEvent):
    """A site was created or renamed."""

    event_type: ClassVar[str] = "organization.site.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "site"

    site_id: uuid.UUID
    changed_fields: list[str]


class SupportGroupChanged(DomainEvent):
    """A support group was created or renamed."""

    event_type: ClassVar[str] = "organization.support_group.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "support_group"

    group_id: uuid.UUID
    changed_fields: list[str]


class MembershipChanged(DomainEvent):
    """A user was added to or removed from a site or support group."""

    event_type: ClassVar[str] = "organization.membership.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "membership"

    kind: UnitKind
    unit_id: uuid.UUID
    user_id: uuid.UUID
    change: Literal["added", "removed"]


EVENTS: tuple[type[DomainEvent], ...] = (SiteChanged, SupportGroupChanged, MembershipChanged)
