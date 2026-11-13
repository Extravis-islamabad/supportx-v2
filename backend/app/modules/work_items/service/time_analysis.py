"""A record's time analysis (WP-046a S3, REQ-INC-071), from its own field history.

The timeline is the record's status, group and technician changes in `field_changes`; each
segment is measured on the record's calendar (its resolution target's, else the tenant's
operating hours, `sla.record_calendar`), so the figures are business hours unless that
calendar counts every hour, and the screen says which (AC2). Anyone who may see the record
sees it: it holds no field the record page does not already show.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import sla
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.time_analysis import (
    TRACKED,
    Step,
    TimeAnalysis,
    analyse,
    initial_values,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.service import catalogue
from app.modules.work_items.service import stages as stage_service
from app.modules.work_items.service import work_items as items
from app.shared.history.history import FieldChange


@dataclass(frozen=True)
class TimeAnalysisView:
    """The analysis, whether it is in business hours, and when it was worked out."""

    analysis: TimeAnalysis
    business_hours: bool
    as_of: datetime


def _text(value: object) -> str | None:
    return None if value is None else str(value)


async def time_analysis(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> TimeAnalysisView:
    """The record's time per status, group and technician, open and paused, until now."""
    record = await items.visible_record(session, subject, wtype, record_id)
    rows = await session.execute(
        select(
            FieldChange.occurred_at, FieldChange.field, FieldChange.old_value, FieldChange.new_value
        )
        .where(
            FieldChange.record_type == items.RECORD_TYPE,
            FieldChange.record_id == record.id,
            FieldChange.field.in_(TRACKED),
        )
        .order_by(FieldChange.occurred_at, FieldChange.id)
    )
    steps = [Step(at, field, _text(old), _text(new)) for at, field, old, new in rows]
    current = {
        "status": record.status,
        "group_id": _text(record.group_id),
        "technician_id": _text(record.technician_id),
    }
    if wtype.stages is not None:
        model = await stage_service.load_model(session, wtype, record.lifecycle_version)

        def category(code: str) -> StatusCategory:
            return model.status(code).category

    else:
        known = {
            s.code: StatusCategory(s.category)
            for s in (await catalogue.load(session, wtype)).statuses
        }

        def category(code: str) -> StatusCategory:
            # A status since removed from the catalogue still counted its time; as open work.
            return known.get(code, StatusCategory.OPEN)

    calendar = await sla.record_calendar(session, record.id)
    now = datetime.now(UTC)
    found = analyse(
        record.created_at,
        now,
        initial_values(current, steps),
        steps,
        category=category,
        measure=calendar.between,
    )
    return TimeAnalysisView(found, not calendar.counts_everything, now)


__all__ = ["TimeAnalysisView", "time_analysis"]
