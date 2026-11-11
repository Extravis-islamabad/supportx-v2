"""How many conflicts each record on the calendar has (WP-058b S2; REQ-REL-041 "on the calendar").

One batch per range, never a query per entry (the coordinator's S2 terms): the windows touching
the range are read once, the others are the records of both types the viewer may see planned in
it, and the pure check (domain/change_windows.conflicts) runs in memory for each record's
planned window. Only what the viewer may see is counted, so a count never reveals a record. The
record pages list the conflicts in full (with the downtimes and the release roles).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.work_items.domain import change_windows as model
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.service import change_conflicts
from app.modules.work_items.service import change_windows as windows

COUNTED = 2000  # entries counted in one range: the calendar's own limit


async def counts(
    session: AsyncSession,
    subject: Subject,
    entries: Sequence[windows.CalendarEntry],
    *,
    start: datetime,
    end: datetime,
) -> dict[uuid.UUID, int]:
    """Each record's conflicts on its planned window, by record ID (records without one: none)."""
    planned = [e for e in entries if e.kind == "window"][:COUNTED]
    if not planned:
        return {}
    rows = {
        r.id: r
        for r in (
            *await change_conflicts.windows_touching(session, start, end),
            *await change_conflicts.maintenance_in_effect(session, start, end),
        )
    }
    zone = await change_conflicts.tenant_zone(session)
    shaped = [change_conflicts.window_of(r, zone) for r in rows.values()]
    others: list[model.Planned] = []
    for code in (WorkItemTypeCode.CHANGE, WorkItemTypeCode.RELEASE):
        seen = await windows.calendar(session, subject, start=start, end=end, wtype=TYPES[code])
        others.extend(
            model.Planned(
                e.record.id,
                e.starts_at,
                e.ends_at,
                e.record.site_id,
                e.record.group_id,
                record_type=e.record.type,
            )
            for e in seen
            if e.kind == "window"
        )
    blocks_outside = await change_conflicts.outside_maintenance_blocks(session)
    found: dict[uuid.UUID, int] = {}
    for e in planned:
        found[e.record.id] = len(
            model.conflicts(
                [(e.starts_at, e.ends_at)],
                site_id=e.record.site_id,
                group_id=e.record.group_id,
                windows=shaped,
                others=others,
                record_id=e.record.id,
                outside_blocks=e.record.type == change_conflicts.CHANGE and blocks_outside,
            )
        )
    return found
