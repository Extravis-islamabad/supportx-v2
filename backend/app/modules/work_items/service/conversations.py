"""Conversation, followers, mentions, typing, counters and reply templates (WP-020b).

Each write, in one transaction with the work item's rules (service/work_items.py):

1. the record must be visible (404) and the action's permission must reach it (403): a private
   note needs `add_note` (followers with access have it, D-068); a reply, a public note or making
   a note public needs `reply`;
2. the body is sanitised with the one allow-list (REQ-INC-064) and checked;
3. the entry is saved; a reply is marked `not_sent` while no email channel exists (WP-024), so it
   is never silently lost;
4. the first response is stamped once, by the actions the tenant counts (REQ-INC-065);
5. mentioned people who may see the record follow it; the others are reported back to the author
   and not notified (REQ-INC-063);
6. history on the work item and the outbox event; notifications (WP-023) start from the event.
"""

import html
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFound, PermissionDenied
from app.modules.identity_access import Subject, authorize_stored, user_contacts
from app.modules.work_items.domain.conversation import (
    BODY_MAX,
    RECIPIENTS_MAX,
    TEMPLATE_NAME_MAX,
    EntryKind,
    FollowReason,
    ReplyMode,
    Visibility,
    delivery_for,
    mentioned_ids,
    stamps_first_response,
    unmention,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.events import (
    WorkItemConversationAdded,
    WorkItemConversationVisibilityChanged,
    WorkItemReplyTemplatesChanged,
    WorkItemUpdated,
)
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemConversation,
    WorkItemFollower,
    WorkItemReplyTemplate,
)
from app.modules.work_items.service import followers
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import RESOURCE
from app.modules.work_items.service.catalogue import load as load_catalogue
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.mail import mail_configured
from app.shared.richtext import is_blank, sanitize_html

TIMELINE_MAX = 500
_EMAIL = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]+$")


class Subjects(Protocol):
    """The part of the policy service a mention check needs (identity_access)."""

    async def subject(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession | None = ...
    ) -> Subject:
        """Another user's compiled subject."""
        ...


class ReplyPolicy(Subjects, items.PermissionHolders, Protocol):
    """The policy service as a reply needs it: mentions, and a requester's follow-up record."""


class ConversationRepository(Repository[WorkItemConversation]):
    """Conversation entries of the session's tenant."""

    model = WorkItemConversation


class TemplateRepository(Repository[WorkItemReplyTemplate]):
    """Reply templates of the session's tenant."""

    model = WorkItemReplyTemplate


async def email_channel_configured(session: AsyncSession) -> bool:
    """Whether outgoing mail is set up (WP-024): a reply is then queued, else it waits.

    The notification engine moves the reply on from there (sent, retrying, failed), so the
    timeline never pretends a reply was sent (REQ-INC-059, REQ-INC-060).
    """
    del session
    return mail_configured(get_settings())


# --- reading --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Timeline:
    """A record's conversation as staff see it, oldest first, with who wrote what."""

    record: WorkItem
    entries: list[WorkItemConversation]
    truncated: bool
    names: dict[str, tuple[str, str]] = field(default_factory=dict)


async def timeline(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    kind: EntryKind | None = None,
) -> Timeline:
    """Replies and notes (public and private: staff see both), oldest first.

    At most TIMELINE_MAX entries (the newest ones; `truncated` says so).
    """
    record = await items.visible_record(session, subject, wtype, record_id)
    query = select(WorkItemConversation).where(
        WorkItemConversation.work_item_id == record.id,
        WorkItemConversation.deleted_at.is_(None),
    )
    if kind is not None:
        query = query.where(WorkItemConversation.kind == kind)
    rows = list(
        await session.scalars(
            query.order_by(
                WorkItemConversation.created_at.desc(), WorkItemConversation.id.desc()
            ).limit(TIMELINE_MAX + 1)
        )
    )
    truncated = len(rows) > TIMELINE_MAX
    entries = list(reversed(rows[:TIMELINE_MAX]))
    people = {str(e.created_by) for e in entries if e.created_by is not None}
    people |= {str(u) for e in entries for u in e.mentioned_ids}
    if record.created_by is not None:
        people.add(str(record.created_by))
    people.add(str(record.requester_id))
    return Timeline(record, entries, truncated, await user_contacts(session, sorted(people)))


