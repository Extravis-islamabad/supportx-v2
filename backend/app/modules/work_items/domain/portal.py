"""The requester's side of an incident (WP-028; ~/Desktop/wp-028-plan.md D1-D3).

Pure rules, no I/O:

- `portal_status`: the plain-language status a requester sees (REQ-INC-147 AC2: no
  technician-only status). Waiting on a third party is staff business: it shows as in progress.
- `requester_fields`: which record fields the portal returns. An **allow-list**: a field the
  staff view gains later never reaches a requester by default (REQ-PRT-007 AC4). Staff-only
  fields are refused whatever a template says.
- `PortalReach` and `reaches`: which records a person may see in the portal (REQ-INC-147,
  REQ-PRT-007 AC1/AC2). `own` is the requester or the person it is for; wider reach comes from
  permissions (D2, pending the product owner: kept behind `service/portal.py`'s one scope check).
"""

import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from app.modules.work_items.domain.lifecycle import (
    DefaultStatus,
    ServiceRequestStatus,
    StatusCategory,
)
from app.modules.work_items.domain.templates import FieldRule, TemplateField


class KnownProblem(StrEnum):
    """What a requester is told of the problem behind their incident (REQ-PRB-075).

    Never the problem itself: only that the issue is known and being worked on, or that it was
    fixed. A problem being opened, cancelled or merged away says nothing.
    """

    BEING_WORKED_ON = "being_worked_on"
    FIXED = "fixed"


def known_problem(category: str | None) -> KnownProblem | None:
    """The requester's word for the causing problem's status category (None: say nothing)."""
    if category in {StatusCategory.RESOLVED.value, StatusCategory.CLOSED.value}:
        return KnownProblem.FIXED
    if category in {StatusCategory.OPEN.value, StatusCategory.PAUSED.value}:
        return KnownProblem.BEING_WORKED_ON
    return None


class PortalStatus(StrEnum):
    """What a requester is told about their incident."""

    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_YOU = "waiting_for_you"
    RESOLVED = "resolved"  # a fix was given: confirm or reject it
    CLOSED = "closed"
    CANCELED = "canceled"
    # Service requests (WP-030 D9): waiting for its approval; ended by a rejection.
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"


_BY_CATEGORY: Mapping[StatusCategory, PortalStatus] = {
    StatusCategory.OPEN: PortalStatus.IN_PROGRESS,
    # Paused on someone else (a third party, a custom pause): still being handled for them.
    StatusCategory.PAUSED: PortalStatus.IN_PROGRESS,
    StatusCategory.RESOLVED: PortalStatus.RESOLVED,
    StatusCategory.CLOSED: PortalStatus.CLOSED,
    StatusCategory.CANCELED: PortalStatus.CANCELED,
}


def portal_status(code: str, category: StatusCategory) -> PortalStatus:
    """The requester's status for a record's status code and its category.

    Custom statuses (a tenant's own) follow their category, so a new status never shows its
    internal name in the portal.
    """
    if code == DefaultStatus.NEW:
        return PortalStatus.RECEIVED
    if code == DefaultStatus.AWAITING_REQUESTER:
        return PortalStatus.WAITING_FOR_YOU
    if code == ServiceRequestStatus.AWAITING_APPROVAL:
        return PortalStatus.AWAITING_APPROVAL
    if code == ServiceRequestStatus.REJECTED:
        return PortalStatus.REJECTED
    return _BY_CATEGORY[category]


# Always part of the requester's view: what the record is and where it stands.
ALWAYS = frozenset(
    {
        "id",
        "display_id",
        "subject",
        "requester_id",
        "on_behalf_of_id",
        "portal_changes",
        "portal_status",
        "created_at",
        "updated_at",
        "resolution",  # the fix the requester confirms or rejects (REQ-INC-147)
        "resolved_at",
        "closed_at",
        "version",
    }
)
# Fields a template may show to requesters (its `requester_can_see`).
TEMPLATE_CONTROLLED = frozenset(
    {
        TemplateField.DESCRIPTION.value,
        TemplateField.CATEGORY_ID.value,
        TemplateField.SITE_ID.value,
        TemplateField.DEPARTMENT_ID.value,
        TemplateField.IMPACT.value,
        TemplateField.URGENCY.value,
        TemplateField.IMPACT_DETAILS.value,
    }
)
# Never shown to a requester, whatever a template says (REQ-INC-028 AC2, REQ-INC-147 AC2).
STAFF_ONLY = frozenset(
    {
        TemplateField.GROUP_ID.value,
        TemplateField.TECHNICIAN_ID.value,
        TemplateField.LEVEL.value,
        TemplateField.CHANNEL.value,
        TemplateField.TAGS.value,
        "priority",
        "status",
    }
)
# What a requester may fill in when reporting (on behalf of comes with WP-030, REQ-SR-011).
FILLABLE = frozenset(
    {
        TemplateField.SUBJECT.value,
        TemplateField.DESCRIPTION.value,
        TemplateField.CATEGORY_ID.value,
        TemplateField.IMPACT.value,
        TemplateField.URGENCY.value,
        TemplateField.IMPACT_DETAILS.value,
    }
)


