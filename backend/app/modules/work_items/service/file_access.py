"""Who may see, attach and remove files on work items, replies and notes (WP-022, ADR-028 item 5).

The files service asks here; it never reads work item tables itself. The rules follow the record:

- an incident's own files: seen by whoever may view the incident (404 otherwise), attached and
  removed by whoever may edit it;
- a reply's or note's files: seen with the entry; a **private** note's files only by people who
  may see private notes (staff: `add_note`). Attaching follows the entry's own rule (`add_note`
  for a private note, `reply` otherwise); removing needs `edit` on the record.

The record's requester or the person it is for, without staff rights to it (mail attachments
from WP-024, the portal from WP-028), sees the record's files and those of its public entries,
and attaches to the record and to their own public replies. Removing, and anything private, stays
with staff (lane B's WP-024 finding, 2026-10-29). Staff rules always come first.

Visibility is evaluated now, never copied onto the file: a note made public takes its files along.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFound, PermissionDenied
from app.modules.identity_access import Subject
from app.modules.work_items.domain.conversation import EntryKind, Visibility
from app.modules.work_items.domain.types import TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem, WorkItemConversation
from app.modules.work_items.service import work_items as items
from app.shared.files.ports import Action, Actor, Owner, OwnerType


def _not_found() -> NotFound:
    return NotFound(code="file_owner_not_found")


def _subject(actor: Actor) -> Subject:
    if not isinstance(actor, Subject):  # the files routes always pass the caller's Subject
        raise _not_found()
    return actor


def _type(code: str) -> WorkItemType:
    try:
        return TYPES[WorkItemTypeCode(code)]
    except (KeyError, ValueError):
        raise _not_found() from None


def _requester_side(subject: Subject, record: WorkItem) -> bool:
    return subject.user_id in {record.requester_id, record.on_behalf_of_id}


def _staff_only() -> PermissionDenied:
    # Seen, but staff work: removing files, or adding to someone else's entry (named, not 404).
    return PermissionDenied(code="file_staff_only")


def sees_private(subject: Subject, wtype: WorkItemType) -> bool:
    """Whether the person may see private notes (staff), and so their files."""
    return subject.holds(wtype.permission("add_note"))


class WorkItemFileAccess:
    """`FileOwnerAccess` for work items and their conversation entries."""

    owner_types = frozenset({OwnerType.WORK_ITEM, OwnerType.CONVERSATION_ENTRY})

    async def check(
        self,
        session: AsyncSession,
        actor: Actor,
        owner_type: OwnerType,
        owner_id: uuid.UUID,
        action: Action,
    ) -> Owner:
        """The owner if allowed; NotFound when it cannot be seen, PermissionDenied otherwise."""
        subject = _subject(actor)
        if owner_type == OwnerType.WORK_ITEM:
            return await self._record(session, subject, owner_id, action)
        return await self._entry(session, subject, owner_id, action)

    @staticmethod
    async def _record(
        session: AsyncSession, subject: Subject, record_id: uuid.UUID, action: Action
    ) -> Owner:
        """The incident's own files: staff by their rights, else its requester's side."""
        record = await session.scalar(
            select(WorkItem).where(WorkItem.id == record_id, WorkItem.deleted_at.is_(None))
        )
        if record is None:
            raise _not_found()
        wtype = _type(record.type)
        try:
            if action == Action.VIEW:
                await items.visible_record(session, subject, wtype, record_id)
            else:
                await items.record_for_action(session, subject, wtype, "edit", record_id)
        except AppError:
            if not _requester_side(subject, record):
                raise
            if action == Action.REMOVE:
                raise _staff_only() from None
        return Owner(OwnerType.WORK_ITEM, record_id, wtype.code.value, record_id)

    async def _entry(
        self, session: AsyncSession, subject: Subject, entry_id: uuid.UUID, action: Action
    ) -> Owner:
        """A reply's or note's files: staff by the entry's rule, else the requester's side."""
        entry = await session.scalar(
            select(WorkItemConversation).where(
                WorkItemConversation.id == entry_id, WorkItemConversation.deleted_at.is_(None)
            )
        )
        if entry is None:
            raise _not_found()
        parent = await session.scalar(
            select(WorkItem).where(WorkItem.id == entry.work_item_id, WorkItem.deleted_at.is_(None))
        )
        if parent is None:
            raise _not_found()
        wtype = _type(parent.type)
        private = entry.visibility == Visibility.PRIVATE.value
        try:
            await items.visible_record(session, subject, wtype, entry.work_item_id)
        except AppError:
            if not _requester_side(subject, parent):
                raise
            return self._requester_entry(subject, wtype, entry, action, private=private)
        if private and not sees_private(subject, wtype):
            raise _not_found()
        if action == Action.ATTACH:
            needed = "add_note" if entry.kind == EntryKind.NOTE.value and private else "reply"
            await items.record_for_action(session, subject, wtype, needed, entry.work_item_id)
        elif action == Action.REMOVE:
            await items.record_for_action(session, subject, wtype, "edit", entry.work_item_id)
        return Owner(
            OwnerType.CONVERSATION_ENTRY,
            entry_id,
            wtype.code.value,
            entry.work_item_id,
            private=private,
        )

    @staticmethod
    def _requester_entry(
        subject: Subject,
        wtype: WorkItemType,
        entry: WorkItemConversation,
        action: Action,
        *,
        private: bool,
    ) -> Owner:
        """The requester's side of an entry: public ones seen, their own public replies added to."""
        if private:
            raise _not_found()
        if action == Action.REMOVE:
            raise _staff_only()
        own_reply = entry.kind == EntryKind.REPLY.value and entry.created_by == subject.user_id
        if action == Action.ATTACH and not own_reply:
            raise _staff_only()
        return Owner(OwnerType.CONVERSATION_ENTRY, entry.id, wtype.code.value, entry.work_item_id)

    async def visible_owners(
        self, session: AsyncSession, actor: Actor, record_type: str, record_id: uuid.UUID
    ) -> set[tuple[OwnerType, uuid.UUID]]:
        """The record and the entries of it the person may see (404 for a hidden record)."""
        subject = _subject(actor)
        wtype = _type(record_type)
        try:
            await items.visible_record(session, subject, wtype, record_id)
        except AppError:
            record = await session.scalar(
                select(WorkItem).where(WorkItem.id == record_id, WorkItem.deleted_at.is_(None))
            )
            if record is None or not _requester_side(subject, record):
                raise
        owners: set[tuple[OwnerType, uuid.UUID]] = {(OwnerType.WORK_ITEM, record_id)}
        query = select(WorkItemConversation.id, WorkItemConversation.visibility).where(
            WorkItemConversation.work_item_id == record_id,
            WorkItemConversation.deleted_at.is_(None),
        )
        staff = sees_private(subject, wtype)
        for entry_id, visibility in await session.execute(query):
            if staff or visibility == Visibility.PUBLIC.value:
                owners.add((OwnerType.CONVERSATION_ENTRY, entry_id))
        return owners


FILE_ACCESS = WorkItemFileAccess()
