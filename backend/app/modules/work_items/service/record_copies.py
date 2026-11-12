"""Copy a record one or more times (WP-046a S5c; REQ-INC-033).

Each copy is a new record made through the same create as any other (the template's rules
apply), with a history entry naming the original and a subject marked as a copy, so the two
are easy to tell apart (BETTER than identical subjects). The technician chooses what comes
with the fields: the tasks, as new open tasks. Conversations, worklogs, history, approvals and
assignment to a person never come (AC2). How many at once is limited per type, 20 by default,
and the refusal says the limit (AC3).

The subject mark is written in the tenant's default language ("Copy 2 of: …"): it is part of
the record's own text from then on, like anything typed, and is edited like it.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.organization import offered_languages
from app.modules.work_items.domain.types import SUBJECT_MAX, WorkItemType
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import parts
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.work_items import PermissionHolders
from app.shared.history import Source
from app.shared.labels import label

DEFAULT_COPY_LIMIT = 20  # REQ-INC-033 AC3's default; per type once its setting exists
SUBJECT_MARK = "work_item.copy_subject"
# The record's own fields a copy takes (never status, dates, assignment to a person, counters).
FIELDS = (
    "subject",
    "description",
    "requester_id",
    "on_behalf_of_id",
    "site_id",
    "department_id",
    "category_id",
    "level",
    "impact",
    "urgency",
    "impact_details",
    "tags",
    "template_id",
)
TASK_FIELDS = ("title", "description", "task_type", "priority", "estimated_minutes")


class RecordCopyPart(StrEnum):
    """What may come with a copy's fields."""

    TASKS = "tasks"


@dataclass(frozen=True)
class Made:
    """The copies made, in order."""

    records: list[WorkItem]


async def copy_limit(session: AsyncSession, wtype: WorkItemType) -> int:
    """How many copies one request may make (the type's setting comes with its migration)."""
    del session, wtype
    return DEFAULT_COPY_LIMIT


def marked_subject(subject: str, number: int, language: str) -> str:
    """The original's subject marked as copy `number`, within the subject's length."""
    text = label(SUBJECT_MARK, language, n=number, subject=subject)
    return text if len(text) <= SUBJECT_MAX else text[: SUBJECT_MAX - 1] + "…"


async def copy_record(  # noqa: PLR0913 - the copy and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    count: int,
    parts_chosen: Collection[RecordCopyPart],
    source: Source,
    holders: PermissionHolders,
) -> Made:
    """`count` copies of a record the subject may see (see the module docstring)."""
    limit = await copy_limit(session, wtype)
    if not 1 <= count <= limit:
        raise items.field_errors([("count", "too_many_copies")], count={"max": limit})
    original = await items.visible_record(session, subject, wtype, record_id)
    _offered, language = await offered_languages(session)
    base = {name: getattr(original, name) for name in FIELDS}
    base = {name: value for name, value in base.items() if value is not None}
    # The group comes only for those who may assign (as when typed); a person never does.
    if original.group_id is not None and subject.holds(wtype.permission("assign")):
        base["group_id"] = original.group_id
    if original.custom:
        base["custom"] = dict(original.custom)
    tasks = (
        await parts.tasks(session, subject, wtype, original.id)
        if RecordCopyPart.TASKS in parts_chosen
        else []
    )
    made: list[WorkItem] = []
    for number in range(1, count + 1):
        values = {**base, "subject": marked_subject(original.subject, number, language)}
        view = await items.create(session, subject, wtype, values, source=source, holders=holders)
        await items.record_copied_from(session, view.record, original, source=source)
        for task in tasks:
            await parts.create_task(
                session,
                subject,
                wtype,
                view.record.id,
                {
                    name: getattr(task, name)
                    for name in TASK_FIELDS
                    if getattr(task, name, None) is not None
                },
                source=source,
            )
        made.append(await items.visible_record(session, subject, wtype, view.record.id))
    return Made(made)


__all__ = [
    "DEFAULT_COPY_LIMIT",
    "Made",
    "RecordCopyPart",
    "copy_limit",
    "copy_record",
    "marked_subject",
]
