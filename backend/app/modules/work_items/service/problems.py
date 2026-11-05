"""Problems from incidents (WP-044a s3; REQ-PRB-011, -012, -014).

- `prefill`: a new problem's form from an incident (subject, description, impact, urgency, site,
  and the category of the same seeded code), never saved by itself (AC1: the technician sees
  and changes it first).
- `link_cause`: an incident is caused by at most one problem (Q2, recommended). Linking it to a
  second one is refused with the current one named, unless the technician confirms the move
  (REQ-PRB-012 AC2); the move removes the old link with history on all three records.
- Creating one problem from many incidents links them through a bulk job (≤ 1,000, background,
  progress streamed), each link through `link_cause` (see service/bulk.py).
- `similar`: open problems the person may see whose subject or text is close to a draft, for the
  create form (REQ-PRB-014), through the search port (ADR-029).
- `copy_values`: a copy's starting values (REQ-PRB-015): the fields only for now, the subject
  marked with the original's display ID (language-neutral), and values retired since then
  left empty and named (AC3). Analysis and solution parts join when those fields exist
  (WP-044b); tasks, attachments, links, conversations and history are never copied.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules.identity_access import Subject
from app.modules.work_items.domain.conversation import FollowReason
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES, StatusCategory
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.templates import PickList
from app.modules.work_items.domain.types import INCIDENT, PROBLEM, SUBJECT_MAX
from app.modules.work_items.infra.models import WorkItem, WorkItemCategory, WorkItemLink
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import followers, parts, search
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.conversations import Subjects
from app.shared.history import Change, Source, record_changes

_DONE = frozenset({StatusCategory.RESOLVED, *FINAL_CATEGORIES})
SIMILAR_LIMIT = 5
SIMILAR_MIN_TEXT = 3  # shorter drafts match almost anything


async def _same_category(session: AsyncSession, category_id: uuid.UUID | None) -> uuid.UUID | None:
    """The problem category with the same seeded code and level, if any (trees are per type)."""
    if category_id is None:
        return None
    node = await session.get(WorkItemCategory, category_id)
    if node is None or node.code is None:
        return None
    found: uuid.UUID | None = await session.scalar(
        select(WorkItemCategory.id).where(
            WorkItemCategory.type == PROBLEM.code,
            WorkItemCategory.code == node.code,
            WorkItemCategory.level == node.level,
            WorkItemCategory.deleted_at.is_(None),
        )
    )
    return found


async def prefill(
    session: AsyncSession, subject: Subject, incident_id: uuid.UUID
) -> dict[str, Any]:
    """A new problem's starting values from an incident the subject may see (REQ-PRB-011 AC1).

    Reported by: the person creating it (REQ-PRB-010 AC1).
    """
    incident = await items.visible_record(session, subject, INCIDENT, incident_id)
    return {
        "subject": incident.subject,
        "description": incident.description,
        "impact": incident.impact,
        "urgency": incident.urgency,
        "site_id": incident.site_id,
        "category_id": await _same_category(session, incident.category_id),
        "requester_id": subject.user_id,
        "problem_type": "reactive",
        "source_incident_id": incident.id,
    }


async def causing_problem(session: AsyncSession, incident_id: uuid.UUID) -> WorkItemLink | None:
    """The incident's live "caused by" link, if it has one."""
    found: WorkItemLink | None = await session.scalar(
        select(WorkItemLink).where(
            WorkItemLink.source_id == incident_id,
            WorkItemLink.kind == LinkKind.CAUSED_BY.value,
            WorkItemLink.deleted_at.is_(None),
        )
    )
    return found


