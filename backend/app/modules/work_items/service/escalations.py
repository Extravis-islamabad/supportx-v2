"""What an SLA escalation level does to an incident (REQ-SLA-024; WP-025 session 3).

sla runs a level once and asks here for its actions (its `ActionsHook`). Each action goes
through the same save path as a business rule's (`automated_update`, `automated_note`), with
history from source "sla", inside its own savepoint: one failing action is recorded on the run
with its code and never stops the others or the level (REQ-SLA-024 AC3).

Raising the priority follows the tenant's priority-change rule like any other change: with the
default "recalculate", the running targets follow the new priority (REQ-SLA-024 AC2 asks for a
policy option to keep them; recorded in PROGRESS for the product owner).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules import sla
from app.modules.identity_access import person_placement
from app.modules.organization import unit_heads, users_in_groups
from app.modules.work_items.domain.classification import Priority
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import conversations
from app.modules.work_items.service import work_items as items

_ORDER = [p.value for p in Priority]  # highest first


def raised(priority: str | None) -> str | None:
    """One step up (P3 → P2); None when already the highest or not set."""
    if priority not in _ORDER:
        return None
    at = _ORDER.index(priority)
    return _ORDER[at - 1] if at > 0 else None


def _values(action: sla.Action, record: WorkItem) -> dict[str, Any] | None:
    """The fields an action sets; None for a note, {} when there is nothing to change."""
    if action.kind is sla.ActionKind.REASSIGN_GROUP:
        return {"group_id": action.target_id, "technician_id": None}
    if action.kind is sla.ActionKind.REASSIGN_PERSON:
        return {"technician_id": action.target_id}
    if action.kind is sla.ActionKind.RAISE_PRIORITY:
        up = raised(record.priority)
        return {"priority": up} if up else {}
    return None


async def run_actions(
    session: AsyncSession, record_id: uuid.UUID, level: sla.Level, *, now: datetime
) -> list[dict[str, object]]:
    """Run a level's actions in order; one outcome per action ({kind, ok, code})."""
    del now
    ref = {"kind": "sla_escalation", "target": level.kind.value, "level": level.position}
    cause = uuid.uuid5(record_id, level.key)  # stable per level: the loop guard sees one chain
    outcomes: list[dict[str, object]] = []
    for action in level.actions:
        record = await session.scalar(select(WorkItem).where(WorkItem.id == record_id))
        if record is None:
            outcomes.append({"kind": action.kind.value, "ok": False, "code": "record_gone"})
            continue
        wtype = TYPES[WorkItemTypeCode(record.type)]
        try:
            async with session.begin_nested():
                values = _values(action, record)
                if values is None:
                    await conversations.automated_note(
                        session,
                        wtype,
                        record_id,
                        action.text or "",
                        ref=ref,
                        cause_id=cause,
                        source="sla",
                    )
                    changed = True
                elif values:
                    changed = bool(
                        await items.automated_update(
                            session, wtype, record_id, values, ref=ref, cause_id=cause, source="sla"
                        )
                    )
                else:
                    changed = False
        except AppError as refused:
            outcomes.append({"kind": action.kind.value, "ok": False, "code": refused.instance_code})
            continue
        outcomes.append(
            {"kind": action.kind.value, "ok": True, "code": None if changed else "no_change"}
        )
    return outcomes


async def _relative(
    session: AsyncSession, record: WorkItem, kind: sla.RecipientKind
) -> frozenset[uuid.UUID]:
    """The people a relative recipient kind names on this record now (REQ-SLA-023)."""
    if kind is sla.RecipientKind.ASSIGNEE:
        return frozenset({record.technician_id} if record.technician_id else ())
    if kind in {sla.RecipientKind.GROUP_HEAD, sla.RecipientKind.DEPARTMENT_HEAD}:
        lead, head = await unit_heads(session, record.group_id, record.department_id)
        person = lead if kind is sla.RecipientKind.GROUP_HEAD else head
        return frozenset({person} if person else ())
    whose = (
        record.technician_id if kind is sla.RecipientKind.ASSIGNEE_MANAGER else record.requester_id
    )
    if whose is None:
        return frozenset()
    manager = (await person_placement(session, whose)).manager_id
    return frozenset({manager} if manager else ())


async def _named(session: AsyncSession, who: sla.Recipient) -> frozenset[uuid.UUID]:
    if who.id is None:
        return frozenset()
    if who.kind is sla.RecipientKind.USER:
        return frozenset({uuid.UUID(who.id)})
    members = await session.scalars(users_in_groups(frozenset({uuid.UUID(who.id)})))
    return frozenset(members)


async def level_people(
    session: AsyncSession, record: WorkItem, level: sla.Level
) -> tuple[frozenset[uuid.UUID], bool]:
    """Who a level tells, and whether its fallback list was used (REQ-SLA-023 AC1).

    A relative who is not set (no assignee, no manager) falls back to the level's fallback
    list. Whether each person may see the record is the notification engine's check at send
    time (the source's `access`), so a recipient who cannot is skipped there (AC3).
    """
    people: set[uuid.UUID] = set()
    missing = False
    for who in level.recipients:
        if who.kind in {sla.RecipientKind.USER, sla.RecipientKind.GROUP}:
            people |= await _named(session, who)
            continue
        found = await _relative(session, record, who.kind)
        missing = missing or not found
        people |= found
    if not missing:
        return frozenset(people), False
    for who in level.fallback:
        found = (
            await _named(session, who)
            if who.kind in {sla.RecipientKind.USER, sla.RecipientKind.GROUP}
            else await _relative(session, record, who.kind)
        )
        if found:
            return frozenset(people | found), True  # the first fallback that names someone
    return frozenset(people), False
