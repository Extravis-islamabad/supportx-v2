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

import re
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import RequestFacts
from app.modules.audit import record as record_audit
from app.modules.identity_access import Subject
from app.modules.organization import offered_languages
from app.modules.work_items.domain.types import SUBJECT_MAX, WorkItemType
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import parts
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.work_items import PermissionHolders
from app.shared.files.ports import OwnerType
from app.shared.files.service.copies import NotCopied, copy_to_records
from app.shared.files.service.core import FileServices
from app.shared.history import Source
from app.shared.labels import label
from app.shared.richtext import image_file_ids, sanitize_html

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
    ATTACHMENTS = "attachments"  # the record's own files, as new files (lane B's copy rules)


@dataclass(frozen=True)
class Made:
    """The copies made, in order, and the original's files that did not come."""

    records: list[WorkItem]
    not_copied: list[NotCopied] = field(default_factory=list)


async def copy_limit(session: AsyncSession, wtype: WorkItemType) -> int:
    """How many copies one request may make (the type's setting comes with its migration)."""
    del session, wtype
    return DEFAULT_COPY_LIMIT


def marked_subject(subject: str, number: int, language: str) -> str:
    """The original's subject marked as copy `number`, within the subject's length."""
    text = label(SUBJECT_MARK, language, n=number, subject=subject)
    return text if len(text) <= SUBJECT_MAX else text[: SUBJECT_MAX - 1] + "…"


async def copy_record(  # noqa: C901, PLR0913 - one step per part chosen; the copy and its context
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    count: int,
    parts_chosen: Collection[RecordCopyPart],
    source: Source,
    holders: PermissionHolders,
    files: FileServices | None = None,
    facts: RequestFacts | None = None,
) -> Made:
    """`count` copies of a record the subject may see (see the module docstring).

    With attachments chosen, `files` and `facts` are needed: the record's own files are copied
    onto every copy in the same transaction (all or nothing), each audited as `file.copied`.
    """
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
    if RecordCopyPart.ATTACHMENTS not in parts_chosen:
        return Made(made)
    if files is None or facts is None:  # pragma: no cover - the route always passes them
        msg = "copying attachments needs the file services and the request facts"
        raise RuntimeError(msg)
    copies = await copy_to_records(
        session,
        files,
        subject,
        owner_type=OwnerType.WORK_ITEM,
        source_id=original.id,
        target_ids=[r.id for r in made],
    )
    for record in made:
        mapping = copies.copied.get(record.id, {})
        for copy_of, copy_id in mapping.items():
            await record_audit(
                session,
                action_code=FILE_COPIED,
                facts=facts,
                object_type="file",
                object_id=str(copy_id),
                details={
                    "copied_from": str(copy_of),
                    "owner_type": OwnerType.WORK_ITEM.value,
                    "owner_id": str(record.id),
                },
            )
    refreshed: list[WorkItem] = []
    for record in made:
        html = _with_copied_images(record.description, copies.copied.get(record.id, {}))
        if html != record.description:
            view = await items.update(
                session,
                subject,
                wtype,
                record.id,
                expected_version=record.version,
                values={"description": html},
                source=source,
            )
            refreshed.append(view.record)
        else:
            refreshed.append(record)
    return Made(refreshed, copies.not_copied)


FILE_COPIED = "file.copied"  # audit: IDs only (lane B)
_IMAGE = r'<img[^>]*\bdata-file-id="{}"[^>]*>'


def _with_copied_images(html: str | None, mapping: dict[uuid.UUID, uuid.UUID]) -> str | None:
    """The copy's description pointing at its own files; an image that did not come is dropped.

    Sanitised again, and never left pointing at the original's files (lane B).
    """
    if not html:
        return html
    for old, new in mapping.items():
        html = html.replace(f'data-file-id="{old}"', f'data-file-id="{new}"')
    own = {str(v) for v in mapping.values()}
    for found in image_file_ids(html):
        if found not in own:
            html = re.sub(_IMAGE.format(re.escape(found)), "", html)
    clean = sanitize_html(html)
    if set(image_file_ids(clean)) - own:  # pragma: no cover - the loop above removed them
        msg = "a copy still names the original's files"
        raise RuntimeError(msg)
    return clean


__all__ = [
    "DEFAULT_COPY_LIMIT",
    "Made",
    "RecordCopyPart",
    "copy_limit",
    "copy_record",
    "marked_subject",
]
