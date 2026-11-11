"""A release's conflicts and their acknowledgements (WP-058b S2; REQ-REL-041; ADR-042 addendum A).

The conflicts are change_conflicts' (one check for changes and releases). Each has a key naming
it as it is now: its kind, what it is with, and both sides' versions of their planned times, so
moving either side gives a new key. An ack (a reason, who, when) holds for its key only: it
lapses when its conflict moves or goes, and a new conflict never inherits it (the coordinator's
S2 terms). Only a warning is acknowledged; a block goes through the freeze override.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules.identity_access import Subject
from app.modules.work_items.domain import change_windows as model
from app.modules.work_items.domain.types import WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import (
    ChangeWindow,
    WorkItem,
    WorkItemConflictAck,
    WorkItemDowntime,
    WorkItemStageSchedule,
)
from app.modules.work_items.service import change_conflicts
from app.shared.history import Change, Source

REASON_MAX = 500
NOT_FOUND = "conflict_not_found"
BLOCKS = "conflict_blocks"


@dataclass(frozen=True)
class ShownConflict:
    """One conflict now: its key, whether it blocks after the overrides, and its ack if any."""

    conflict: model.Conflict
    key: str
    blocks: bool
    ack: WorkItemConflictAck | None


async def own_mark(session: AsyncSession, record: WorkItem) -> str:
    """The record's own side of every key: its planned window's and planned downtimes' versions."""
    stage = model.PLANNED_STAGE.get(record.type, "")
    window = await session.scalar(
        select(WorkItemStageSchedule.version).where(
            WorkItemStageSchedule.work_item_id == record.id,
            WorkItemStageSchedule.stage == stage,
        )
    )
    downtimes = list(
        await session.scalars(
            select(WorkItemDowntime.version).where(
                WorkItemDowntime.work_item_id == record.id,
                WorkItemDowntime.phase == "planned",
                WorkItemDowntime.deleted_at.is_(None),
            )
        )
    )
    return f"s{window or 0}d{len(downtimes)}.{sum(downtimes)}"


def conflict_key(c: model.Conflict, mine: str, named: dict[uuid.UUID, ChangeWindow]) -> str:
    """A conflict's key: `kind:with:mine:theirs`.

    What it is with (a window, a record, or the maintenance windows in force) and that side's
    version, beside the record's own mark.
    """
    if c.window_id is not None:
        window = named.get(c.window_id)
        target, theirs = str(c.window_id), str(window.version if window else 0)
    elif c.record_id is not None:
        target, theirs = str(c.record_id), str(c.other_version or 0)
    else:  # outside maintenance: against the maintenance windows as they are now
        held = sorted(
            (str(w.id), w.version)
            for w in named.values()
            if w.kind == model.WindowKind.MAINTENANCE.value
        )
        target, theirs = "maintenance", ".".join(f"{i}@{v}" for i, v in held)
    return f"{c.kind.value}:{target}:{mine}:{theirs}"[:300]


async def shown(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> tuple[WorkItem, list[ShownConflict], dict[uuid.UUID, ChangeWindow], frozenset[uuid.UUID]]:
    """A release's conflicts now with their keys and live acks, the windows named and passed."""
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - cycle

    if wtype.code is not WorkItemTypeCode.RELEASE:
        raise NotFound(code="work_item_not_found")
    record = await items.visible_record(session, subject, wtype, record_id)
    found, named = await change_conflicts.conflicts(session, record)
    passed = await change_conflicts.passed_windows(session, record.id)
    mine = await own_mark(session, record)
    keyed = [(c, conflict_key(c, mine, named)) for c in found]
    acks = {
        a.conflict_key: a
        for a in await session.scalars(
            select(WorkItemConflictAck).where(
                WorkItemConflictAck.work_item_id == record.id,
                WorkItemConflictAck.deleted_at.is_(None),
                WorkItemConflictAck.conflict_key.in_([k for _, k in keyed]),
            )
        )
    }
    rows = [
        ShownConflict(c, k, c.blocks and c.window_id not in passed, acks.get(k)) for c, k in keyed
    ]
    return record, rows, named, passed


async def acknowledge(  # noqa: PLR0913 - the conflict, the record's version and why, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    key: str,
    reason: str,
    expected_version: int,
    source: Source,
) -> WorkItem:
    """Acknowledge one warning on a release, with a reason (REQ-REL-041 AC3).

    Needs the right to edit the release and its version (If-Match); the conflict must be there
    now and only warn. A second ack of the same key is the first (nothing changes).
    """
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - cycle

    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    if items.is_closed(record):
        raise Conflict(code=items.RECORD_CLOSED, params={"status": record.status})
    text = " ".join((reason or "").split())
    if not text:
        raise items.field_errors([("reason", "reason_required")])
    if len(text) > REASON_MAX:
        raise items.field_errors([("reason", "value_too_long")])
    _, rows, _, _ = await shown(session, subject, wtype, record_id)
    match = next((r for r in rows if r.key == key), None)
    if match is None:
        raise items.field_errors([("key", NOT_FOUND)])
    if match.blocks:
        raise items.field_errors([("key", BLOCKS)])
    if match.ack is not None:
        return record
    if record.version != expected_version:
        raise Conflict(code="version_conflict", params={"current_version": record.version})
    session.add(
        WorkItemConflictAck(
            tenant_id=record.tenant_id,
            work_item_id=record.id,
            conflict_key=key,
            reason=text,
            acked_by=subject.user_id,
            acked_at=datetime.now(UTC),
        )
    )
    await session.flush()
    what = {
        "kind": match.conflict.kind.value,
        "window_id": str(match.conflict.window_id) if match.conflict.window_id else None,
        "record_id": str(match.conflict.record_id) if match.conflict.record_id else None,
        "record_type": match.conflict.record_type,
    }
    return await items.save_detail_change(
        session,
        record,
        expected_version,
        [Change("conflict_acknowledged", None, what)],
        source=source,
        reason=text,
    )


def acked_people(rows: Sequence[ShownConflict]) -> set[uuid.UUID]:
    """Who acknowledged what is shown (names for the screen)."""
    return {r.ack.acked_by for r in rows if r.ack is not None}
