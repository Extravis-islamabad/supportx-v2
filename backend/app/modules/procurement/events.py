"""Event contracts published by the procurement module (WP-049a s2: vendors).

Payloads carry IDs and changed field *names* only, never a vendor's name or contact details
(architecture.md §8.2). Consumers that need more read it through the module's service.
"""

import uuid
from typing import ClassVar, Literal

from app.shared.events import DomainEvent

VendorAction = Literal["created", "updated", "deleted"]


class VendorChanged(DomainEvent):
    """A vendor was added, changed or moved to the trash (REQ-PUR-001)."""

    event_type: ClassVar[str] = "procurement.vendor.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "vendor"

    vendor_id: uuid.UUID
    action: VendorAction
    changed_fields: list[str]


EVENTS: tuple[type[DomainEvent], ...] = (VendorChanged,)
