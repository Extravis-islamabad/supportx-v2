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
    """A site was created, changed, made inactive or removed."""

    event_type: ClassVar[str] = "organization.site.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "site"

    site_id: uuid.UUID
    changed_fields: list[str]


class SupportGroupChanged(DomainEvent):
    """A support group was created, changed, made inactive or removed."""

    event_type: ClassVar[str] = "organization.support_group.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "support_group"

    group_id: uuid.UUID
    changed_fields: list[str]


class DepartmentChanged(DomainEvent):
    """A department was created, changed, made inactive or removed (WP-021)."""

    event_type: ClassVar[str] = "organization.department.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "department"

    department_id: uuid.UUID
    changed_fields: list[str]


class DeskChanged(DomainEvent):
    """A desk was created or changed (WP-021, ESM)."""

    event_type: ClassVar[str] = "organization.desk.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "desk"

    desk_id: uuid.UUID
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


EVENTS: tuple[type[DomainEvent], ...] = (
    SiteChanged,
    SupportGroupChanged,
    DepartmentChanged,
    DeskChanged,
    MembershipChanged,
)
