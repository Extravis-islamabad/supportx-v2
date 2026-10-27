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

from sqlalchemy import ColumnElement, and_, select

from app.core.authorization import ALL_SCOPES, PermissionSpec, Scope
from app.modules.identity_access import ResourceType, Subject
from app.modules.work_items.domain.classification import Impact, Priority, PrioritySource, Urgency
from app.modules.work_items.domain.lifecycle import DefaultStatus, StatusCategory
from app.modules.work_items.domain.types import Channel, WorkItemType
from app.modules.work_items.infra.models import WorkItem, WorkItemFollower
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


# What a follower with access may do on that record (REQ-INC-151 AC2).
SHARED_ACTIONS = frozenset({"view", "add_note"})


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
        "template_id": FilterField(WorkItem.template_id, FieldType.UUID),
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
        "resolution_due_at": FilterField(
            WorkItem.resolution_due_at, FieldType.DATETIME, sortable=True, simple=False
        ),
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
    ("assign_outside_group", ("all",), ()),
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
)


def permissions(wtype: WorkItemType) -> tuple[PermissionSpec, ...]:
    """The permission catalogue entries of one type."""
    return tuple(
        PermissionSpec(wtype.permission(action), wtype.feature, scopes, defaults=defaults)
        for action, scopes, defaults in _ACTIONS
    )
