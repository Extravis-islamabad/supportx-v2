"""Work items as trigger sources and targets (WP-029 part 2; REQ-RUL-009, 010).

Registers, for every work item type, how automation reads a record's current values, sets
fields through the record's own save path, adds a private note, and reads this module's
events. Automation never reads work item tables itself (CLAUDE.md rule e).
"""

import dataclasses
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import automation
from app.modules.work_items.domain.types import TYPES, WorkItemType
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import conversations
from app.modules.work_items.service import work_items as items
from app.shared.events import EventEnvelope

_RECORD_EVENTS = {
    "work_items.work_item.created": automation.TriggerEvent.CREATED,
    "work_items.work_item.updated": automation.TriggerEvent.UPDATED,
    "work_items.work_item.status_changed": automation.TriggerEvent.STATUS_CHANGED,
    "work_items.work_item.assigned": automation.TriggerEvent.ASSIGNED,
}
_CONVERSATION = "work_items.conversation.added"


async def read_event(
    session: AsyncSession, envelope: EventEnvelope
) -> automation.RecordEvent | None:
    """A committed work item event as triggers see it (None: nothing to react to)."""
    payload = envelope.payload
    if envelope.event_type == _CONVERSATION:
        return await _conversation(session, envelope)
    event = _RECORD_EVENTS.get(envelope.event_type)
    if event is None:
        return None
    record_id = uuid.UUID(str(payload.get("work_item_id") or envelope.aggregate_id))
    changed: list[str] = []
    known: dict[str, Any] = {}
    action = None
    if event == automation.TriggerEvent.UPDATED:
        changed = list(payload.get("changed_fields") or [])
    elif event == automation.TriggerEvent.STATUS_CHANGED:
        changed = ["status", "status_category"]
        known = {"status": payload.get("from_status")}
        action = payload.get("action")
    elif event == automation.TriggerEvent.ASSIGNED:
        changed = ["group_id", "technician_id"]
    return automation.RecordEvent(
        record_type=str(payload["type"]),
        record_id=record_id,
        event=event,
        changed=changed,
        known_before=known,
        action=action,
    )


async def _conversation(
    session: AsyncSession, envelope: EventEnvelope
) -> automation.RecordEvent | None:
    payload = envelope.payload
    record_id = uuid.UUID(str(payload["work_item_id"]))
    row = (
        await session.execute(
            select(WorkItem.type, WorkItem.requester_id, WorkItem.on_behalf_of_id).where(
                WorkItem.id == record_id, WorkItem.deleted_at.is_(None)
            )
        )
    ).first()
    if row is None:
        return None
    if payload.get("kind") == "note":
        event = automation.TriggerEvent.NOTE_ADDED
    elif (
        payload.get("kind") == "reply"
        and envelope.actor.type == "user"
        and envelope.actor.id
        in {
            str(row.requester_id),
            str(row.on_behalf_of_id),
        }
    ):
        event = automation.TriggerEvent.REQUESTER_REPLIED
    else:
        return None
    return automation.RecordEvent(record_type=str(row.type), record_id=record_id, event=event)


def _facts(wtype: WorkItemType) -> automation.FactsReader:
    async def facts(session: AsyncSession, record_id: uuid.UUID) -> Mapping[str, Any] | None:
        return await items.automation_facts(session, wtype, record_id)

    return facts


def _apply(wtype: WorkItemType) -> automation.Applier:
    async def apply(
        session: AsyncSession,
        record_id: uuid.UUID,
        values: Mapping[str, Any],
        change: automation.AutomatedChange,
    ) -> list[str]:
        return await items.automated_update(
            session, wtype, record_id, values, ref=change.ref, cause_id=change.cause_id
        )

    return apply


def _note(wtype: WorkItemType) -> automation.Noter:
    async def note(
        session: AsyncSession, record_id: uuid.UUID, text: str, change: automation.AutomatedChange
    ) -> None:
        await conversations.automated_note(
            session, wtype, record_id, text, ref=change.ref, cause_id=change.cause_id
        )

    return note


def register_triggers() -> None:
    """Give every registered work item type its trigger hooks (module import, after types)."""
    for wtype in TYPES.values():
        current = automation.record_type(wtype.code.value)
        if current is None:
            continue
        automation.register_record_type(
            dataclasses.replace(
                current,
                facts=_facts(wtype),
                apply=_apply(wtype),
                add_note=_note(wtype),
                transition_actions=tuple(a.value for a in items.ACTION_PERMISSION),
            )
        )
    automation.register_event_reader((*_RECORD_EVENTS, _CONVERSATION), read_event)
