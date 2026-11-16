"""Work items' mentions port for a person's erasure (ADR-052 S2, D-171 a; lane B's conditions).

Where other people's text about a record names the person being erased: the record's own text,
its conversation, its tasks and its worklogs. The erasure's report lists each place (where and
how often, never the text); an admin may redact the matched words, which become the reserved
marker; the passage is the current text for someone who may read the record and that field.

Phases, one bounded batch each (`MENTION_BATCH` rows), cursor `phase|after`:

- `records`: subject, impact details and free-text custom fields (plain text); description,
  resolution and a problem's analysis and review texts (sanitised HTML). Fields are named as
  the field catalogue names them (`custom.<key>`, the built-in names), so the registry's field
  access backstop matches. On a record the person requested or was raised for, the fields their
  erasure blanks anyway are skipped.
- `conversation`, `tasks`, `worklogs`: every row, the person's own records included (other
  people's replies stay, D1a). Their record types are their own; the passage checks the parent
  record's view right (staff who may view a record read its notes, public and private).

A redaction writes only the new history row (the field named, old and new None, reason
`erasure_redaction`); the registry blanks older history itself. The record's ordinary event
follows, so lists, search and the AI re-embedding see the redacted text. No pre-filter yet: a
plain ordered scan never misses a match.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, ClassVar, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules import metadata
from app.modules.identity_access import (
    MENTION_BATCH,
    Mention,
    MentionBatch,
    MentionMatchKind,
    MentionTerms,
    Subject,
    count_matches,
    count_matches_html,
    redact_html,
    redact_matches,
    register_mentions,
)
from app.modules.metadata import FieldType
from app.modules.work_items.domain import field_access as field_rules
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.events import WorkItemConversationRedacted, WorkItemPartChanged
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemConversation,
    WorkItemTask,
    WorkItemWorklog,
)
from app.modules.work_items.service import work_items as items
from app.shared.events import record_event
from app.shared.history import Change, record_changes

REDACTION_REASON = "erasure_redaction"  # the history reason code (identity_access's)
CONVERSATION = "work_item_conversation"
TASK = "work_item_task"
WORKLOG = "work_item_worklog"
PHASES = ("records", "conversation", "tasks", "worklogs")
# Trashed rows are found too; only someone who may erase people reads or redacts their text (the
# rule lane B applies to every port, #514 review): the trash is no one's day-to-day screen.
ERASE_RIGHT = "people.erase"

# The record's own text, by field: plain text, or sanitised HTML.
PLAIN = (
    "subject",
    "impact_details",
)
HTML = (
    "description",
    "resolution",
    "root_cause",
    "symptoms",
    "workaround",
    "review_summary",
    "review_lessons",
    "review_actions",
)
# What a requester's erasure blanks on their own records (person_data._requested): not searched.
ERASED_WITH_THEM = frozenset({"subject", "description", "impact_details"})


async def _text_keys(
    session: AsyncSession, record_type: str, known: dict[str, frozenset[str]]
) -> frozenset[str]:
    """The record type's free-text custom fields, retired ones too (cached per call)."""
    if record_type not in known:
        found = await metadata.definitions(session, record_type)
        known[record_type] = frozenset(
            k for k, d in found.items() if d.type in {FieldType.TEXT, FieldType.LONG_TEXT}
        )
    return known[record_type]


def _counted(  # noqa: PLR0913 - where the text is, the text, and how to read it
    record_type: str,
    record_id: uuid.UUID,
    field: str,
    text: str | None,
    *,
    html: bool,
    terms: MentionTerms,
) -> list[Mention]:
    found = count_matches_html(text, terms) if html else count_matches(text, terms)
    return [
        Mention(record_type, record_id, field, kind, count) for kind, count in sorted(found.items())
    ]


def _cursor(phase: str, after: uuid.UUID | None) -> str | None:
    """Where the next call goes on: the same phase after a row, else the next phase."""
    if after is not None:
        return f"{phase}|{after}"
    index = PHASES.index(phase)
    return f"{PHASES[index + 1]}|" if index + 1 < len(PHASES) else None


async def _records(
    session: AsyncSession, person_id: uuid.UUID, terms: MentionTerms, after: uuid.UUID | None
) -> tuple[list[Mention], uuid.UUID | None]:
    query = select(WorkItem).order_by(WorkItem.id).limit(MENTION_BATCH)
    if after is not None:
        query = query.where(WorkItem.id > after)
    rows = list((await session.scalars(query)).all())
    known: dict[str, frozenset[str]] = {}
    found: list[Mention] = []
    for record in rows:
        theirs = person_id in {record.requester_id, record.on_behalf_of_id}
        for name in PLAIN + HTML:
            if theirs and name in ERASED_WITH_THEM:
                continue
            found += _counted(
                record.type, record.id, name, getattr(record, name), html=name in HTML, terms=terms
            )
        if not theirs:  # their own records' custom text is blanked with them
            texts = await _text_keys(session, record.type, known)
            for key, value in sorted((record.custom or {}).items()):
                if key in texts and isinstance(value, str):
                    found += _counted(
                        record.type,
                        record.id,
                        f"{field_rules.CUSTOM}{key}",
                        value,
                        html=False,
                        terms=terms,
                    )
    return found, rows[-1].id if len(rows) >= MENTION_BATCH else None


