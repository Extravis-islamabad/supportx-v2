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
from app.modules.work_items.domain.lifecycle import (
    DEFAULT_STATUSES,
    DONE_CATEGORIES,
    ServiceRequestStatus,
    StatusCategory,
)
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
SLA_TYPES = frozenset(
    {
        WorkItemTypeCode.INCIDENT.value,
        WorkItemTypeCode.SERVICE_REQUEST.value,
        WorkItemTypeCode.PROBLEM.value,
    }
)
# Problems (WP-044a, REQ-PRB-008, Appendix A): a target date only, in business days from
# creation (P1 5, P2 10, P3 20, P4 40), on the site's calendar; no first response.
PROBLEM_TARGETS: tuple[tuple[str, str, int, str, str], ...] = tuple(
    (priority, "resolution", days, "business_days", "site")
    for priority, days in (("p1", 5), ("p2", 10), ("p3", 20), ("p4", 40))
)


def register_sla() -> None:
    """Incidents, service requests and problems have SLAs (called at import; idempotent).

    Service requests (WP-030) take the same policies, conditions and firing; the item's own SLA
    and the clock waiting for approval (REQ-SR-006, -007) come with the approval engine.
    """
    for code in (
        WorkItemTypeCode.INCIDENT,
        WorkItemTypeCode.SERVICE_REQUEST,
        WorkItemTypeCode.PROBLEM,
    ):
        sla.register_record_type(
            sla.SlaRecordType(
                code=code.value,
                fields=CONDITION_FIELDS,
                priorities=tuple(p.value for p in Priority),
                lock_record=lock_record,
                on_fired=_on_fired,
                run_actions=_run_actions,
                record_state=record_state,
                preferred_policy=_item_policy,
                default_targets=PROBLEM_TARGETS if code is WorkItemTypeCode.PROBLEM else None,
                target_dates_only=code is WorkItemTypeCode.PROBLEM,
            )
        )


def _item_policy(values: Mapping[str, Any]) -> uuid.UUID | None:
    """The catalog item's own SLA policy, kept on the request (REQ-SR-006)."""
    found = values.get("item_sla_policy_id")
    return found if isinstance(found, uuid.UUID) else None


async def record_state(session: AsyncSession, record_id: uuid.UUID) -> sla.RecordState:
    """Whether the record's clocks may fire (sla's `RecordStateHook`).

    In the trash: nothing fires until it is restored, exactly as it was. Not there at all
    (erased): its clocks stop for good. Lane B found one such record failing every run.
    """
    deleted = await session.execute(select(WorkItem.deleted_at).where(WorkItem.id == record_id))
    row = deleted.first()
    if row is None:
        return sla.RecordState.GONE
    return sla.RecordState.LIVE if row.deleted_at is None else sla.RecordState.TRASHED


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
    lines = [Change(k, plain(getattr(record, k)), plain(v)) for k, v in changed.items()]
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
    "item_sla_policy_id",  # REQ-SR-006: the catalog item's own policy wins
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


def plain(value: object) -> object:
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
            changes=[Change(k, plain(before.get(k)), plain(v)) for k, v in columns.items()],
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
    return Change(column, plain(getattr(record, column)), plain(columns.get(column)))


SlaRecordView = sla.SlaRecordView


async def record_view(session: AsyncSession, record: WorkItem) -> sla.SlaRecordView:
    """The record's SLA for its panel; a type without SLAs has none."""
    if not has_sla(record):
        return sla.SlaRecordView(
            policy_id=None, policy_name=None, reason=None, applied_at=None, targets=()
        )
    return await sla.record_sla(session, record.id)


async def replay_from_creation(
    session: AsyncSession, record: WorkItem, *, now: datetime
) -> dict[str, Any]:
    """A record's SLA as if it had applied from its creation; the columns to stamp on it.

    For records saved before any SLA applied (the showcase's older incidents, Haider 2026-11-09).
    The clocks run on the record's own times, through the same `on_change` as every save: start
    at `created_at`; the first response at `first_responded_at`; the end at `resolved_at` or
    `closed_at` for a finished record, else `now`, when an open one past its due breaches.
    Pauses of the past are not known and not replayed: time spent waiting counts as open.
    The record row is locked by the caller.
    """
    final = snapshot(record)
    start = {**final, "status_category": StatusCategory.OPEN.value, "first_responded_at": None}
    if final["status_category"] != StatusCategory.OPEN.value:
        start["status"] = DEFAULT_STATUSES[0].code  # it started new
    at = record.created_at
    stamp = await sla.on_change(session, record.type, record.id, None, start, now=at)
    before = start
    if record.first_responded_at is not None:
        responded = {**start, "first_responded_at": record.first_responded_at}
        at = max(at, record.first_responded_at)
        stamp = await sla.on_change(session, record.type, record.id, before, responded, now=at)
        before = responded
    finished = final["status_category"] in DONE_CATEGORIES
    end = (record.resolved_at or record.closed_at) if finished else None
    at = max(at, end or now)
    stamp = await sla.on_change(session, record.type, record.id, before, final, now=at)
    return dict(stamp.columns())
