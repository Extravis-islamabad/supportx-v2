"""Major incidents (WP-046b S4; REQ-INC-141, D-043 Essentials).

- `declare` / `end`: the flag, with `incidents.declare_major` and a reason, on an open incident
  the actor may edit. Declaring switches to the tenant's major incident template when one is set.
  Both are audited; the reason is free text (possibly personal data), so it is kept on the record
  and in the audit entry's personal part, and field history names the fields only (lane B).
- The `work_items.major.changed` event (IDs and the flag only) tells the major incident team
  through the one notification engine, which checks each member's access at send time: declaring
  grants nobody access and adds no follower (lane B).
- `settings` / `update_settings`: the team (a group and named people) and the template, with the
  type settings' right, If-Match and an audit entry with before and after.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, PermissionDenied
from app.modules.audit import WORKER as AUDIT_WORKER
from app.modules.audit import RequestFacts
from app.modules.audit import record as record_audit
from app.modules.identity_access import Subject, active_user_ids
from app.modules.organization import active_unit_ids
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.events import WorkItemMajorChanged, WorkItemSettingsChanged
from app.modules.work_items.infra.models import WorkItem, WorkItemTemplate, WorkItemTypeSettings
from app.modules.work_items.service import catalogue
from app.modules.work_items.service import settings as settings_service
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import DECLARE_MAJOR
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

REASON_MAX = 500  # as every other reason
DECLARED = "incident.major_declared"
ENDED = "incident.major_ended"
# Named in history without values: the reason may be personal data (lane B).
UNRECORDED = frozenset({"major_reason", "major_declared_by"})


async def _for_change(session: AsyncSession, subject: Subject, record_id: uuid.UUID) -> WorkItem:
    record = await items.record_for_action(session, subject, INCIDENT, "edit", record_id)
    if not await items.may(session, subject, INCIDENT, DECLARE_MAJOR, record.id):
        raise PermissionDenied(
            params={"permission": INCIDENT.permission(DECLARE_MAJOR), "reason": "no_permission"}
        )
    if StatusCategory(record.status_category) not in {StatusCategory.OPEN, StatusCategory.PAUSED}:
        raise Conflict(code="record_closed", params={"status": record.status, "locked": False})
    return record


def _reason(reason: str) -> str:
    text = reason.strip()
    if not text:
        raise items.field_errors([("reason", "required")])
    if len(text) > REASON_MAX:
        raise items.field_errors([("reason", "value_too_long")])
    return text


async def _changed(
    session: AsyncSession,
    record: WorkItem,
    *,
    code: str,
    reason: str,
    facts: RequestFacts | None,
) -> None:
    await record_event(
        session,
        WorkItemMajorChanged(work_item_id=record.id, major=record.major),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    await record_audit(
        session,
        action_code=code,
        facts=facts or AUDIT_WORKER,
        object_type=INCIDENT.code.value,
        object_id=str(record.id),
        details={"display_id": record.display_id},
        reason=reason,  # the audit entry's personal part
    )


async def declare(  # noqa: PLR0913 - the incident, its version, the reason and the source
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    expected_version: int,
    reason: str,
    source: Source,
    facts: RequestFacts | None = None,
) -> WorkItem:
    """Declare it major (409 `already_major`); the tenant's major template applies, if set."""
    why = _reason(reason)
    record = await _for_change(session, subject, record_id)
    if record.major:
        raise Conflict(code="already_major", params={"display_id": record.display_id})
    columns: dict[str, Any] = {
        "major": True,
        "major_declared_at": datetime.now(UTC),
        "major_declared_by": subject.user_id,
        "major_reason": why,
    }
    template = (await catalogue.load(session, INCIDENT)).major.template_id
    if template is not None and record.template_id != template:
        columns["template_id"] = template
    updated = await items.set_fields(
        session,
        record,
        columns,
        expected_version=expected_version,
        source=source,
        unrecorded=UNRECORDED,
    )
    await _changed(session, updated, code=DECLARED, reason=why, facts=facts)
    return updated


async def end(  # noqa: PLR0913 - the incident, its version, the reason and the source
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    expected_version: int,
    reason: str,
    source: Source,
    facts: RequestFacts | None = None,
) -> WorkItem:
    """End the major status (409 `not_major`); the time it was declared stays in history."""
    why = _reason(reason)
    record = await items.record_for_action(session, subject, INCIDENT, "edit", record_id)
    if not await items.may(session, subject, INCIDENT, DECLARE_MAJOR, record.id):
        raise PermissionDenied(
            params={"permission": INCIDENT.permission(DECLARE_MAJOR), "reason": "no_permission"}
        )
    if not record.major:
        raise Conflict(code="not_major", params={"display_id": record.display_id})
    updated = await items.set_fields(
        session,
        record,
        {"major": False, "major_reason": None},
        expected_version=expected_version,
        source=source,
        unrecorded=UNRECORDED,
    )
    await _changed(session, updated, code=ENDED, reason=why, facts=facts)
    return updated


