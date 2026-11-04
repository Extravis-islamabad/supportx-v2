"""Incidents on the SLA module (WP-025 session 2; wp-025-plan.md §3.1).

Registers the incident record type with sla: the fields a policy's conditions may use and the
priority codes, highest first. The SLA fields themselves (due dates, the policy, paused time)
and the record's own timestamps are left out: a policy chosen by its own due date would go round
in circles, and a condition on "created before" would match differently on every recalculation.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import sla
from app.modules.work_items.domain.classification import Priority
from app.modules.work_items.domain.lifecycle import ServiceRequestStatus, StatusCategory
from app.modules.work_items.domain.types import WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service.access import FIELDS
from app.modules.work_items.service.followers import RECORD_TYPE
from app.shared.api.filters import ResourceFields
from app.shared.history import Change, record_changes

# Fields no policy condition may name (see the docstring).
_NOT_CONDITIONS = frozenset(
    {
        "id",
        "display_id",
        "display_number",
        "sla_policy_id",
        "resolution_due_at",
        "first_response_due_at",
        "first_response_sla_state",
        "resolution_sla_state",
        "first_response_breached",
        "resolution_breached",
        "first_responded_at",
        "paused_seconds",
        "created_at",
        "updated_at",
        "status_changed_at",
        "first_assigned_at",
        "resolved_at",
        "closed_at",
        "created_by",
        "updated_by",
    }
)

CONDITION_FIELDS = ResourceFields(
    FIELDS.name,
    {k: v for k, v in FIELDS.fields.items() if k not in _NOT_CONDITIONS},
    FIELDS.id_column,
)


AWAITING_APPROVAL = ServiceRequestStatus.AWAITING_APPROVAL.value
SLA_TYPES = frozenset({WorkItemTypeCode.INCIDENT.value, WorkItemTypeCode.SERVICE_REQUEST.value})


def register_sla() -> None:
    """Incidents and service requests have SLAs (called at import; idempotent).

    Service requests (WP-030) take the same policies, conditions and firing; the item's own SLA
    and the clock waiting for approval (REQ-SR-006, -007) come with the approval engine.
    """
    for code in (WorkItemTypeCode.INCIDENT, WorkItemTypeCode.SERVICE_REQUEST):
        sla.register_record_type(
            sla.SlaRecordType(
                code=code.value,
                fields=CONDITION_FIELDS,
                priorities=tuple(p.value for p in Priority),
                lock_record=lock_record,
                on_fired=_on_fired,
                run_actions=_run_actions,
            )
        )


async def lock_record(session: AsyncSession, record_id: uuid.UUID) -> None:
    """Lock the record row: always before its SLA clocks (sla's `LockHook`, one lock order)."""
    await session.execute(select(WorkItem.id).where(WorkItem.id == record_id).with_for_update())


async def _on_fired(
    session: AsyncSession,
    record_id: uuid.UUID,
    columns: Mapping[str, Any],
    fired: list[sla.Fired],
    *,
    now: datetime,
) -> None:
    # Imported here: work_items.py imports this module (the save path calls it).
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - see above

    await items.sla_fired(session, record_id, columns, fired, now=now)


async def _run_actions(
    session: AsyncSession, record_id: uuid.UUID, level: sla.Level, *, now: datetime
) -> list[dict[str, object]]:
    from app.modules.work_items.service import escalations  # noqa: PLC0415 - as `_on_fired`

    return await escalations.run_actions(session, record_id, level, now=now)


def fired_changes(
    record: WorkItem, changed: Mapping[str, Any], fired: list[sla.Fired]
) -> list[Change]:
    """History lines of a firing: the SLA columns that moved, and each level that ran."""
    lines = [Change(k, _plain(getattr(record, k)), _plain(v)) for k, v in changed.items()]
    lines += [
        Change("sla_escalation", None, f"{f.kind}:{f.position}")
        for f in fired
        if f.what == "escalated" and not f.skipped
    ]
    return lines


# What the SLA clock reads beyond the condition fields (sla.service.registry names them).
_CLOCK_FIELDS = (
    "status",
    "status_category",
    "priority",
    "site_id",
    "group_id",
    "first_responded_at",
)
SNAPSHOT_FIELDS = tuple(dict.fromkeys((*CONDITION_FIELDS.fields, *_CLOCK_FIELDS)))
STAMP_COLUMNS = (
    "sla_policy_id",
    "first_response_due_at",
    "resolution_due_at",
    "first_response_sla_state",
    "resolution_sla_state",
    "first_response_breached",
    "resolution_breached",
)


def snapshot(record: WorkItem, changes: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The record as sla sees it, with `changes` applied (field name -> value)."""
    values = {name: getattr(record, name) for name in SNAPSHOT_FIELDS}
    values |= {k: v for k, v in (changes or {}).items() if k in values}
    # An item that counts approval time keeps the clock running while it waits (REQ-SR-007 AC2):
    # the SLA sees "awaiting approval" as open work, not a pause.
    if record.sla_counts_approval and values["status"] == AWAITING_APPROVAL:
        values["status_category"] = StatusCategory.OPEN.value
    return values


def has_sla(record: WorkItem) -> bool:
    """Whether this record's type has SLAs (registered above).

    Service requests too (WP-030 s2, D6): "awaiting approval" is a paused status, so the
    resolution clock waits for the approval by default (REQ-SR-007 AC1, AC3).
    """
    return record.type in SLA_TYPES


async def sla_columns(
    session: AsyncSession,
    record: WorkItem,
    changes: Mapping[str, Any] | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    """The SLA columns this save changes (`changes` None: the record was just created)."""
    if not has_sla(record):
        return {}
    before = None if changes is None else snapshot(record)
    if before is not None:
        await lock_record(session, record.id)  # before the clocks (registry.LockHook)
    after = snapshot(record, changes)
    stamp = await sla.on_change(session, record.type, record.id, before, after, now=now)
    return {k: v for k, v in stamp.columns().items() if getattr(record, k) != v}


def _plain(value: object) -> object:
    """A history value: dates as ISO text, IDs as text."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if isinstance(value, uuid.UUID) else value


async def record_sla_history(
    session: AsyncSession, record: WorkItem, before: Mapping[str, Any], columns: Mapping[str, Any]
) -> None:
    """The SLA's own changes in the record's history, with source `sla` (§7.4)."""
    if columns:
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=record.id,
            version=record.version,
            kind="updated",
            changes=[Change(k, _plain(before.get(k)), _plain(v)) for k, v in columns.items()],
            source="sla",
        )


# The record column that shows each target's due moment (REQ-SLA-028).
DUE_COLUMNS = {"first_response": "first_response_due_at", "resolution": "resolution_due_at"}


async def set_due(  # noqa: PLR0913 - the change and who makes it, explicit
    session: AsyncSession,
    record: WorkItem,
    kind: str,
    due_at: datetime | None,
    *,
    reason: str,
    now: datetime,
    actor: uuid.UUID,
) -> dict[str, Any]:
    """Set or clear a due date by hand in sla; returns the record's SLA columns after it."""
    await lock_record(session, record.id)
    stamp = await sla.set_due_by_hand(
        session, record.type, record.id, kind, due_at, reason=reason, now=now, actor=actor
    )
    return stamp.columns()


def due_change(record: WorkItem, kind: str, columns: Mapping[str, Any]) -> Change:
    """The history line of a due date set or cleared by hand."""
    column = DUE_COLUMNS[kind]
    return Change(column, _plain(getattr(record, column)), _plain(columns.get(column)))


SlaRecordView = sla.SlaRecordView


async def record_view(session: AsyncSession, record: WorkItem) -> sla.SlaRecordView:
    """The record's SLA for its panel; a type without SLAs has none."""
    if not has_sla(record):
        return sla.SlaRecordView(
            policy_id=None, policy_name=None, reason=None, applied_at=None, targets=()
        )
    return await sla.record_sla(session, record.id)
