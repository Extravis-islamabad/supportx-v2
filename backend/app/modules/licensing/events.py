"""Event contracts published by licensing (WP-009; docs/architecture/events.md).

Payloads carry codes only (architecture.md §8.2): no customer name, licence ID or signature.
"""

from typing import ClassVar, Literal

from app.shared.events import DomainEvent

ChangeSource = Literal["subscription", "licence"]


class EntitlementChanged(DomainEvent):
    """The tenant's entitlement changed (plan, add-ons, limits, term or status).

    Consumers: the entitlement cache invalidation (this module); later the realtime fan-out
    (WP-011) so open consoles re-read GET /api/v1/entitlements and show or hide menus live.
    """

    event_type: ClassVar[str] = "licensing.entitlement.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "entitlement"

    source: ChangeSource
    changed_fields: list[str]


EVENTS: tuple[type[DomainEvent], ...] = (EntitlementChanged,)
