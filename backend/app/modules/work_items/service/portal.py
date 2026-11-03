"""The portal's view of incidents for requesters (WP-028; ~/Desktop/wp-028-plan.md).

Everything a requester reads goes through `viewer` and `reach_predicate`: the **one scope
check** of D2. Wider reach than their own records is pending the product owner (permissions
here, or scopes in identity's policy); moving it later touches only `viewer`.

Today's default:

- own: always (requester, or the person it is for), no permission needed;
- direct reports: `requests.view_reports`;
- department: `requests.view_department` (the person's own department);
- site and all: `requests.view` at scope `site` / `all` ("my requests" covers incidents and
  service requests, REQ-PRT-007). `group` scope means nothing to a requester and is ignored.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, Select, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import PermissionSpec
from app.core.errors import NotFound
from app.modules.identity_access import Subject, direct_reports, person_placement
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.portal import (
    PortalReach,
    PortalStatus,
    RecordFacts,
    Viewer,
    portal_status,
    reaches,
    requester_fields,
)
from app.modules.work_items.domain.templates import rules_from_json
from app.modules.work_items.domain.types import INCIDENT, WorkItemType
from app.modules.work_items.infra.models import WorkItem, WorkItemTemplate
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.api.listing import ListQuery, PageResult, paginate

VIEW = "requests.view"
VIEW_DEPARTMENT = "requests.view_department"
VIEW_REPORTS = "requests.view_reports"

# work_items' share of D2 (registered through its ModuleSpec; no role holds them by default).
PERMISSIONS: tuple[PermissionSpec, ...] = (
    PermissionSpec(VIEW_DEPARTMENT, "incident"),
    PermissionSpec(VIEW_REPORTS, "incident"),
)


def _scopes(subject: Subject, permission: str) -> set[str]:
    return {grant.scope for grant in subject.grants.get(permission, ())}


async def viewer(session: AsyncSession, subject: Subject) -> Viewer:
    """The signed-in person's portal reach (the one place D2 is decided)."""
    reach = {PortalReach.OWN}
    departments: frozenset[uuid.UUID] = frozenset()
    sites: frozenset[uuid.UUID] = frozenset()
    reports: frozenset[uuid.UUID] = frozenset()
    view = _scopes(subject, VIEW)
    if "all" in view:
        reach.add(PortalReach.ALL)
    placement = await person_placement(session, subject.user_id)
    # The person's own site (as a requester), not the sites of their support groups.
    if "site" in view and placement.site_id is not None:
        reach.add(PortalReach.SITE)
        sites = frozenset({placement.site_id})
    if subject.holds(VIEW_DEPARTMENT) and placement.department_id is not None:
        reach.add(PortalReach.DEPARTMENT)
        departments = frozenset({placement.department_id})
    if subject.holds(VIEW_REPORTS):
        found = await direct_reports(session, subject.user_id)
        if found:
            reach.add(PortalReach.REPORTS)
            reports = frozenset(found)
    return Viewer(subject.user_id, frozenset(reach), departments, sites, reports)


def _people(ids: frozenset[uuid.UUID]) -> ColumnElement[bool]:
    return or_(WorkItem.requester_id.in_(ids), WorkItem.on_behalf_of_id.in_(ids))


def reach_predicate(viewer: Viewer, only: PortalReach | None = None) -> ColumnElement[bool]:
    """SQL for the records the viewer sees: all of their reach, or `only` one (a filter).

    The same rules as `domain.portal.reaches`, which the tests hold this to.
    """
    wanted = viewer.reach if only is None else viewer.reach & {only}
    if PortalReach.ALL in wanted:
        return WorkItem.id.is_not(None)
    parts: list[ColumnElement[bool]] = []
    if PortalReach.OWN in wanted:
        parts.append(_people(frozenset({viewer.user_id})))
    if PortalReach.REPORTS in wanted and viewer.report_ids:
        parts.append(_people(viewer.report_ids))
    if PortalReach.DEPARTMENT in wanted and viewer.department_ids:
        parts.append(WorkItem.department_id.in_(viewer.department_ids))
    if PortalReach.SITE in wanted and viewer.site_ids:
        parts.append(WorkItem.site_id.in_(viewer.site_ids))
    return or_(*parts) if parts else false()


# --- reading --------------------------------------------------------------------------------------

