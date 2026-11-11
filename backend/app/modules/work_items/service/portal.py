"""The portal's view of incidents for requesters (WP-028; ~/Desktop/wp-028-plan.md).

Everything a requester reads goes through `viewer` and `reach_predicate`: the **one scope
check**. Wider reach than their own records is decided by D-129 (product owner, D2 option a):
two permissions of the work-item engine, not of one type, so service requests use them too.

- own: always (requester, or the person it is for), no permission needed;
- direct reports: `work_items.view_reports`;
- department: `work_items.view_department` (the person's own department);
- site and all: `requests.view` at scope `site` / `all` ("my requests" covers incidents and
  service requests, REQ-PRT-007). `group` scope means nothing to a requester and is ignored.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, Select, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import PermissionSpec
from app.core.errors import FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules import service_catalog
from app.modules.identity_access import (
    Subject,
    direct_reports,
    people_matching,
    person_placement,
    user_contacts,
    user_names,
)
from app.modules.work_items.domain.conversation import Visibility
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.portal import (
    PLANNED_STAGE,
    KnownProblem,
    PortalReach,
    PortalStatus,
    RecordFacts,
    Viewer,
    known_problem,
    portal_status,
    reaches,
    requester_fields,
    unfillable,
)
from app.modules.work_items.domain.templates import rules_from_json
from app.modules.work_items.domain.types import (
    INCIDENT,
    SERVICE_REQUEST,
    TYPES,
    Channel,
    WorkItemType,
    WorkItemTypeCode,
)
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemConversation,
    WorkItemLink,
    WorkItemStageSchedule,
    WorkItemTemplate,
)
from app.modules.work_items.service import approval_stage, catalogue, resolution, templates
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.conversations import RequesterReply, add_requester_reply
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.api.listing import ListQuery, PageResult, paginate
from app.shared.history import Source

VIEW = "requests.view"
VIEW_DEPARTMENT = "work_items.view_department"
VIEW_REPORTS = "work_items.view_reports"

# D-129: engine-level, for every work item type (registered through work_items' ModuleSpec);
# no role holds them by default.
PERMISSIONS: tuple[PermissionSpec, ...] = (
    # D-152: the department viewer role holds it; a department's head too, computed by identity.
    PermissionSpec(VIEW_DEPARTMENT, "incident", defaults=(("department_viewer", "all"),)),
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
    # The problem behind it, in the requester's words only (REQ-PRB-075, WP-044c D15).
    known_problem: KnownProblem | None = None

    def values(self) -> dict[str, Any]:
        """Only the allowed fields (the allow-list, D1), plus the portal status."""
        out: dict[str, Any] = {name: getattr(self.record, name, None) for name in self.fields}
        out["portal_status"] = self.status
        out["reach"] = self.reach
        if self.known_problem is not None:
            out["known_problem"] = self.known_problem
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
    session: AsyncSession,
    seen_by: Viewer,
    records: list[WorkItem],
    *,
    reach: PortalReach | None = None,
) -> list[PortalRecord]:
    rules = await _rules(session, {r.template_id for r in records if r.template_id is not None})
    # The expected resolution time, only if the tenant shows it (REQ-INC-147, D5).
    shown = DUE_TIME if records and await _shows_due_time(session, records[0].type) else frozenset()
    causes = await _known_problems(session, [r.id for r in records])
    out: list[PortalRecord] = []
    for record in records:
        found_reach = reach or reaches(seen_by, _facts(record))
        if found_reach is None:  # the SQL predicate kept it out (or the caller says why)
            continue
        found = rules.get(record.template_id) if record.template_id else None
        out.append(
            PortalRecord(
                record,
                found_reach,
                requester_fields(found if found is not None else rules_from_json(None)) | shown,
                portal_status(record.status, StatusCategory(record.status_category)),
                causes.get(record.id),
            )
        )
    return out


async def _known_problems(
    session: AsyncSession, incident_ids: list[uuid.UUID]
) -> dict[uuid.UUID, KnownProblem]:
    """Each incident's causing problem, as its requester is told (REQ-PRB-075), in one query.

    Read here as system data: the requester never holds a problem right, and is told only this.
    """
    if not incident_ids:
        return {}
    problem = WorkItem.__table__.alias("problem")
    rows = await session.execute(
        select(WorkItemLink.source_id, problem.c.status_category)
        .join(problem, problem.c.id == WorkItemLink.target_id)
        .where(
            WorkItemLink.source_id.in_(incident_ids),
            WorkItemLink.kind == LinkKind.CAUSED_BY.value,
            WorkItemLink.deleted_at.is_(None),
            problem.c.deleted_at.is_(None),
        )
    )
    found: dict[uuid.UUID, KnownProblem] = {}
    for incident_id, category in rows.all():
        said = known_problem(category)
        if said is not None:
            found[incident_id] = said
    return found


DUE_TIME = frozenset({"resolution_due_at"})


async def _shows_due_time(session: AsyncSession, type_code: str) -> bool:
    wtype = TYPES.get(WorkItemTypeCode(type_code))
    return wtype is not None and (await catalogue.load(session, wtype)).portal_show_due_time


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
    if record is None and wtype is SERVICE_REQUEST:
        record = await _as_approver(session, subject, record_id)
    if record is None:
        raise NotFound(code="work_item_not_found")
    shaped = await _shape(session, seen_by, [record])
    if shaped:
        return shaped[0]
    # Only an approver gets here: the request's own fields, what its requester sees, no more.
    return (await _shape(session, seen_by, [record], reach=PortalReach.APPROVER))[0]


async def _as_approver(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID
) -> WorkItem | None:
    """The request when the person is named on one of its approvals (QA10-P2-06), else None."""
    if not await approval_stage.is_named_approver(session, subject.user_id, record_id):
        return None
    return await session.scalar(_base(SERVICE_REQUEST).where(WorkItem.id == record_id))


# --- reporting an issue (REQ-INC-028) ---------------------------------------------------------

CREATE = "requests.create"


async def portal_templates(
    session: AsyncSession, wtype: WorkItemType = INCIDENT
) -> list[WorkItemTemplate]:
    """The templates the portal offers: those marked for requesters and enabled.

    With none marked, the default template, so a new tenant's portal can report an issue out
    of the box (REQ-INC-028 AC1).
    """
    rows = await templates.list_templates(session, wtype)
    offered = [t for t in rows if t.for_requesters and t.disabled_at is None]
    offered = offered or [t for t in rows if t.is_default]
    # WP-031 plan D7 (REQ-CAT-014): the catalog may hide the general incident form, so
    # requesters report through its "report a problem" entries; never down to no form at all.
    if (
        wtype is INCIDENT
        and (await service_catalog.catalog_settings(session)).hide_default_incident_template
    ):
        narrowed = [t for t in offered if not t.is_default]
        offered = narrowed or offered
    return offered


async def create_record(  # noqa: PLR0913 - the form's inputs and the engine's context
    session: AsyncSession,
    subject: Subject,
    values: Mapping[str, Any],
    *,
    template_id: uuid.UUID | None,
    source: Source,
    holders: items.PermissionHolders,
    wtype: WorkItemType = INCIDENT,
) -> PortalRecord:
    """A new incident from the portal, in the signed-in person's name, channel `portal`.

    Only the template's requester-fillable fields are taken; any other field is refused, not
    dropped (a staff field like `group_id` never comes from a requester, REQ-INC-028 AC2).
    """
    if not subject.holds(CREATE):
        raise PermissionDenied(params={"permission": CREATE, "reason": "no_permission"})
    offered = {t.id: t for t in await portal_templates(session, wtype)}
    chosen = offered.get(template_id) if template_id else next(iter(offered.values()), None)
    if chosen is None:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.template_id",
                    code="template_not_found",
                    message_key="errors.field.template_not_found",
                )
            ]
        )
    # Not a form field: the engine checks it against the tenant's scope (REQ-SR-011, 403).
    fields = {k: v for k, v in values.items() if k != "on_behalf_of_id"}
    refused = unfillable(fields.keys(), rules_from_json(chosen.field_rules))
    if refused:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field=f"body.{name}", code="read_only", message_key="errors.field.read_only"
                )
                for name in refused
            ]
        )
    made = await items.create(
        session,
        subject,
        wtype,
        {**values, "requester_id": subject.user_id, "template_id": chosen.id},
        source=source,
        holders=holders,
        channel=Channel.PORTAL,
    )
    return await get_record(session, subject, made.record.id, wtype)


ON_BEHALF_LIMIT = 20


async def on_behalf_people(
    session: AsyncSession, subject: Subject, text: str, wtype: WorkItemType = INCIDENT
) -> list[tuple[uuid.UUID, str]]:
    """(id, name) of people matching `text` the subject may report for, best match first."""
    candidates = await people_matching(session, text.strip(), limit=ON_BEHALF_LIMIT * 5)
    allowed = (await items.may_raise_for_people(session, subject, wtype, candidates))[
        :ON_BEHALF_LIMIT
    ]
    names = await user_names(session, [str(p) for p in allowed])
    return [(p, names[str(p)]) for p in allowed if str(p) in names]


# --- the public conversation (REQ-INC-147) ----------------------------------------------------

CONVERSATION_MAX = 200


@dataclass(frozen=True)
class PublicEntry:
    """A public reply or note as the requester's side sees it: no recipients, no delivery."""

    id: uuid.UUID
    kind: str
    body: str
    created_at: datetime
    author_name: str | None
    by_you: bool


