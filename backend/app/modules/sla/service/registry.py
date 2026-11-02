"""Record types that have SLAs (WP-025; wp-025-plan.md §3.1, the same pattern as automation).

The sla module never reads work-item tables. A record type registers here when its module is
imported: the fields its policy conditions may use (the shared filter DSL), and nothing else.
Inside a save, the owning module passes a snapshot of the record (field name -> value) to
`sla.on_change`, which returns what to stamp on the record. So `sla` never imports `work_items`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.shared.api.filters import ResourceFields

# The snapshot keys the clock itself reads (beyond the condition fields).
PRIORITY = "priority"
SITE = "site_id"
GROUP = "group_id"
STATUS_CATEGORY = "status_category"
STATUS = "status"
FIRST_RESPONDED_AT = "first_responded_at"

Snapshot = Mapping[str, Any]


@dataclass(frozen=True)
class SlaRecordType:
    """One record type with SLAs."""

    code: str  # "incident"
    fields: ResourceFields  # what conditions may filter on (validated and evaluated in memory)
    priorities: tuple[str, ...]  # its priority codes, highest first ("p1" ... "p4")


_TYPES: dict[str, SlaRecordType] = {}


def register_record_type(record_type: SlaRecordType) -> None:
    """Called by the owning module when it is imported (idempotent)."""
    _TYPES[record_type.code] = record_type


def record_type(code: str) -> SlaRecordType | None:
    """A registered record type, or None."""
    return _TYPES.get(code)


def record_types() -> list[str]:
    """Every registered record type code."""
    return sorted(_TYPES)