def requester_fields(rules: Mapping[str, FieldRule]) -> frozenset[str]:
    """The fields the portal returns for a record made from a template with these rules."""
    shown = {
        name
        for name in TEMPLATE_CONTROLLED
        if (rule := rules.get(name)) is not None and rule.shown and rule.requester_can_see
    }
    return ALWAYS | frozenset(shown)


def requester_fillable(rules: Mapping[str, FieldRule]) -> frozenset[str]:
    """The fields a requester may fill in on the portal form for this template."""
    fill = {
        name
        for name in FILLABLE
        if (rule := rules.get(name)) is not None and rule.shown and rule.requester_can_fill
    }
    return frozenset(fill | {TemplateField.SUBJECT.value})


def unfillable(given: Collection[str], rules: Mapping[str, FieldRule]) -> list[str]:
    """Fields in a portal create the requester may not set (refused, never silently dropped)."""
    allowed = requester_fillable(rules)
    return sorted(name for name in given if name not in allowed)


class PortalReach(StrEnum):
    """How far a person sees in the portal."""

    OWN = "own"  # records they raised or that are for them
    REPORTS = "reports"  # their direct reports' records (own filter, REQ-PRT-007 AC2)
    DEPARTMENT = "department"
    SITE = "site"
    ALL = "all"
    # Named on one of the request's approvals: sees it to decide, read-only (QA10-P2-06).
    APPROVER = "approver"


@dataclass(frozen=True)
class Viewer:
    """The person looking, with what decides their reach."""

    user_id: uuid.UUID
    reach: frozenset[PortalReach] = frozenset({PortalReach.OWN})
    department_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    site_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    report_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RecordFacts:
    """What reach is decided on."""

    requester_id: uuid.UUID | None
    on_behalf_of_id: uuid.UUID | None
    department_id: uuid.UUID | None
    site_id: uuid.UUID | None


def is_own(viewer: Viewer, record: RecordFacts) -> bool:
    """The viewer raised it or it is for them (the only reach that may reply or confirm)."""
    return viewer.user_id in {record.requester_id, record.on_behalf_of_id}


def reaches(viewer: Viewer, record: RecordFacts) -> PortalReach | None:
    """The narrowest reach by which the viewer sees the record, or None."""
    people = {record.requester_id, record.on_behalf_of_id} - {None}
    checks: tuple[tuple[PortalReach, bool], ...] = (
        (PortalReach.OWN, is_own(viewer, record)),
        (PortalReach.REPORTS, bool(people & viewer.report_ids)),
        (
            PortalReach.DEPARTMENT,
            record.department_id is not None and record.department_id in viewer.department_ids,
        ),
        (PortalReach.SITE, record.site_id is not None and record.site_id in viewer.site_ids),
        (PortalReach.ALL, True),
    )
    for reach, ok in checks:
        if ok and reach in viewer.reach:
            return reach
    return None


# What the requester's live channel may name as changed (field names, never values); the due
# time is a name only: the API decides whether the tenant shows it (D5).
LIVE_FIELDS = ALWAYS | TEMPLATE_CONTROLLED | {"resolution_due_at"}
# The stage whose scheduled window a change's requester sees as its planned window (WP-045d S4a).
PLANNED_STAGE = "implementation"


def portal_changes(
    fields: Collection[str],
    *,
    status_before: tuple[str, StatusCategory | None] | None = None,
    status_after: tuple[str, StatusCategory] | None = None,
) -> tuple[str, ...]:
    """The changed fields a requester may hear about; empty means publish nothing.

    A staff-side change (group, technician, priority, a move between two statuses the
    requester sees the same, like in progress -> waiting on a third party) says nothing on
    their channel, so it cannot even tell that staff did something.
    """
    found = {f for f in fields if f in LIVE_FIELDS}
    if status_after is not None:
        after = portal_status(*status_after)
        before = (
            portal_status(status_before[0], status_before[1])
            if status_before is not None and status_before[1] is not None
            else None
        )
        if before != after:
            found.add("portal_status")
    return tuple(sorted(found))


__all__ = [
    "ALWAYS",
    "FILLABLE",
    "LIVE_FIELDS",
    "PLANNED_STAGE",
    "STAFF_ONLY",
    "TEMPLATE_CONTROLLED",
    "PortalReach",
    "PortalStatus",
    "RecordFacts",
    "Viewer",
    "is_own",
    "portal_changes",
    "portal_status",
    "reaches",
    "requester_fields",
    "requester_fillable",
    "unfillable",
]