async def conversation(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID, wtype: WorkItemType = INCIDENT
) -> list[PublicEntry]:
    """Public entries only, oldest first (the newest CONVERSATION_MAX); private notes never."""
    found = await get_record(session, subject, record_id, wtype)
    if found.reach is PortalReach.APPROVER:
        return []  # an approver sees what is asked, not the requester's talk with the desk
    rows = list(
        await session.scalars(
            select(WorkItemConversation)
            .where(
                WorkItemConversation.work_item_id == found.record.id,
                WorkItemConversation.visibility == Visibility.PUBLIC,
                WorkItemConversation.deleted_at.is_(None),
            )
            .order_by(WorkItemConversation.created_at.desc(), WorkItemConversation.id.desc())
            .limit(CONVERSATION_MAX)
        )
    )
    rows.reverse()
    authors = sorted({str(e.created_by) for e in rows if e.created_by is not None})
    names = await user_contacts(session, authors)  # names only leave here, never addresses
    return [
        PublicEntry(
            e.id,
            e.kind,
            e.body,
            e.created_at,
            names[str(e.created_by)][0] if str(e.created_by) in names else None,
            e.created_by == subject.user_id,
        )
        for e in rows
    ]


async def reply(  # noqa: PLR0913 - the reply and the engine's context
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    body: str,
    source: Source,
    holders: items.PermissionHolders,
    wtype: WorkItemType = INCIDENT,
) -> RequesterReply:
    """The requester's public reply; only their own records (a manager reads, never replies)."""
    found = await get_record(session, subject, record_id, wtype)
    if found.reach is not PortalReach.OWN:
        raise PermissionDenied(params={"permission": CREATE, "reason": "no_permission"})
    return await add_requester_reply(
        session,
        wtype,
        found.record,
        body=body,
        source=source,
        automatic=False,
        subject=subject,
        holders=holders,
    )


