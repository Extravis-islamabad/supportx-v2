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

from sqlalchemy import ColumnElement, false, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import PermissionSpec
from app.modules.identity_access import Subject, direct_reports, person_placement
from app.modules.work_items.domain.portal import Reach, Viewer
from app.modules.work_items.infra.models import WorkItem

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
    reach = {Reach.OWN}
    departments: frozenset[uuid.UUID] = frozenset()
    sites: frozenset[uuid.UUID] = frozenset()
    reports: frozenset[uuid.UUID] = frozenset()
    view = _scopes(subject, VIEW)
    if "all" in view:
        reach.add(Reach.ALL)
    placement = await person_placement(session, subject.user_id)
    # The person's own site (as a requester), not the sites of their support groups.
    if "site" in view and placement.site_id is not None:
        reach.add(Reach.SITE)
        sites = frozenset({placement.site_id})
    if subject.holds(VIEW_DEPARTMENT) and placement.department_id is not None:
        reach.add(Reach.DEPARTMENT)
        departments = frozenset({placement.department_id})
    if subject.holds(VIEW_REPORTS):
        found = await direct_reports(session, subject.user_id)
        if found:
            reach.add(Reach.REPORTS)
            reports = frozenset(found)
    return Viewer(subject.user_id, frozenset(reach), departments, sites, reports)


def _people(ids: frozenset[uuid.UUID]) -> ColumnElement[bool]:
    return or_(WorkItem.requester_id.in_(ids), WorkItem.on_behalf_of_id.in_(ids))


def reach_predicate(viewer: Viewer, only: Reach | None = None) -> ColumnElement[bool]:
    """SQL for the records the viewer sees: all of their reach, or `only` one (a filter).

    The same rules as `domain.portal.reaches`, which the tests hold this to.
    """
    wanted = viewer.reach if only is None else viewer.reach & {only}
    if Reach.ALL in wanted:
        return WorkItem.id.is_not(None)
    parts: list[ColumnElement[bool]] = []
    if Reach.OWN in wanted:
        parts.append(_people(frozenset({viewer.user_id})))
    if Reach.REPORTS in wanted and viewer.report_ids:
        parts.append(_people(viewer.report_ids))
    if Reach.DEPARTMENT in wanted and viewer.department_ids:
        parts.append(WorkItem.department_id.in_(viewer.department_ids))
    if Reach.SITE in wanted and viewer.site_ids:
        parts.append(WorkItem.site_id.in_(viewer.site_ids))
    return or_(*parts) if parts else false()


__all__ = [
    "PERMISSIONS",
    "VIEW",
    "VIEW_DEPARTMENT",
    "VIEW_REPORTS",
    "reach_predicate",
    "viewer",
]
