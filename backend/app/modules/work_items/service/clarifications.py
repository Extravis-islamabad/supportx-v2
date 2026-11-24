"""Asking for clarification on a request approval (WP-047a S3a; REQ-SR-037).

An approver who may decide a pending approval may ask a question instead. To the requester it
is a public reply (the portal conversation shows it, and it is mailed as any reply is; AC1); to
the request's technician it is a private note that mentions them. The approval shows
"clarification asked", the stage stays pending and its reminders pause (AC3: the sweep skips it,
and the waiting time is added to the approval's `paused_seconds` when it ends).

The addressee's next entry on the request answers it (`on_conversation_added`, a consumer of
the conversation's event): the approver is told and can decide (AC2). A decision ends it too,
as does the approval closing.

Who reads the question and the answer (the coordinator's condition 4): the conversation's own
rules for the entries, and on the approval only the person who asked and the request's staff
(`shown_text`); the events and notices carry IDs and codes only.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules.audit import WORKER as AUDIT_WORKER
from app.modules.audit import RequestFacts
from app.modules.audit import record as record_audit
from app.modules.identity_access import Subject
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.clarifications import (
    Addressee,
    ClarificationEnd,
    question_problems,
)
from app.modules.work_items.domain.conversation import EntryKind, Visibility
from app.modules.work_items.domain.types import SERVICE_REQUEST, WorkItemType
from app.modules.work_items.events import WorkItemConversationAdded
from app.modules.work_items.infra.models import (
    ApprovalClarification,
    WorkItem,
    WorkItemApproval,
    WorkItemConversation,
)
from app.modules.work_items.service import approvals, clarification_rows, conversations
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.followers import RECORD_TYPE
from app.shared.events import ConsumerSpec, EventEnvelope
from app.shared.history import Change, Source, record_changes

ASKED = "service_request.clarification_asked"
ANSWERED = "service_request.clarification_answered"
FIELD = "approval_clarification"  # its history lines on the request


@dataclass(frozen=True)
class Shown:
    """A clarification as a viewer may see it: the texts only for the asker and staff."""

    row: ApprovalClarification
    question: str | None
    answer: str | None


async def _approval(
    session: AsyncSession, record: WorkItem, approval_id: uuid.UUID
) -> WorkItemApproval:
    row: WorkItemApproval | None = await session.scalar(
        select(WorkItemApproval)
        .where(
            WorkItemApproval.id == approval_id,
            WorkItemApproval.work_item_id == record.id,
            WorkItemApproval.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise NotFound(code="approval_not_found")
    return row


async def _history(
    session: AsyncSession, record: WorkItem, said: dict[str, object], source: Source
) -> None:
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_changed",
        changes=[Change(FIELD, None, said)],
        source=source,
        subtype=record.type,
    )


async def ask(  # noqa: PLR0913 - the question and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    approval_id: uuid.UUID,
    *,
    question: str,
    addressee: Addressee,
    expected_version: int,
    source: Source,
    facts: RequestFacts,
) -> approvals.ApprovalView:
    """Ask a question on a pending approval one may decide (AC1); its view after."""
    if wtype.code is not SERVICE_REQUEST.code:
        raise NotFound(code="work_item_not_found")
    record = await approvals.record_of(session, wtype, record_id)
    row = await _approval(session, record, approval_id)
    if row.state != rules.ApprovalState.PENDING:
        raise Conflict(code="approval_closed", params={"state": row.state})
    if row.purpose != rules.ApprovalPurpose.RECORD or not approvals.may_decide(subject, wtype, row):
        raise PermissionDenied(code="not_an_approver")
    if row.version != expected_version:
        raise Conflict(code="approval_changed", params={"version": row.version})
    if problems := question_problems(question):
        raise items.field_errors(problems)
    if await clarification_rows.open_for(session, [row.id]):
        raise Conflict(code="clarification_open")
    to = record.requester_id if addressee is Addressee.REQUESTER else record.technician_id
    if to is None:
        raise items.field_errors([("addressee", "no_technician")])
    if to == subject.user_id:
        raise items.field_errors([("addressee", "is_you")])
    entry = await conversations.add_system_entry(
        session,
        record,
        author_id=subject.user_id,
        kind=EntryKind.REPLY if addressee is Addressee.REQUESTER else EntryKind.NOTE,
        visibility=Visibility.PUBLIC if addressee is Addressee.REQUESTER else Visibility.PRIVATE,
        text=question.strip(),
        mentioned=() if addressee is Addressee.REQUESTER else (to,),
        source=source,
    )
    asked = ApprovalClarification(
        tenant_id=record.tenant_id,
        work_item_id=record.id,
        approval_id=row.id,
        asked_by=subject.user_id,
        addressee=addressee.value,
        addressee_id=to,
        question_entry_id=entry.id,
        asked_at=items.now(),
    )
    session.add(asked)
    row.version += 1  # the approval now shows the question; the next decision sees it
    await session.flush()
    await clarification_rows.event(session, record, asked, "asked")
    said: dict[str, object] = {"action": "asked", "stage": row.stage, "addressee": addressee.value}
    await _history(session, record, said, source)
    await record_audit(
        session,
        action_code=ASKED,
        facts=facts,
        object_type="service_request",
        object_id=str(record.id),
        details={"display_id": record.display_id, **said, "approval_id": str(row.id)},
    )
    return approvals.view_of(subject, wtype, record, row)


def _answers(entry: WorkItemConversation, open_row: ApprovalClarification) -> bool:
    """Whether a new entry answers an open question: its addressee's, after it was asked.

    The requester answers with a public reply (their portal or e-mail reply); the technician with
    any reply or note.
    """
    if entry.created_by != open_row.addressee_id or entry.automatic:
        return False
    if entry.created_at < open_row.asked_at:
        return False
    if open_row.addressee == Addressee.REQUESTER:
        return entry.kind == EntryKind.REPLY and entry.visibility == Visibility.PUBLIC
    return True


async def on_conversation_added(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """A new entry on a request may answer its open questions (AC2); idempotent."""
    if session is None:
        return
    entry = await session.get(WorkItemConversation, uuid.UUID(str(envelope.payload["entry_id"])))
    if entry is None or entry.deleted_at is not None:
        return
    record = await session.get(WorkItem, entry.work_item_id)
    if record is None or record.type != SERVICE_REQUEST.code.value:
        return
    candidates = await session.scalars(
        select(ApprovalClarification)
        .where(
            ApprovalClarification.work_item_id == record.id,
            ApprovalClarification.ended_at.is_(None),
            ApprovalClarification.deleted_at.is_(None),
        )
        .with_for_update()
    )
    for open_row in candidates:
        if open_row.question_entry_id == entry.id or not _answers(entry, open_row):
            continue
        await clarification_rows.end(
            session, record, open_row, ClarificationEnd.ANSWERED, answer_entry_id=entry.id
        )
        await _history(
            session,
            record,
            {"action": "answered", "addressee": open_row.addressee},
            "rule",
        )
        await record_audit(
            session,
            action_code=ANSWERED,
            facts=AUDIT_WORKER,
            object_type="service_request",
            object_id=str(record.id),
            details={"display_id": record.display_id, "approval_id": str(open_row.approval_id)},
        )


async def shown(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record: WorkItem
) -> dict[uuid.UUID, Shown]:
    """Each approval's latest clarification, the texts only for the asker and staff."""
    rows = await clarification_rows.for_record(session, record.id)
    latest: dict[uuid.UUID, ApprovalClarification] = {}
    for row in rows:
        latest[row.approval_id] = row  # oldest first, so the newest wins
    staff = subject.holds(wtype.permission("edit"))
    wanted = {
        e
        for row in latest.values()
        if staff or row.asked_by == subject.user_id
        for e in (row.question_entry_id, row.answer_entry_id)
        if e is not None
    }
    bodies: dict[uuid.UUID, str] = {}
    if wanted:
        found = await session.execute(
            select(WorkItemConversation.id, WorkItemConversation.body).where(
                WorkItemConversation.id.in_(wanted), WorkItemConversation.deleted_at.is_(None)
            )
        )
        bodies = dict(found.tuples().all())
    found_views: dict[uuid.UUID, Shown] = {}
    for approval_id, row in latest.items():
        sees = staff or row.asked_by == subject.user_id
        found_views[approval_id] = Shown(
            row=row,
            question=bodies.get(row.question_entry_id) if sees else None,
            answer=bodies.get(row.answer_entry_id)
            if sees and row.answer_entry_id is not None
            else None,
        )
    return found_views


ANSWERS = ConsumerSpec(
    name="work_items__clarification_answers",
    event_types=(WorkItemConversationAdded.event_type,),
    handler=on_conversation_added,
)


__all__ = [
    "ANSWERED",
    "ANSWERS",
    "ASKED",
    "FIELD",
    "Shown",
    "ask",
    "on_conversation_added",
    "shown",
]
