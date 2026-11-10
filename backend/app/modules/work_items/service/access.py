"""Who may see and change which work items (WP-020; ADR-022 policy layer; D-052).

The scopes of every `<type>.<action>` permission mean, for work items:

* `all`   every record of the type;
* `site`  records whose site is one of the user's sites;
* `group` records of the user's support groups, **plus the unassigned queue of the user's sites**
          (no group and no technician yet, D-052): the built-in technician holds `group`, so a
          new ticket nobody has picked up is visible to the technicians of its site;
* `own`   records the user requested, is the on-behalf-of person of, or is assigned to. Creating
          a record does not make it yours: a technician who logs a call and hands it to another
          group stops seeing it (after a warning, D-053).

Followers who kept access after handing a record over (D-068, `work_item_followers.grants_access`)
reach that one record for `view` and `add_note` only, whatever their scope (`shared_scope`): they
can read it, see it live and add private notes, never edit, assign or change its status.

The built-in technician role holds view and the working permissions at `group` and `own`
(D-052); admins widen them to `all` per role. Lists, single records, realtime channels and
(later) search and AI use these same predicates (architecture.md §11.2).
"""

import uuid

from sqlalchemy import ColumnElement, and_, false, or_, select

from app.core.authorization import ALL_SCOPES, PermissionSpec, Scope
from app.modules.identity_access import (
    PROBLEM_MANAGER,
    RELEASE_MANAGER,
    REPORT_VIEWER,
    SERVICE_DESK_MANAGER,
    SITE_ADMIN,
    ResourceType,
    Subject,
)
from app.modules.work_items.domain.classification import Impact, Priority, PrioritySource, Urgency
from app.modules.work_items.domain.lifecycle import DefaultStatus, StatusCategory
from app.modules.work_items.domain.service_requests import ApprovalStatus
from app.modules.work_items.domain.types import Channel, WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem, WorkItemFollower, WorkItemRoleHolder
from app.shared.api.filters import FieldType, FilterField, ResourceFields

NOT_OWN: tuple[Scope, ...] = ("all", "site", "group")


def _in_sites(site_ids: frozenset[uuid.UUID]) -> ColumnElement[bool]:
    return WorkItem.site_id.in_(site_ids)


def _in_groups(group_ids: frozenset[uuid.UUID]) -> ColumnElement[bool]:
    return WorkItem.group_id.in_(group_ids)


def unassigned_in_sites(site_ids: frozenset[uuid.UUID]) -> ColumnElement[bool]:
    """Records nobody has picked up yet (no group, no technician) at one of `site_ids`."""
    return and_(
        WorkItem.group_id.is_(None),
        WorkItem.technician_id.is_(None),
        WorkItem.site_id.in_(site_ids),
    )


def _site_queue(subject: Subject) -> ColumnElement[bool] | None:
    return unassigned_in_sites(subject.site_ids) if subject.site_ids else None


def followed_with_access(subject: Subject) -> ColumnElement[bool]:
    """Records the subject follows with access (D-068): kept after handing them over."""
    return WorkItem.id.in_(
        select(WorkItemFollower.work_item_id).where(
            WorkItemFollower.user_id == subject.user_id,
            WorkItemFollower.grants_access.is_(True),
            WorkItemFollower.deleted_at.is_(None),
        )
    )


def role_holder_of(subject: Subject) -> ColumnElement[bool]:
    """Records where the subject holds a named role, in person or through a group (WP-058a s4).

    The `own` scope's extra records (lane B's review): a holder reaches the record with whatever
    an own-scope grant of theirs allows, in lists, on the record, live and in search alike.
    """
    held = select(WorkItemRoleHolder.work_item_id).where(
        or_(
            WorkItemRoleHolder.user_id == subject.user_id,
            WorkItemRoleHolder.group_id.in_(subject.group_ids) if subject.group_ids else false(),
        )
    )
    return WorkItem.id.in_(held)


# What a follower with access may do on that record (REQ-INC-151 AC2).
SHARED_ACTIONS = frozenset({"view", "add_note"})


# A target's state as lists show it (sla's SlaStamp; labels `sla_target_state.*`).
SLA_STATES = ("running", "warning", "paused", "met", "breached", "stopped")


def _enum(column: object, values: object) -> FilterField:
    return FilterField(column, FieldType.ENUM, values=frozenset(str(v) for v in values))  # type: ignore[attr-defined]  # StrEnum classes iterate