@dataclass(frozen=True)
class MajorTeam:
    """Who is told when an incident is declared major."""

    group_id: uuid.UUID | None
    user_ids: tuple[uuid.UUID, ...]


async def team(session: AsyncSession) -> MajorTeam:
    """The tenant's major incident team, as set now."""
    major = (await catalogue.load(session, INCIDENT)).major
    return MajorTeam(major.group_id, major.user_ids)


async def majors_open(session: AsyncSession, subject: Subject) -> list[WorkItem]:
    """The open major incidents the subject may see, newest declaration first."""
    rows = await session.scalars(
        items.staff_rows(subject, INCIDENT)
        .where(
            WorkItem.major.is_(True),
            WorkItem.status_category.in_([StatusCategory.OPEN.value, StatusCategory.PAUSED.value]),
        )
        .order_by(WorkItem.major_declared_at.desc(), WorkItem.id)
        .limit(100)
    )
    return list(rows)


MAJOR_USERS_MAX = 50  # named people besides the group; a team, not a mailing list
# The settings' field problems (labelled: errors.field.<code>).
FIELD_PROBLEMS = frozenset({"unknown_group", "too_many", "unknown_reference", "template_not_found"})


async def _check_settings(
    session: AsyncSession,
    group_id: uuid.UUID | None,
    user_ids: Sequence[uuid.UUID],
    template_id: uuid.UUID | None,
) -> None:
    problems: list[tuple[str, str]] = []
    if group_id is not None and not await active_unit_ids(session, "group", [group_id]):
        problems.append(("group_id", "unknown_group"))
    if len(user_ids) > MAJOR_USERS_MAX:
        problems.append(("user_ids", "too_many"))
    elif set(user_ids) - await active_user_ids(session, list(user_ids)):
        problems.append(("user_ids", "unknown_reference"))
    if template_id is not None:
        # A live incident template of this tenant (RLS), not disabled (lane B: server-checked).
        found = await session.scalar(
            select(WorkItemTemplate.id).where(
                WorkItemTemplate.id == template_id,
                WorkItemTemplate.type == INCIDENT.code.value,
                WorkItemTemplate.deleted_at.is_(None),
                WorkItemTemplate.disabled_at.is_(None),
            )
        )
        if found is None:
            problems.append(("template_id", "template_not_found"))
    if problems:
        raise items.field_errors(problems)


async def update_settings(  # noqa: PLR0913 - the team, the template, the version and who
    session: AsyncSession,
    *,
    group_id: uuid.UUID | None,
    user_ids: Sequence[uuid.UUID],
    template_id: uuid.UUID | None,
    expected_version: int,
    source: Source,
    user_id: uuid.UUID,
) -> tuple[catalogue.Catalogue, dict[str, Any], dict[str, Any]]:
    """Set the major incident team and template (If-Match on the type's settings).

    Returns the new catalogue and the before and after values (IDs only) for the audit entry.
    """
    current = await catalogue.load(session, INCIDENT)
    people = sorted(set(user_ids), key=str)
    await _check_settings(session, group_id, people, template_id)
    if current.settings_version != expected_version:
        raise await settings_service.stale_settings(session, INCIDENT, current, expected_version)
    before = {
        "major_group_id": current.major.group_id,
        "major_user_ids": sorted(current.major.user_ids, key=str),
        "major_template_id": current.major.template_id,
    }
    after = {"major_group_id": group_id, "major_user_ids": people, "major_template_id": template_id}
    changes = {k: v for k, v in after.items() if before[k] != v}
    if not changes:
        return current, before, after
    await session.execute(
        update(WorkItemTypeSettings)
        .where(WorkItemTypeSettings.type == INCIDENT.code)
        .values(**changes, version=WorkItemTypeSettings.version + 1, updated_by=user_id)
    )
    settings_id = catalogue.settings_record_id(INCIDENT.code)
    await record_changes(
        session,
        record_type=settings_service.SETTINGS_RECORD_TYPE,
        record_id=settings_id,
        version=expected_version + 1,
        kind="updated",
        changes=[Change(k, _ids(before[k]), _ids(v)) for k, v in changes.items()],
        source=source,
    )
    await record_event(
        session,
        WorkItemSettingsChanged(type=INCIDENT.code, changed_fields=sorted(changes)),
        aggregate_id=settings_id,
        aggregate_version=expected_version + 1,
    )
    session.expire_all()
    return await catalogue.load(session, INCIDENT), _ids(before), _ids(after)


def _ids(value: Any) -> Any:  # noqa: ANN401 - an ID, a list of IDs or a mapping of them
    """IDs as strings, for history and the audit entry."""
    if isinstance(value, dict):
        return {k: _ids(v) for k, v in value.items()}
    if isinstance(value, list):
        return [str(v) for v in value]
    return None if value is None else str(value)