async def link_cause(  # noqa: PLR0913 - both records, the move and the source, explicit
    session: AsyncSession,
    subject: Subject,
    incident_id: uuid.UUID,
    problem_id: uuid.UUID,
    *,
    move: bool,
    source: Source,
) -> WorkItemLink | None:
    """Record that the incident is caused by the problem; None when it already was.

    The change is the incident's: editing the incident is the right that counts. The problem
    only has to be one the subject may see (a group's technician links incidents to a problem
    they just created without a group, or to another group's problem they can see).
    """
    incident = await items.record_for_action(session, subject, INCIDENT, "edit", incident_id)
    problem = await problem_of(session, subject, problem_id)
    current = await causing_problem(session, incident.id)
    if current is not None and current.target_id == problem.id:
        return None
    if current is not None:
        other = await session.get(WorkItem, current.target_id)
        if not move:
            raise Conflict(
                code="incident_has_problem",
                params={"display_id": other.display_id if other is not None else ""},
            )
        removed = await parts.LinkRepository(session).soft_delete(
            current.id, expected_version=current.version
        )
        if other is not None:
            await parts.link_recorded(session, incident, other, removed, "child_removed", source)
    link = await parts.LinkRepository(session).add(
        WorkItemLink(source_id=incident.id, target_id=problem.id, kind=LinkKind.CAUSED_BY.value)
    )
    await parts.link_recorded(session, incident, problem, link, "child_added", source)
    return link


async def unlink_cause(
    session: AsyncSession,
    subject: Subject,
    incident_id: uuid.UUID,
    problem_id: uuid.UUID | None,
    *,
    source: Source,
) -> bool:
    """The incident is no longer caused by its problem (only by `problem_id`, when given).

    Like linking, the change is the incident's: editing it is the right that counts. False when
    there was nothing to remove.
    """
    incident = await items.record_for_action(session, subject, INCIDENT, "edit", incident_id)
    current = await causing_problem(session, incident.id)
    if current is None or (problem_id is not None and current.target_id != problem_id):
        return False
    problem = await session.get(WorkItem, current.target_id)
    removed = await parts.LinkRepository(session).soft_delete(
        current.id, expected_version=current.version
    )
    if problem is not None:
        await parts.link_recorded(session, incident, problem, removed, "child_removed", source)
    return True


async def already_caused(
    session: AsyncSession, subject: Subject, incident_ids: list[uuid.UUID]
) -> Mapping[uuid.UUID, str]:
    """Of these incidents, those already caused by a problem, with its display ID (AC2).

    Only incidents the subject may see are answered (others are left out, never leaked).
    """
    if not incident_ids:
        return {}
    rows = await session.execute(
        items.staff_rows(subject, INCIDENT)
        .with_only_columns(WorkItem.id)
        .where(WorkItem.id.in_(incident_ids))
    )
    visible = [r for (r,) in rows.all()]
    if not visible:
        return {}
    linked = await session.execute(
        select(WorkItemLink.source_id, WorkItem.display_id)
        .join(WorkItem, WorkItem.id == WorkItemLink.target_id)
        .where(
            WorkItemLink.source_id.in_(visible),
            WorkItemLink.kind == LinkKind.CAUSED_BY.value,
            WorkItemLink.deleted_at.is_(None),
        )
    )
    return {row[0]: row[1] for row in linked.all()}


async def similar(session: AsyncSession, subject: Subject, text: str) -> list[WorkItem]:
    """Open problems the subject may see that look like this draft, best first (REQ-PRB-014)."""
    if len(text.strip()) < SIMILAR_MIN_TEXT:
        return []
    found = await search.search(session, subject, PROBLEM, text, limit=SIMILAR_LIMIT * 2)
    return [r for r in found if StatusCategory(r.status_category) not in _DONE][:SIMILAR_LIMIT]


async def problem_of(session: AsyncSession, subject: Subject, problem_id: uuid.UUID) -> WorkItem:
    """A problem the subject may see (404 otherwise)."""
    try:
        return await items.visible_record(session, subject, PROBLEM, problem_id)
    except NotFound:
        raise NotFound(code="work_item_not_found") from None


COPY_FIELDS = (
    "subject",
    "description",
    "category_id",
    "impact",
    "impact_details",
    "urgency",
    "level",
    "site_id",
    "department_id",
    "group_id",
    "problem_type",
    "root_cause_category",
)
_COPY_LISTS = {
    "level": PickList.LEVEL,
    "problem_type": PickList.PROBLEM_TYPE,
    "root_cause_category": PickList.ROOT_CAUSE,
}