FIELDS = ResourceFields(
    name="work_items",
    fields={
        "id": FilterField(WorkItem.id, FieldType.UUID),
        "display_id": FilterField(WorkItem.display_id, FieldType.STRING, sortable=True),
        "display_number": FilterField(WorkItem.display_number, FieldType.INTEGER, sortable=True),
        "subject": FilterField(WorkItem.subject, FieldType.STRING, sortable=True),
        "status": _enum(WorkItem.status, DefaultStatus),
        "status_category": _enum(WorkItem.status_category, StatusCategory),
        "priority": FilterField(
            WorkItem.priority,
            FieldType.ENUM,
            values=frozenset(Priority),
            sortable=True,
        ),
        "priority_source": _enum(WorkItem.priority_source, PrioritySource),
        "impact": _enum(WorkItem.impact, Impact),
        "urgency": _enum(WorkItem.urgency, Urgency),
        "channel": _enum(WorkItem.channel, Channel),
        "requester_id": FilterField(WorkItem.requester_id, FieldType.UUID),
        "on_behalf_of_id": FilterField(WorkItem.on_behalf_of_id, FieldType.UUID),
        "technician_id": FilterField(WorkItem.technician_id, FieldType.UUID),
        "group_id": FilterField(WorkItem.group_id, FieldType.UUID),
        "site_id": FilterField(WorkItem.site_id, FieldType.UUID),
        "category_id": FilterField(WorkItem.category_id, FieldType.UUID),
        "level": FilterField(WorkItem.level, FieldType.STRING, sortable=True),
        # REQ-INC-093: lists and reports group and filter by the closure code.
        "closure_code": FilterField(WorkItem.closure_code, FieldType.STRING, sortable=True),
        "template_id": FilterField(WorkItem.template_id, FieldType.UUID),
        # Service requests (WP-030, REQ-SR-009): by item and by approval status.
        "catalog_item_id": FilterField(WorkItem.catalog_item_id, FieldType.UUID),
        "approval_status": _enum(WorkItem.approval_status, ApprovalStatus),
        "sla_policy_id": FilterField(WorkItem.sla_policy_id, FieldType.UUID),
        "created_by": FilterField(WorkItem.created_by, FieldType.UUID),
        "updated_by": FilterField(WorkItem.updated_by, FieldType.UUID),
        "reopen_count": FilterField(WorkItem.reopen_count, FieldType.INTEGER, sortable=True),
        "reassignment_count": FilterField(WorkItem.reassignment_count, FieldType.INTEGER),
        "created_at": FilterField(
            WorkItem.created_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "updated_at": FilterField(
            WorkItem.updated_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "status_changed_at": FilterField(
            WorkItem.status_changed_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "first_assigned_at": FilterField(
            WorkItem.first_assigned_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "resolved_at": FilterField(
            WorkItem.resolved_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "closed_at": FilterField(
            WorkItem.closed_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        # Haider, 2026-11-10: "restored from trash" (the latest restore), for SLA reports.
        "restored_at": FilterField(
            WorkItem.restored_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "resolution_due_at": FilterField(
            WorkItem.resolution_due_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "first_response_due_at": FilterField(
            WorkItem.first_response_due_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        # Each target's SLA state and breached flag (WP-025 session 3): list columns, filters
        # and the "about to breach" and "breached" views (REQ-SLA-019 AC2, REQ-SLA-020 AC4).
        "first_response_sla_state": _enum(WorkItem.first_response_sla_state, SLA_STATES),
        "resolution_sla_state": _enum(WorkItem.resolution_sla_state, SLA_STATES),
        "first_response_breached": FilterField(WorkItem.first_response_breached, FieldType.BOOLEAN),
        "resolution_breached": FilterField(WorkItem.resolution_breached, FieldType.BOOLEAN),
        # Reporting needs these too (WP-035, D-100 D9); they filter the list just the same.
        "first_responded_at": FilterField(
            WorkItem.first_responded_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "paused_seconds": FilterField(WorkItem.paused_seconds, FieldType.INTEGER),
        "department_id": FilterField(WorkItem.department_id, FieldType.UUID),
        "desk_id": FilterField(WorkItem.desk_id, FieldType.UUID),
    },
    id_column=WorkItem.id,
    default_sort=("-updated_at",),
)

RESOURCE = ResourceType(
    name="work_items",
    fields=FIELDS,
    owner_columns=(
        WorkItem.requester_id,
        WorkItem.on_behalf_of_id,
        WorkItem.technician_id,
    ),
    site_scope=_in_sites,
    group_scope=_in_groups,
    group_scope_extra=_site_queue,
    owner_extra=role_holder_of,
    shared_scope=followed_with_access,
    shared_actions=SHARED_ACTIONS,
)

# action -> (scopes it may be granted at, built-in technician scopes). D-052: group + own.
_TECH: tuple[tuple[str, Scope], ...] = (("technician", "group"), ("technician", "own"))
_ACTIONS: tuple[tuple[str, tuple[Scope, ...], tuple[tuple[str, Scope], ...]], ...] = (
    ("view", ALL_SCOPES, _TECH),
    ("create", ("all",), (("technician", "all"),)),
    ("edit", ALL_SCOPES, _TECH),
    ("assign", ALL_SCOPES, _TECH),
    ("take", NOT_OWN, (("technician", "group"),)),
    ("change_priority", ALL_SCOPES, _TECH),
    ("resolve", ALL_SCOPES, _TECH),
    ("close", ALL_SCOPES, _TECH),
    ("reopen", ALL_SCOPES, _TECH),
    ("cancel", ALL_SCOPES, _TECH),
    ("delete", ("all",), ()),
    # WP-020b: private notes; public replies and notes (and making a note public); followers.
    ("add_note", ALL_SCOPES, _TECH),
    ("reply", ALL_SCOPES, _TECH),
    ("manage_followers", ALL_SCOPES, _TECH),
    # WP-025: due dates set by hand (D-115 D11): not for technicians by default (least
    # privilege). Admins hold every permission; a group lead gets it through a role.
    ("edit_due_dates", ALL_SCOPES, ()),
)


# WP-042 built-in roles (agreed with lanes A and B): the service desk manager everywhere, a site
# admin works their site's records (no create, delete or due dates), a report viewer reads.
_SITE_WORK = frozenset(
    {
        "view",
        "edit",
        "assign",
        "take",
        "change_priority",
        "resolve",
        "close",
        "reopen",
        "cancel",
        "add_note",
        "reply",
        "manage_followers",
    }
)


def _role_defaults(action: str) -> tuple[tuple[str, Scope], ...]:
    found: list[tuple[str, Scope]] = [(SERVICE_DESK_MANAGER, "all")]
    if action in _SITE_WORK:
        found.append((SITE_ADMIN, "site"))
    if action == "view":
        found.append((REPORT_VIEWER, "all"))
    return tuple(found)


# Service requests (WP-030): these five keys keep the system-role grants identity has always
# given them (SYSTEM_ROLE_GRANTS: technicians all, requesters view and close own, create all);
# the type declares no defaults of its own for them, so nothing is added or widened.
IDENTITY_GRANTED = frozenset({"view", "create", "edit", "assign", "close"})


# Problems (WP-044a, agreed with lane B): what identity's reserved `problems.view` (all) and
# `problems.manage` (group) gave technicians, in the engine's actions: they see every problem,
# create them, and work their groups' problems. Never delete (admins), never due dates by hand.
_PROBLEM_TECH: dict[str, tuple[tuple[str, Scope], ...]] = {
    "view": (("technician", "all"),),
    "create": (("technician", "all"),),
    "delete": (),
    "edit_due_dates": (),
}
_PROBLEM_GROUP: tuple[tuple[str, Scope], ...] = (("technician", "group"),)


def _type_defaults(
    wtype: WorkItemType, action: str, defaults: tuple[tuple[str, Scope], ...]
) -> tuple[tuple[str, Scope], ...]:
    if wtype.code is WorkItemTypeCode.SERVICE_REQUEST:
        # Service requests keep identity's system-role grants for these keys (WP-030, nothing
        # widened for technicians or requesters).
        return () if action in IDENTITY_GRANTED else defaults
    if wtype.code is WorkItemTypeCode.PROBLEM:
        # The problem manager (WP-044c D14, Appendix A) holds every problem permission.
        return (*_PROBLEM_TECH.get(action, _PROBLEM_GROUP), (PROBLEM_MANAGER, "all"))
    if wtype.code is WorkItemTypeCode.INCIDENT and action == "view":
        # ... and reads the incidents problems are about (linking, evidence, impact).
        return (*defaults, (PROBLEM_MANAGER, "all"))
    if wtype.code is WorkItemTypeCode.RELEASE:
        # Releases (WP-058a): technicians keep only identity's releases.view grant; the type
        # adds no technician defaults, so nothing is widened (lane B review). The release
        # manager (D-153) holds every release permission at "all" but delete: the trash stays
        # with the service desk manager and admins, as for the other types (lane B's review).
        return () if action == "delete" else ((RELEASE_MANAGER, "all"),)
    if wtype.code is WorkItemTypeCode.CHANGE:
        # Changes (WP-045a): technicians keep identity's changes.view and changes.create (all);
        # the engine adds working their groups' changes, never delete or due dates by hand.
        kept = {"view", "create", "delete", "edit_due_dates"}
        return () if action in kept else (("technician", "group"),)
    return defaults


def permissions(wtype: WorkItemType) -> tuple[PermissionSpec, ...]:
    """The permission catalogue entries of one type."""
    is_sr = wtype.code is WorkItemTypeCode.SERVICE_REQUEST
    is_release = wtype.code is WorkItemTypeCode.RELEASE
    return (
        tuple(
            PermissionSpec(
                wtype.permission(action),
                wtype.feature,
                # requests.assign keeps the scopes it always had (never "own": lane B, #182)
                NOT_OWN if is_sr and action == "assign" else scopes,
                # The type's own system-role defaults (service requests keep identity's grants,
                # problems their technician grants, releases none); the WP-042 built-in roles
                # still get theirs.
                defaults=(*_type_defaults(wtype, action, defaults), *_role_defaults(action)),
            )
            for action, scopes, defaults in _ACTIONS
        )
        + (APPROVE_SPECS if is_sr else ())
        + (PROBLEM_SPECS if wtype.code is WorkItemTypeCode.PROBLEM else ())
        + (RELEASE_APPROVE_SPECS if is_release else ())
        + (CHANGE_APPROVE_SPECS if wtype.code is WorkItemTypeCode.CHANGE else ())
    )


# Problems only (WP-044b, REQ-PRB-070, D-140 Q7): changing the analysis, and seeing the root
# cause, which may describe a security weakness. Technicians hold both for their groups'
# problems (they work them); everyone else who sees a problem reads it without its root cause
# unless an admin widens it. Enforced in the API, history and search, not only the screen.
EDIT_ANALYSIS = "edit_analysis"
VIEW_ROOT_CAUSE = "view_root_cause"
# WP-044b s3 (REQ-PRB-034, -036): the solution (workaround) and the known error flag.
EDIT_SOLUTION = "edit_solution"
MARK_KNOWN_ERROR = "mark_known_error"
PROBLEM_SPECS: tuple[PermissionSpec, ...] = (
    *(
        PermissionSpec(
            f"problems.{action}",
            "problem",
            ALL_SCOPES,
            defaults=(("technician", "group"), (PROBLEM_MANAGER, "all"), *_role_defaults(action)),
        )
        for action in (EDIT_ANALYSIS, VIEW_ROOT_CAUSE, EDIT_SOLUTION, MARK_KNOWN_ERROR)
    ),
    # Deciding a problem's approvals when named (s4): technicians and the service desk
    # managers, as the problem manager role does in Appendix A.
    PermissionSpec(
        "problems.approve",
        "problem",
        ("all",),
        defaults=(
            ("technician", "all"),
            (SERVICE_DESK_MANAGER, "all"),
            (PROBLEM_MANAGER, "all"),
        ),
    ),
)


# The approval engine (WP-030 s2, REQ-SR-063): anyone holding the type's approve permission may
# be named an approver, requester or technician (REQ-SR-022 AC2), so both system roles hold it.
# Approval administrators (REQ-SR-023) decide approvals that resolved to no active person; only
# the tenant admin holds that by default (least privilege).
APPROVE = "approve"
# Releases (WP-058a s5; lane B's review): a release sign-off is a change-control duty, so only the
# admin roles hold it by default; an approver without it is routed to approve_any, never stuck.
# The release manager signs off too (D-153); the stage approvals' segregation still keeps anyone
# from approving a stage of a release they requested or own.
RELEASE_APPROVE_SPECS: tuple[PermissionSpec, ...] = (
    PermissionSpec(
        "releases.approve",
        "release",
        ("all",),
        defaults=(*_role_defaults("approve"), (RELEASE_MANAGER, "all")),
    ),
)
# changes.approve keeps identity's scopes (not own) and grants (WP-045a).
CHANGE_APPROVE_SPECS: tuple[PermissionSpec, ...] = (
    PermissionSpec(
        "changes.approve", "change", ("all", "site", "group"), defaults=_role_defaults("approve")
    ),
    # D-144: keep a change going without its approval, with a reason, audited, and a mandatory
    # review. Nobody holds it by default but administrators; the change manager role (D-153)
    # gets it when lane B's role model lands.
    PermissionSpec("changes.emergency_override", "change", ("all", "site", "group")),
    # Haider (2026-11-10): change boards are run by the change manager and administrators only,
    # not by every service desk configurer. Administrators hold it; the change manager role
    # (D-153) gets it with the role model.
    PermissionSpec("changes.manage_boards", "change", ("all",)),
)
APPROVE_ANY = "work_items.approve_any"
APPROVE_SPECS: tuple[PermissionSpec, ...] = (
    PermissionSpec(
        "requests.approve",
        "service_request",
        ("all",),
        defaults=(("technician", "all"), ("requester", "all")),
    ),
    PermissionSpec(APPROVE_ANY, "service_request", ("all",)),
)