# What a requester may filter and sort by: nothing that would let a filter probe staff fields
# (a `group_id=` filter would reveal the group by which rows come back).
FIELDS = ResourceFields(
    name="portal_incidents",
    fields={
        "created_at": FilterField(
            WorkItem.created_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "updated_at": FilterField(
            WorkItem.updated_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "display_number": FilterField(
            WorkItem.display_number, FieldType.INTEGER, sortable=True, simple=False
        ),
    },
    id_column=WorkItem.id,
    default_sort=("-updated_at",),
)
OPEN_CATEGORIES = frozenset(
    {StatusCategory.OPEN, StatusCategory.PAUSED, StatusCategory.RESOLVED}  # resolved: confirm it
)
SEARCH_MAX = 200


class PortalState(StrEnum):
    """The open / closed filter of "My requests" (REQ-PRT-007)."""

    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True)
class PortalRecord:
    """One incident as its requester's side sees it."""

    record: WorkItem
    reach: PortalReach
    fields: frozenset[str]
    status: PortalStatus

    def values(self) -> dict[str, Any]:
        """Only the allowed fields (the allow-list, D1), plus the portal status."""
        out: dict[str, Any] = {name: getattr(self.record, name, None) for name in self.fields}
        out["portal_status"] = self.status
        out["reach"] = self.reach
        return out


def _base(wtype: WorkItemType) -> Select[WorkItem]:
    return select(WorkItem).where(WorkItem.type == wtype.code, WorkItem.deleted_at.is_(None))


async def _rules(session: AsyncSession, template_ids: set[uuid.UUID]) -> dict[uuid.UUID, Any]:
    if not template_ids:
        return {}
    rows = await session.execute(
        select(WorkItemTemplate.id, WorkItemTemplate.field_rules).where(
            WorkItemTemplate.id.in_(template_ids)
        )
    )
    return {row.id: rules_from_json(row.field_rules) for row in rows}


def _facts(record: WorkItem) -> RecordFacts:
    return RecordFacts(
        record.requester_id, record.on_behalf_of_id, record.department_id, record.site_id
    )


async def _shape(
    session: AsyncSession, seen_by: Viewer, records: list[WorkItem]
) -> list[PortalRecord]:
    rules = await _rules(session, {r.template_id for r in records if r.template_id is not None})
    out: list[PortalRecord] = []
    for record in records:
        reach = reaches(seen_by, _facts(record))
        if reach is None:  # pragma: no cover - the SQL predicate already kept it out
            continue
        found = rules.get(record.template_id) if record.template_id else None
        out.append(
            PortalRecord(
                record,
                reach,
                requester_fields(found if found is not None else rules_from_json(None)),
                portal_status(record.status, StatusCategory(record.status_category)),
            )
        )
    return out


def _search(text: str) -> ColumnElement[bool]:
    term = text.strip()[:SEARCH_MAX]
    like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return or_(
        WorkItem.subject.ilike(like, escape="\\"),
        func.lower(WorkItem.display_id) == term.lower(),
    )


async def list_records(  # noqa: PLR0913 - the list's own filters
    session: AsyncSession,
    subject: Subject,
    query: ListQuery,
    *,
    wtype: WorkItemType = INCIDENT,
    only: PortalReach | None = None,
    state: PortalState | None = None,
    search: str | None = None,
) -> tuple[list[PortalRecord], PageResult[Any]]:
    """One page of "My requests" (REQ-PRT-007): the viewer's reach, or one reach as a filter."""
    seen_by = await viewer(session, subject)
    statement = _base(wtype).where(reach_predicate(seen_by, only))
    if state is PortalState.OPEN:
        statement = statement.where(WorkItem.status_category.in_(OPEN_CATEGORIES))
    elif state is PortalState.CLOSED:
        statement = statement.where(WorkItem.status_category.not_in(OPEN_CATEGORIES))
    if search and search.strip():
        statement = statement.where(_search(search))
    page = await paginate(session, statement, query)
    return await _shape(session, seen_by, page.rows), page


async def get_record(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID, wtype: WorkItemType = INCIDENT
) -> PortalRecord:
    """One record in the viewer's reach; out of reach is 404, never 403 (no existence leak)."""
    seen_by = await viewer(session, subject)
    record = await session.scalar(
        _base(wtype).where(WorkItem.id == record_id, reach_predicate(seen_by))
    )
    if record is None:
        raise NotFound(code="work_item_not_found")
    return (await _shape(session, seen_by, [record]))[0]


__all__ = [
    "FIELDS",
    "PERMISSIONS",
    "VIEW",
    "VIEW_DEPARTMENT",
    "VIEW_REPORTS",
    "PortalRecord",
    "PortalState",
    "get_record",
    "list_records",
    "reach_predicate",
    "viewer",
]