async def copy_values(
    session: AsyncSession, subject: Subject, problem_id: uuid.UUID
) -> tuple[WorkItem, dict[str, Any], list[str]]:
    """The original, the copy's values and the fields left empty as now retired (REQ-PRB-015)."""
    original = await problem_of(session, subject, problem_id)
    cat = await config.load(session, PROBLEM)
    values: dict[str, Any] = {
        name: getattr(original, name) for name in COPY_FIELDS if getattr(original, name) is not None
    }
    left_empty: list[str] = []
    for name, pick in _COPY_LISTS.items():
        if name in values and values[name] not in cat.reason_codes(pick):
            del values[name]
            left_empty.append(name)
    if "category_id" in values:
        node = await session.get(WorkItemCategory, values["category_id"])
        if node is None or node.disabled_at is not None or node.deleted_at is not None:
            del values["category_id"]
            left_empty.append("category_id")
    mark = f" ({original.display_id})"
    values["subject"] = original.subject[: SUBJECT_MAX - len(mark)] + mark
    values["requester_id"] = subject.user_id
    return original, values, sorted(left_empty)


async def copied_from(
    session: AsyncSession, copy: WorkItem, original: WorkItem, source: Source
) -> None:
    """The copy's history names the original (REQ-PRB-015 AC2)."""
    await record_changes(
        session,
        record_type=parts.RECORD_TYPE,
        record_id=copy.id,
        version=copy.version,
        kind="updated",
        changes=[
            Change("copied_from", None, {"id": str(original.id), "display_id": original.display_id})
        ],
        source=source,
    )


# --- investigators (REQ-PRB-029, ADR-040) ----------------------------------------------------


async def investigators(
    session: AsyncSession, subject: Subject, problem_id: uuid.UUID
) -> list[uuid.UUID]:
    """The problem's investigators, oldest first."""
    record = await problem_of(session, subject, problem_id)
    return [
        r.user_id
        for r in await followers.of_record(session, record.id)
        if r.grants_access and r.reason == FollowReason.INVESTIGATOR.value
    ]


async def add_investigator(  # noqa: PLR0913 - the problem, the person and the context, explicit
    session: AsyncSession,
    subject: Subject,
    problem_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    policy: Subjects,
    source: Source,
) -> None:
    """Name a technician as an investigator: whoever may edit the problem (ADR-040 §3)."""
    record = await items.record_for_action(session, subject, PROBLEM, "edit", problem_id)
    person = await policy.subject(subject.tenant_id, user_id, session)
    if not person.holds(PROBLEM.permission("view")):
        raise items.field_errors([("user_id", "not_a_technician")])
    existing = await followers.current(session, record.id, user_id)
    if existing is not None and existing.reason == FollowReason.INVESTIGATOR.value:
        return
    if existing is not None:  # following already: becomes the investigator row
        await followers.unfollow(session, record, existing, source=source)
    await followers.follow(
        session,
        record,
        user_id,
        reason=FollowReason.INVESTIGATOR,
        grants_access=True,
        source=source,
    )
    await _investigator_history(session, record, None, str(user_id), source)


async def remove_investigator(
    session: AsyncSession,
    subject: Subject,
    problem_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    source: Source,
) -> None:
    """End an investigator's follow, and so their access (REQ-PRB-029 AC3)."""
    if user_id == subject.user_id:  # stepping down needs no edit right
        record = await problem_of(session, subject, problem_id)
    else:
        record = await items.record_for_action(session, subject, PROBLEM, "edit", problem_id)
    row = await followers.current(session, record.id, user_id)
    if row is None or row.reason != FollowReason.INVESTIGATOR.value:
        raise NotFound(code="investigator_not_found")
    await followers.unfollow(session, record, row, source=source)
    await _investigator_history(session, record, str(user_id), None, source)


async def _investigator_history(
    session: AsyncSession, record: WorkItem, old: str | None, new: str | None, source: Source
) -> None:
    await record_changes(
        session,
        record_type=parts.RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_added" if new is not None else "child_removed",
        changes=[Change("investigator", old, new)],
        source=source,
    )


__all__ = [
    "COPY_FIELDS",
    "add_investigator",
    "already_caused",
    "causing_problem",
    "copied_from",
    "copy_values",
    "investigators",
    "link_cause",
    "prefill",
    "problem_of",
    "remove_investigator",
    "similar",
]