# --- adding ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Added:
    """A saved entry, and the mentioned people who were not notified (they cannot see it)."""

    entry: WorkItemConversation
    not_notified: list[uuid.UUID]
    names: dict[str, tuple[str, str]]
    # A requester's late reply started a new record following this one (REQ-INC-098).
    follow_up: WorkItem | None = None


def _needed_action(kind: EntryKind, visibility: Visibility) -> str:
    return "add_note" if kind == EntryKind.NOTE and visibility == Visibility.PRIVATE else "reply"


def _addresses(values: Sequence[str]) -> tuple[list[str], list[str]]:
    """(valid, invalid): trimmed, lower-cased, de-duplicated in order."""
    cleaned: list[str] = []
    invalid: list[str] = []
    for raw in values:
        value = raw.strip().lower()
        if not value:
            continue
        if not _EMAIL.fullmatch(value) or len(value) > 254:  # noqa: PLR2004 - RFC 5321 limit
            invalid.append(raw.strip())
        elif value not in cleaned:
            cleaned.append(value)
    return cleaned, invalid


async def _default_to(session: AsyncSession, record: WorkItem) -> list[str]:
    """A plain reply goes to the requester (and the person it was raised for)."""
    people = [str(u) for u in (record.requester_id, record.on_behalf_of_id) if u is not None]
    contacts = await user_contacts(session, people)
    return [contacts[p][1].lower() for p in people if p in contacts and contacts[p][1]]


async def _check_recipients(  # noqa: PLR0913, PLR0917 - the composer's fields, explicit
    session: AsyncSession,
    record: WorkItem,
    kind: EntryKind,
    mode: ReplyMode | None,
    to: Sequence[str],
    cc: Sequence[str],
) -> tuple[dict[str, list[str]] | None, list[tuple[str, str]], dict[str, dict[str, str]]]:
    """(recipients, problems, problem params). Invalid addresses are named (QA C2)."""
    problems: list[tuple[str, str]] = []
    params: dict[str, dict[str, str]] = {}
    if kind == EntryKind.NOTE:
        if to or cc or mode is not None:
            problems.append(("to", "not_allowed_for_notes"))
        return None, problems, params
    to_list, to_bad = _addresses(to)
    cc_list, cc_bad = _addresses(cc)
    for name, bad in (("to", to_bad), ("cc", cc_bad)):
        if bad:
            problems.append((name, "invalid_email"))
            params[name] = {"addresses": ", ".join(bad)}
    if not to_list and mode != ReplyMode.FORWARD:
        to_list = await _default_to(session, record)
    # A wrong address already explains the empty To: no second "required" message (QA C2).
    if not to_list and not to_bad:
        problems.append(("to", "required"))
    if len(to_list) + len(cc_list) > RECIPIENTS_MAX:
        problems.append(("cc", "too_many"))
    return {"to": to_list, "cc": [c for c in cc_list if c not in to_list]}, problems, params


async def _may_see(  # noqa: PLR0913, PLR0917 - who asks, about whom, and where; explicit
    session: AsyncSession,
    policy: Subjects,
    subject: Subject,
    wtype: WorkItemType,
    user_id: uuid.UUID,
    record_id: uuid.UUID,
) -> bool:
    """Whether another person may see the record (mentions and added followers)."""
    other = await policy.subject(subject.tenant_id, user_id, session)
    permission = wtype.permission("view")
    if not other.holds(permission):
        return False
    return bool(
        await authorize_stored(session, other, permission, RESOURCE, WorkItem.id, record_id)
    )