async def _children(  # noqa: PLR0913, PLR0917 - the batch's model, columns and cursor
    session: AsyncSession,
    model: Any,  # noqa: ANN401 - one of the three child models
    record_type: str,
    columns: Sequence[tuple[str, bool]],
    terms: MentionTerms,
    after: uuid.UUID | None,
) -> tuple[list[Mention], uuid.UUID | None]:
    query = select(model).order_by(model.id).limit(MENTION_BATCH)
    if after is not None:
        query = query.where(model.id > after)
    rows = list((await session.scalars(query)).all())
    found = [
        mention
        for row in rows
        for name, html in columns
        for mention in _counted(
            record_type, row.id, name, getattr(row, name), html=html, terms=terms
        )
    ]
    return found, rows[-1].id if len(rows) >= MENTION_BATCH else None


async def _parent(session: AsyncSession, record_id: uuid.UUID) -> WorkItem | None:
    return await session.scalar(select(WorkItem).where(WorkItem.id == record_id).with_for_update())


def _redacted(
    text: str, terms: MentionTerms, kind: MentionMatchKind, marker: str, *, html: bool
) -> tuple[str, int]:
    return (
        redact_html(text, terms, kind, marker)
        if html
        else redact_matches(text, terms, kind, marker)
    )


class WorkItemMentions:
    """Work items' text that names the person: records, conversation, tasks and worklogs."""

    module: ClassVar[str] = "work_items"

    async def find_mentions(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        terms: MentionTerms,
        cursor: str | None,
    ) -> MentionBatch:
        """One batch of one phase, and where to go on."""
        phase, _, raw = (cursor or f"{PHASES[0]}|").partition("|")
        after = uuid.UUID(raw) if raw else None
        if phase == "records":
            found, last = await _records(session, person_id, terms, after)
        elif phase == "conversation":
            found, last = await _children(
                session, WorkItemConversation, CONVERSATION, (("body", True),), terms, after
            )
        elif phase == "tasks":
            found, last = await _children(
                session,
                WorkItemTask,
                TASK,
                (("title", False), ("description", False)),
                terms,
                after,
            )
        elif phase == "worklogs":
            found, last = await _children(
                session, WorkItemWorklog, WORKLOG, (("description", False),), terms, after
            )
        else:
            return MentionBatch(())
        return MentionBatch(tuple(found), _cursor(phase, last))

    async def redact_mention(
        self,
        session: AsyncSession,
        mention: Mention,
        *,
        terms: MentionTerms,
        marker: str,
        now: datetime,
    ) -> bool:
        """The matched occurrences in that one field become the marker; False if none are left."""
        del now
        if mention.record_type == CONVERSATION:
            return await _redact_entry(session, mention, terms, marker)
        if mention.record_type in {TASK, WORKLOG}:
            return await _redact_part(session, mention, terms, marker)
        return await _redact_record(session, mention, terms, marker)

    async def passage(
        self, session: AsyncSession, subject: Subject, mention: Mention
    ) -> str | None:
        """The field's current text, when the subject may read the record and that field."""
        if mention.record_type == CONVERSATION:
            return await _entry_passage(session, subject, mention)
        if mention.record_type in {TASK, WORKLOG}:
            return await _part_passage(session, subject, mention)
        return await _record_passage(session, subject, mention)


async def _readable_child(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID, *, deleted: bool
) -> bool:
    """A child row's text: a trashed row for the erasure right, else the parent's view."""
    if deleted:
        return subject.holds(ERASE_RIGHT)
    return await _may_view(session, subject, record_id)


async def _entry_passage(session: AsyncSession, subject: Subject, mention: Mention) -> str | None:
    entry = await session.get(WorkItemConversation, mention.record_id)
    if entry is None or mention.field != "body":
        return None
    readable = await _readable_child(
        session, subject, entry.work_item_id, deleted=entry.deleted_at is not None
    )
    return entry.body if readable else None


async def _part_passage(session: AsyncSession, subject: Subject, mention: Mention) -> str | None:
    part: WorkItemTask | WorkItemWorklog | None = (
        await session.get(WorkItemTask, mention.record_id)
        if mention.record_type == TASK
        else await session.get(WorkItemWorklog, mention.record_id)
    )
    if part is None:
        return None
    if not await _readable_child(
        session, subject, part.work_item_id, deleted=part.deleted_at is not None
    ):
        return None
    value = getattr(part, mention.field, None)
    return value if isinstance(value, str) else None


async def _may_view(session: AsyncSession, subject: Subject, record_id: uuid.UUID) -> bool:
    """Whether the subject may view the record (its type's view right and scope)."""
    record = await session.get(WorkItem, record_id)
    if record is None:
        return False
    if record.deleted_at is not None:  # a trashed record's parts: the erasure right only
        return subject.holds(ERASE_RIGHT)
    wtype = TYPES.get(WorkItemTypeCode(record.type))
    if wtype is None:
        return False
    try:
        await items.visible_record(session, subject, wtype, record_id)
    except NotFound:
        return False
    return True