async def answer_resolution(  # noqa: PLR0913 - the answer and its context
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    confirmed: bool,
    comment: str | None,
    source: Source,
    wtype: WorkItemType = INCIDENT,
) -> PortalRecord:
    """Confirm or reject the fix (WP-020f) on your own record; the portal's view comes back."""
    found = await get_record(session, subject, record_id, wtype)
    if found.reach is not PortalReach.OWN:
        raise PermissionDenied(params={"permission": CREATE, "reason": "no_permission"})
    if confirmed:
        await resolution.confirm(session, subject, wtype, record_id, source=source)
    else:
        await resolution.reject(
            session, subject, wtype, record_id, comment=comment or "", source=source
        )
    return await get_record(session, subject, record_id, wtype)


__all__ = [
    "CONVERSATION_MAX",
    "CREATE",
    "FIELDS",
    "PERMISSIONS",
    "VIEW",
    "VIEW_DEPARTMENT",
    "VIEW_REPORTS",
    "PortalRecord",
    "PortalState",
    "PublicEntry",
    "answer_resolution",
    "conversation",
    "create_record",
    "get_record",
    "list_records",
    "portal_templates",
    "reach_predicate",
    "reply",
    "viewer",
]


async def planned_window(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID, wtype: WorkItemType
) -> tuple[datetime | None, datetime | None]:
    """A staged record's planned window as its requester may see it (WP-045d S4a, REQ-CHG-109).

    The planned stage's scheduled start and end only (a change's implementation), after the
    same reach check as the record; never the plans, the outcome or anyone's notes.
    """
    await get_record(session, subject, record_id, wtype)  # 404 out of reach
    row = await session.scalar(
        select(WorkItemStageSchedule).where(
            WorkItemStageSchedule.work_item_id == record_id,
            WorkItemStageSchedule.stage == PLANNED_STAGE,
        )
    )
    return (row.scheduled_start, row.scheduled_end) if row is not None else (None, None)