async def _stamp_first_response(
    session: AsyncSession, record: WorkItem, source: Source
) -> WorkItem:
    """Set the first response time once (REQ-INC-065 AC3: later replies do not move it)."""
    audience = items.audience_of(record)
    updated = await items.update_columns(
        session, record, record.version, {"first_responded_at": items.now()}
    )
    await record_changes(
        session,
        record_type=followers.RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=[Change("first_responded_at", None, updated.first_responded_at.isoformat())]
        if updated.first_responded_at
        else [],
        source=source,
    )
    await record_event(
        session,
        WorkItemUpdated(
            work_item_id=updated.id,
            type=updated.type,
            display_id=updated.display_id,
            status=updated.status,
            status_category=updated.status_category,
            changed_fields=["first_responded_at"],
            audience_before=audience,
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return updated


def _entry_code(kind: str, visibility: str) -> str:
    """The history value of an entry: reply, public_note or private_note (labelled in the UI)."""
    return "reply" if kind == EntryKind.REPLY else f"{visibility}_note"


async def add_entry(  # noqa: PLR0913, C901, PLR0912 - the composer's fields and context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    kind: EntryKind,
    visibility: Visibility | None,
    body: str,
    reply_mode: ReplyMode | None,
    to: Sequence[str],
    cc: Sequence[str],
    source: Source,
    policy: ReplyPolicy,
) -> Added:
    """Save a reply or a note (REQ-INC-057/058/061/063/065).

    A public reply by the requester (or the person it is for) moves the record on: resumed when
    it waits on them, reopened within the window, or followed by a new record (WP-020f).
    """
    if kind == EntryKind.REPLY:
        chosen = Visibility.PUBLIC if visibility is None else visibility
        mode: ReplyMode | None = reply_mode or ReplyMode.REPLY
    else:
        chosen = Visibility.PRIVATE if visibility is None else visibility  # D-079: private first
        mode = reply_mode
    record = await items.record_for_action(
        session, subject, wtype, _needed_action(kind, chosen), record_id
    )
    problems: list[tuple[str, str]] = []
    if kind == EntryKind.REPLY and chosen != Visibility.PUBLIC:
        problems.append(("visibility", "invalid_choice"))
    clean = sanitize_html(body)
    if is_blank(clean):
        problems.append(("body", "required"))
    elif len(clean) > BODY_MAX:
        problems.append(("body", "value_too_long"))
    recipients, recipient_problems, params = await _check_recipients(
        session, record, kind, mode, to, cc
    )
    problems += recipient_problems
    if problems:
        raise items.field_errors(problems, **params)
    # Mentions of people who are not users of this tenant become plain words (QA C3).
    claimed = mentioned_ids(clean)
    if claimed:
        known = await user_contacts(session, claimed)
        clean = unmention(clean, [u for u in claimed if u not in known])
    state, reason = delivery_for(kind, email_channel=await email_channel_configured(session))
    mentioned: list[uuid.UUID] = []
    not_notified: list[uuid.UUID] = []
    for raw in mentioned_ids(clean):
        user_id = uuid.UUID(raw)
        if user_id == subject.user_id:
            continue
        if await _may_see(session, policy, subject, wtype, user_id, record.id):
            mentioned.append(user_id)
        else:
            not_notified.append(user_id)
    cat = await load_catalogue(session, wtype)
    first = stamps_first_response(
        kind,
        chosen,
        counted=cat.first_response_on,
        already_stamped=record.first_responded_at is not None,
        by_requester=subject.user_id in {record.requester_id, record.on_behalf_of_id},
    )
    entry = await ConversationRepository(session).add(
        WorkItemConversation(
            work_item_id=record.id,
            kind=kind,
            visibility=chosen,
            reply_mode=mode if kind == EntryKind.REPLY else None,
            body=clean,
            recipients=recipients,
            delivery_state=state,
            delivery_reason=reason,
            first_response=first,
            mentioned_ids=mentioned,
        )
    )
    await record_changes(
        session,
        record_type=followers.RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_added",
        changes=[Change("conversation_entry", None, _entry_code(kind, chosen))],
        source=source,
    )
    if first:
        record = await _stamp_first_response(session, record, source)
    for user_id in mentioned:
        await followers.follow(
            session, record, user_id, reason=FollowReason.MENTIONED, source=source
        )
    await record_event(
        session,
        WorkItemConversationAdded(
            work_item_id=record.id,
            entry_id=entry.id,
            kind=kind,
            visibility=chosen,
            delivery_state=state,
            first_response=first,
            mentioned_ids=mentioned,
        ),
        aggregate_id=entry.id,
        aggregate_version=entry.version,
    )
    follow_up = None
    if kind == EntryKind.REPLY and subject.user_id in {record.requester_id, record.on_behalf_of_id}:
        follow_up = await items.on_requester_reply(
            session, subject, wtype, record, body=clean, source=source, holders=policy
        )
    names = await user_contacts(
        session, [str(u) for u in (*not_notified, subject.user_id, *mentioned)]
    )
    return Added(entry, not_notified, names, follow_up)


async def add_requester_comment(
    session: AsyncSession,
    record: WorkItem,
    body: str,
    *,
    source: Source,
    automatic: bool = False,
) -> WorkItemConversation:
    """The requester's own words as a public reply (a rejected resolution, REQ-INC-096 AC2).

    The caller checked that the signed-in person is the record's requester; this adds no
    permission check of its own and moves nothing (the caller made the move).
    """
    clean = sanitize_html(body)
    state, reason = delivery_for(
        EntryKind.REPLY, email_channel=await email_channel_configured(session)
    )
    entry = await ConversationRepository(session).add(
        WorkItemConversation(
            work_item_id=record.id,
            kind=EntryKind.REPLY,
            visibility=Visibility.PUBLIC,
            reply_mode=ReplyMode.REPLY,
            body=clean,
            recipients=None,
            delivery_state=state,
            delivery_reason=reason,
            first_response=False,
            mentioned_ids=[],
        )
    )
    await record_changes(
        session,
        record_type=followers.RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_added",
        changes=[
            Change("conversation_entry", None, _entry_code(EntryKind.REPLY, Visibility.PUBLIC))
        ],
        source=source,
    )
    await record_event(
        session,
        WorkItemConversationAdded(
            work_item_id=record.id,
            entry_id=entry.id,
            kind=EntryKind.REPLY,
            visibility=Visibility.PUBLIC,
            delivery_state=state,
            first_response=False,
            mentioned_ids=[],
            automatic=automatic,
        ),
        aggregate_id=entry.id,
        aggregate_version=entry.version,
    )
    return entry


async def add_requester_reply(  # noqa: PLR0913 - the reply and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    *,
    body: str,
    source: Source,
    automatic: bool,
    subject: Subject,
    holders: items.PermissionHolders,
) -> WorkItem | None:
    """A reply by the record's requester from outside the console (e-mail WP-024, portal WP-028).

    Only the requester or the person it is for (else 404, as for a record they cannot see; staff
    reply through `add_entry` as themselves). The reply is public and in their name; then the
    record moves as for any requester reply (WP-020f): resumed when waiting on them, reopened
    within the window, or followed by a new record, which is returned so the sender can be told
    its ID. An automatic reply (out-of-office) is recorded and does nothing else.
    """
    if subject.user_id not in {record.requester_id, record.on_behalf_of_id}:
        raise NotFound(code=f"{wtype.code}_not_found")
    await add_requester_comment(session, record, body, source=source, automatic=automatic)
    if automatic:
        return None
    return await items.on_requester_reply(
        session, subject, wtype, record, body=sanitize_html(body), source=source, holders=holders
    )


async def _entry(
    session: AsyncSession, record: WorkItem, entry_id: uuid.UUID
) -> WorkItemConversation:
    entry: WorkItemConversation | None = await session.scalar(
        select(WorkItemConversation).where(
            WorkItemConversation.id == entry_id,
            WorkItemConversation.work_item_id == record.id,
            WorkItemConversation.deleted_at.is_(None),
        )
    )
    if entry is None:
        raise NotFound(code="conversation_entry_not_found")
    return entry


async def change_visibility(  # noqa: PLR0913 - the entry, its version and the context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    entry_id: uuid.UUID,
    *,
    visibility: Visibility,
    expected_version: int,
    source: Source,
) -> WorkItemConversation:
    """Make a note public or private (REQ-INC-061 AC3; the UI asks first). Replies stay public."""
    record = await items.record_for_action(session, subject, wtype, "reply", record_id)
    entry = await _entry(session, record, entry_id)
    if entry.kind != EntryKind.NOTE:
        raise items.field_errors([("visibility", "replies_are_public")])
    if entry.visibility == visibility:
        if entry.version != expected_version:
            raise items.stale(entry.version, expected_version)
        return entry
    before = entry.visibility
    changes: dict[str, Any] = {"visibility": visibility}
    cat = await load_catalogue(session, wtype)
    first = stamps_first_response(
        EntryKind.NOTE,
        visibility,
        counted=cat.first_response_on,
        already_stamped=record.first_responded_at is not None,
        by_requester=entry.created_by in {record.requester_id, record.on_behalf_of_id},
    )
    if first:
        changes["first_response"] = True
    updated = await ConversationRepository(session).update(
        entry.id, expected_version=expected_version, changes=changes
    )
    await record_changes(
        session,
        record_type=followers.RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_changed",
        changes=[Change("note_visibility", before, visibility)],
        source=source,
    )
    if first:
        await _stamp_first_response(session, record, source)
    await record_event(
        session,
        WorkItemConversationVisibilityChanged(
            work_item_id=record.id,
            entry_id=updated.id,
            kind=updated.kind,
            visibility=visibility,
            from_visibility=before,
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return updated


# --- followers ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Followers:
    """Who follows a record, and what the caller may do about it."""

    rows: list[WorkItemFollower]
    names: dict[str, tuple[str, str]]
    may_manage: bool
    is_assignee: bool


async def list_followers(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> Followers:
    """Followers, oldest first, with names (anyone who may see the record may see them)."""
    record = await items.visible_record(session, subject, wtype, record_id)
    rows = await followers.of_record(session, record.id)
    return Followers(
        rows=rows,
        names=await user_contacts(session, [str(r.user_id) for r in rows]),
        may_manage=await items.may(session, subject, wtype, "manage_followers", record.id),
        is_assignee=record.technician_id == subject.user_id,
    )


async def add_follower(  # noqa: PLR0913 - the person and the context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    source: Source,
    policy: Subjects,
) -> Followers:
    """Follow it yourself (needs view), or add someone (manage_followers; they must see it)."""
    if user_id == subject.user_id:
        record = await items.visible_record(session, subject, wtype, record_id)
        await followers.follow(session, record, user_id, reason=FollowReason.SELF, source=source)
    else:
        record = await items.record_for_action(
            session, subject, wtype, "manage_followers", record_id
        )
        if not await _may_see(session, policy, subject, wtype, user_id, record.id):
            # Following never gives access (REQ-INC-063); sharing (REQ-INC-056) comes in V1.
            raise items.field_errors([("user_id", "cannot_see_record")])
        await followers.follow(session, record, user_id, reason=FollowReason.ADDED, source=source)
    return await list_followers(session, subject, wtype, record_id)


async def remove_follower(  # noqa: PLR0913 - the person and the context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    source: Source,
) -> Followers:
    """Unfollow yourself, or remove someone: the assignee or manage_followers (REQ-INC-151 AC4)."""
    record = await items.visible_record(session, subject, wtype, record_id)
    if subject.user_id not in {user_id, record.technician_id}:
        record = await items.record_for_action(
            session, subject, wtype, "manage_followers", record_id
        )
    row = await followers.current(session, record.id, user_id)
    if row is None:
        raise NotFound(code="follower_not_found")
    await followers.unfollow(session, record, row, source=source)
    if user_id == subject.user_id and not await items.may(
        session, subject, wtype, "view", record.id
    ):
        # They stopped following what they could only see by following it: nothing to show.
        return Followers(rows=[], names={}, may_manage=False, is_assignee=False)
    return await list_followers(session, subject, wtype, record_id)


async def mentionable(  # noqa: PLR0913, PLR0917 - search options, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    holders: items.PermissionHolders,
    policy: Subjects,
    *,
    search: str | None,
    limit: int,
) -> list[tuple[uuid.UUID, str, str, bool]]:
    """Staff to mention or add as followers: (id, name, email, may see this record)."""
    record = await items.visible_record(session, subject, wtype, record_id)
    found = await holders.holders(
        session, subject.tenant_id, wtype.permission("view"), search=search, limit=limit
    )
    contacts = await user_contacts(session, [str(u) for u, _ in found])
    result: list[tuple[uuid.UUID, str, str, bool]] = []
    for user_id, name in found:
        sees = await _may_see(session, policy, subject, wtype, user_id, record.id)
        result.append((user_id, name, contacts.get(str(user_id), (name, ""))[1], sees))
    return result


async def check_typing(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> None:
    """Typing signals need the record to be visible (the API then publishes, nothing stored)."""
    await items.visible_record(session, subject, wtype, record_id)


# --- personal counters (REQ-INC-128) -------------------------------------------------------------


async def counters(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, *, zone: tzinfo
) -> list[tuple[str, int, bool]]:
    """(counter, count up to COUNT_CAP, capped), in the fixed order.

    Each counter is also a list view of the same code, so the list it opens has exactly the
    counted rows (REQ-INC-128 AC2).
    """
    predicates = await items.views_for(session, subject, zone=zone)
    base = items.staff_rows(subject, wtype)
    found: list[tuple[str, int, bool]] = []
    for code in items.COUNTERS:
        limited = (
            base.where(predicates[code]).with_only_columns(WorkItem.id).limit(items.COUNT_CAP + 1)
        )
        total = int(await session.scalar(select(func.count()).select_from(limited.subquery())) or 0)
        found.append((code, min(total, items.COUNT_CAP), total > items.COUNT_CAP))
    return found


# --- reply templates ------------------------------------------------------------------------------


async def templates(session: AsyncSession, wtype: WorkItemType) -> list[WorkItemReplyTemplate]:
    """The tenant's reply templates of the type, by name."""
    rows = await session.scalars(
        select(WorkItemReplyTemplate)
        .where(WorkItemReplyTemplate.type == wtype.code, WorkItemReplyTemplate.deleted_at.is_(None))
        .order_by(func.lower(WorkItemReplyTemplate.name), WorkItemReplyTemplate.id)
    )
    return list(rows)


async def _check_template(
    session: AsyncSession,
    wtype: WorkItemType,
    name: str,
    body: str,
    *,
    except_id: uuid.UUID | None = None,
) -> tuple[str, str]:
    problems: list[tuple[str, str]] = []
    clean_name = " ".join(name.split())
    if not clean_name:
        problems.append(("name", "required"))
    elif len(clean_name) > TEMPLATE_NAME_MAX:
        problems.append(("name", "value_too_long"))
    else:
        same = select(WorkItemReplyTemplate.id).where(
            WorkItemReplyTemplate.type == wtype.code,
            WorkItemReplyTemplate.deleted_at.is_(None),
            func.lower(WorkItemReplyTemplate.name) == clean_name.lower(),
        )
        if except_id is not None:
            same = same.where(WorkItemReplyTemplate.id != except_id)
        if await session.scalar(same) is not None:
            problems.append(("name", "duplicate_name"))
    clean_body = sanitize_html(body)
    if is_blank(clean_body):
        problems.append(("body", "required"))
    elif len(clean_body) > BODY_MAX:
        problems.append(("body", "value_too_long"))
    if problems:
        raise items.field_errors(problems)
    return clean_name, clean_body


async def _template_changed(
    session: AsyncSession,
    wtype: WorkItemType,
    row: WorkItemReplyTemplate,
    kind: str,
    source: Source,
) -> None:
    await record_changes(
        session,
        record_type="work_item_reply_template",
        record_id=row.id,
        version=row.version,
        kind="deleted" if kind == "deleted" else ("created" if kind == "created" else "updated"),
        changes=[] if kind == "deleted" else [Change("name", None, row.name)],
        source=source,
    )
    await record_event(
        session,
        WorkItemReplyTemplatesChanged(type=wtype.code, template_id=row.id),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def create_template(
    session: AsyncSession, wtype: WorkItemType, *, name: str, body: str, source: Source
) -> WorkItemReplyTemplate:
    """A new reply template (settings.manage)."""
    clean_name, clean_body = await _check_template(session, wtype, name, body)
    row = await TemplateRepository(session).add(
        WorkItemReplyTemplate(type=wtype.code, name=clean_name, body=clean_body)
    )
    await _template_changed(session, wtype, row, "created", source)
    return row


async def _template(
    session: AsyncSession, wtype: WorkItemType, template_id: uuid.UUID
) -> WorkItemReplyTemplate:
    row: WorkItemReplyTemplate | None = await session.scalar(
        select(WorkItemReplyTemplate).where(
            WorkItemReplyTemplate.id == template_id,
            WorkItemReplyTemplate.type == wtype.code,
            WorkItemReplyTemplate.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFound(code="reply_template_not_found")
    return row


async def update_template(  # noqa: PLR0913 - the template, its version and the change, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    template_id: uuid.UUID,
    *,
    expected_version: int,
    name: str,
    body: str,
    source: Source,
) -> WorkItemReplyTemplate:
    """Rename or rewrite a template (If-Match)."""
    row = await _template(session, wtype, template_id)
    clean_name, clean_body = await _check_template(session, wtype, name, body, except_id=row.id)
    updated = await TemplateRepository(session).update(
        row.id, expected_version=expected_version, changes={"name": clean_name, "body": clean_body}
    )
    await _template_changed(session, wtype, updated, "updated", source)
    return updated


async def delete_template(
    session: AsyncSession,
    wtype: WorkItemType,
    template_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a template (soft delete); text already inserted into replies stays."""
    row = await _template(session, wtype, template_id)
    removed = await TemplateRepository(session).soft_delete(
        row.id, expected_version=expected_version
    )
    await _template_changed(session, wtype, removed, "deleted", source)


def require_view(subject: Subject, wtype: WorkItemType) -> None:
    """Templates are read by anyone who may view the type's records."""
    if not subject.holds(wtype.permission("view")):
        raise PermissionDenied(
            params={"permission": wtype.permission("view"), "reason": "no_permission"}
        )


async def automated_note(  # noqa: PLR0913 - the record, the text and who adds it, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    text: str,
    *,
    ref: Mapping[str, Any],
    cause_id: uuid.UUID,
) -> None:
    """A trigger's private note (REQ-RUL-010): plain text, history names the trigger."""
    record = await items.automation_record(session, wtype, record_id)
    body = sanitize_html(
        "".join(f"<p>{html.escape(line)}</p>" for line in text.splitlines() if line.strip())
    )
    entry = await ConversationRepository(session).add(
        WorkItemConversation(
            work_item_id=record.id,
            kind=EntryKind.NOTE,
            visibility=Visibility.PRIVATE,
            reply_mode=None,
            body=body,
            recipients=None,
            delivery_state=None,
            delivery_reason=None,
            first_response=False,
            mentioned_ids=[],
        )
    )
    await record_changes(
        session,
        record_type=followers.RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_added",
        changes=[
            Change("conversation_entry", None, _entry_code(EntryKind.NOTE, Visibility.PRIVATE))
        ],
        source="rule",
        automation_ref=dict(ref),
    )
    await record_event(
        session,
        WorkItemConversationAdded(
            work_item_id=record.id,
            entry_id=entry.id,
            kind=EntryKind.NOTE,
            visibility=Visibility.PRIVATE,
        ),
        aggregate_id=entry.id,
        aggregate_version=entry.version,
        causation_id=cause_id,
    )