async def _record_passage(session: AsyncSession, subject: Subject, mention: Mention) -> str | None:
    """The record's field through the record's own read (its field rules and older gates)."""
    record = await session.get(WorkItem, mention.record_id)
    if record is None or record.type != mention.record_type:
        return None
    if not await _may_read_field(session, subject, record, mention.field):
        return None
    if mention.field.startswith(field_rules.CUSTOM):
        value = (record.custom or {}).get(mention.field[len(field_rules.CUSTOM) :])
    else:
        value = getattr(record, mention.field) if mention.field in PLAIN + HTML else None
    return value if isinstance(value, str) else None


async def _may_read_field(
    session: AsyncSession, subject: Subject, record: WorkItem, field: str
) -> bool:
    """Whether the subject may read that field of the record.

    Trashed: the erasure right (the registry still applies the role field rules). Live: the
    record's own read, and the field neither hidden nor masked for the subject.
    """
    if record.deleted_at is not None:
        return subject.holds(ERASE_RIGHT)
    wtype = TYPES.get(WorkItemTypeCode(record.type))
    if wtype is None:
        return False
    try:
        view = await items.get(session, subject, wtype, record.id)
    except NotFound:
        return False
    return field not in view.hidden | view.masked


async def _redact_record(
    session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str
) -> bool:
    record = await _parent(session, mention.record_id)
    if record is None or record.type != mention.record_type:
        return False
    if mention.field.startswith(field_rules.CUSTOM):
        key = mention.field[len(field_rules.CUSTOM) :]
        value = (record.custom or {}).get(key)
        if not isinstance(value, str):
            return False
        text, replaced = redact_matches(value, terms, mention.match_kind, marker)
        columns: dict[str, Any] = {"custom": {**(record.custom or {}), key: text}}
    elif mention.field in PLAIN + HTML:
        value = getattr(record, mention.field)
        if not isinstance(value, str):
            return False
        text, replaced = _redacted(
            value, terms, mention.match_kind, marker, html=mention.field in HTML
        )
        columns = {mention.field: text}
    else:
        return False
    if not replaced:
        return False
    await items.redact_fields(
        session, record, columns, fields=(mention.field,), reason=REDACTION_REASON
    )
    return True


async def _redact_entry(
    session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str
) -> bool:
    entry = await session.scalar(
        select(WorkItemConversation)
        .where(WorkItemConversation.id == mention.record_id)
        .with_for_update()
    )
    if entry is None or mention.field != "body":
        return False
    text, replaced = redact_html(entry.body, terms, mention.match_kind, marker)
    if not replaced:
        return False
    entry.body = text
    entry.version += 1
    record = await session.get(WorkItem, entry.work_item_id)
    await record_changes(
        session,
        record_type="work_item",
        record_id=entry.work_item_id,
        version=record.version if record is not None else 1,
        kind="updated",
        changes=[Change("conversation", None, None)],
        source="system",
        reason=REDACTION_REASON,
    )
    await record_event(
        session,
        WorkItemConversationRedacted(
            work_item_id=entry.work_item_id,
            entry_id=entry.id,
            kind=entry.kind,
            visibility=entry.visibility,
        ),
        aggregate_id=entry.id,
        aggregate_version=entry.version,
    )
    return True


async def _redact_part(
    session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str
) -> bool:
    part_kind: Literal["task", "worklog"] = "task" if mention.record_type == TASK else "worklog"
    allowed = (
        (
            "title",
            "description",
        )
        if part_kind == "task"
        else ("description",)
    )
    if mention.field not in allowed:
        return False
    part: WorkItemTask | WorkItemWorklog | None = (
        await session.scalar(
            select(WorkItemTask).where(WorkItemTask.id == mention.record_id).with_for_update()
        )
        if part_kind == "task"
        else await session.scalar(
            select(WorkItemWorklog).where(WorkItemWorklog.id == mention.record_id).with_for_update()
        )
    )
    if part is None:
        return False
    value = getattr(part, mention.field)
    if not isinstance(value, str):
        return False
    text, replaced = redact_matches(value, terms, mention.match_kind, marker)
    if not replaced:
        return False
    setattr(part, mention.field, text)
    part.version += 1
    record = await session.get(WorkItem, part.work_item_id)
    await record_changes(
        session,
        record_type="work_item",
        record_id=part.work_item_id,
        version=record.version if record is not None else 1,
        kind="child_changed",
        changes=[Change(f"{part_kind}.{mention.field}", None, None)],
        source="system",
        reason=REDACTION_REASON,
    )
    await record_event(
        session,
        WorkItemPartChanged(
            work_item_id=part.work_item_id,
            part=part_kind,
            part_id=part.id,
            change="changed",
            task_status=part.status if isinstance(part, WorkItemTask) else None,
        ),
        aggregate_id=part.work_item_id,
    )
    return True


PORT = WorkItemMentions()


def register() -> None:
    """Register the port (work_items' import does; idempotent)."""
    register_mentions(PORT)
