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


class CancellationDeciders(StrEnum):
    """Who decides a waiting ask (the coordinator's Q2 and its conditions, 2026-11-21).

    The assignee; with none, the group's members who may edit it; with none of those, the
    type's service desk managers (audited, and the requester told); with none at all, nobody
    yet: the ask stays open and says so, and a log line flags it, never lost.
    """

    ASSIGNEE = "assignee"
    GROUP = "group"
    MANAGERS = "managers"
    NONE = "none"


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


def editable_by_requester(
    field: str, allowed: frozenset[str], shown: frozenset[str] | None = None
) -> bool:
    """A field the tenant lets requesters edit, one they may ever edit, and one they can see.

    `shown`: the fields the portal returns for this record (its template's rules); a field the
    requester cannot read is never theirs to write. Custom fields never are: the portal shows
    requesters none, so a staff-only, restricted (ADR-047) or sealed one could otherwise be
    written blind (lane C's B2 on #572).
    """
    if field in STAFF_ONLY_FIELDS or field.startswith("custom."):
        return False
    if shown is not None and field not in shown:
        return False
    return field in REQUESTER_EDITABLE and field in allowed
