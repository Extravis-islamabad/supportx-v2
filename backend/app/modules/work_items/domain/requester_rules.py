"""What a requester may do to their own record after submitting (WP-046b S5; REQ-INC-148).

Pure domain, no I/O: the tenant's per-type rules and the life of a cancellation ask.
"""

from enum import StrEnum


class RequesterCancel(StrEnum):
    """Whether a requester may cancel their own record: never, directly, or by asking."""

    OFF = "off"  # as every tenant is today: only staff cancel
    DIRECT = "direct"
    ASK = "ask"


class CancellationState(StrEnum):
    """A requester's ask to cancel (AC1): waiting, then decided or taken back."""

    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


# Fields a requester may ever be allowed to edit: what they could fill when reporting, never
# staff-only ones (group, technician, priority, status, due times; the coordinator's test).
STAFF_ONLY_FIELDS = frozenset(
    {
        "group_id",
        "technician_id",
        "priority",
        "status",
        "status_category",
        "resolution_due_at",
        "response_due_at",
        "category_id",
        "subcategory_id",
        "item_id",
        "level",
        "tags",
    }
)
REQUESTER_EDITABLE = frozenset({"subject", "description", "impact", "urgency", "impact_details"})


def editable_by_requester(field: str, allowed: frozenset[str]) -> bool:
    """A field the tenant lets requesters edit, and one they may ever edit at all."""
    if field in STAFF_ONLY_FIELDS:
        return False
    if field.startswith("custom."):
        return field in allowed
    return field in REQUESTER_EDITABLE and field in allowed
