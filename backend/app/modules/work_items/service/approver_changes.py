"""Adjusting a request's running approval (WP-047a S2b; REQ-SR-042).

A person holding `requests.modify_approvers` on the request (seeded for the service desk
manager; tenant admins hold every right) may, with a reason:

- add an approver to a stage that is open now;
- replace an approver whose approval is still pending: that approval becomes `replaced`, its
  e-mailed link is revoked, and the new person is asked (AC1);
- add a stage after the request's last one (Professional, as stages are);
- remind the open stage's approvers again, at most once every `REMIND_EVERY` and
  `REMINDERS_MAX` times per request.

The coordinator's S2b conditions: never the requester or the person it is for as approver, and
never someone already named on the stage (3); refused once the request is closed, cancelled or
its approval decided (4); reminders limited per request and in its history, and a replaced
approver is never mailed (5: the notice re-reads the approval at send and finds it closed).

Every action is in the record's history with the reason, audited with IDs only, and its
approval events go through the outbox (realtime and notices follow).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules import licensing
from app.modules.audit import RequestFacts
from app.modules.audit import record as record_audit
from app.modules.identity_access import Subject
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain import stage_snapshot
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES, StatusCategory
from app.modules.work_items.domain.service_requests import ApprovalStatus
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.infra.models import WorkItem, WorkItemApproval
from app.modules.work_items.service import request_stages
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.approval_stage import approval_event, requested_for
from app.modules.work_items.service.followers import RECORD_TYPE
from app.shared import action_links
from app.shared.history import Change, FieldChange, Source, record_changes

MODIFY = "modify_approvers"  # `requests.modify_approvers`
MODIFIED = "service_request.approvers_modified"  # the audit code
FIELD = "approvers"  # the history line of an added, replaced or reminded approver
REMINDED_FIELD = "approval_reminder"
REMIND_EVERY = timedelta(minutes=10)
REMINDERS_MAX = 10
REASON_MAX = 500
LINK_OBJECT = "work_item_approval"  # as approvals.LINK_OBJECT (that module imports this one)
MAX_STAGES = 10  # REQ-SR-029 AC4: as the catalog's cap
MAX_APPROVERS = 10  # a stage's people, as the catalog's
# The field problems these actions name (each has its `errors.field.<code>` label).
FIELD_PROBLEMS = frozenset(
    {
        "approver_already_named",
        "approver_is_requester",
        "approver_not_eligible",
        "stage_not_open",
        "too_many_approvers",
        "too_many_stages",
    }
)


class Action(StrEnum):
    """What was done to the running approval (history and audit)."""

    ADDED = "added"
    REPLACED = "replaced"
    STAGE_ADDED = "stage_added"
    REMINDED = "reminded"


def _reason(reason: str) -> str:
    text = (reason or "").strip()
    if not text:
        raise items.field_errors([("reason", "required")])
    if len(text) > REASON_MAX:
        raise items.field_errors([("reason", "value_too_long")], max=REASON_MAX)
    return text


async def _running(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID, expected_version: int
) -> WorkItem:
    """The request, locked, if the subject may adjust it and its approval is running (cond. 4)."""
    found = await items.record_for_action(session, subject, SERVICE_REQUEST, MODIFY, record_id)
    record = await session.scalar(select(WorkItem).where(WorkItem.id == found.id).with_for_update())
    if record is None:  # pragma: no cover - visible a moment ago, and never hard-deleted
        raise NotFound(code="record_not_found")
    if StatusCategory(record.status_category) in FINAL_CATEGORIES:
        raise Conflict(code="record_closed", params={"display_id": record.display_id})
    if record.approval_status != ApprovalStatus.PENDING:
        raise Conflict(code="approval_not_running", params={"display_id": record.display_id})
    if record.version != expected_version:
        raise items.stale(record.version, expected_version)
    return record


async def _rows(session: AsyncSession, record: WorkItem) -> list[WorkItemApproval]:
    """The request's own approvals (never an ad hoc ask), oldest first."""
    return list(
        await session.scalars(
            select(WorkItemApproval)
            .where(
                WorkItemApproval.work_item_id == record.id,
                WorkItemApproval.record_stage.is_(None),
                WorkItemApproval.purpose == rules.ApprovalPurpose.RECORD.value,
                WorkItemApproval.deleted_at.is_(None),
            )
            .order_by(WorkItemApproval.stage, WorkItemApproval.created_at)
        )
    )


def _open_stages(rows: Sequence[WorkItemApproval]) -> set[int]:
    return {r.stage for r in rows if r.state == rules.ApprovalState.PENDING}


async def _check_person(
    session: AsyncSession,
    subject: Subject,
    record: WorkItem,
    person: uuid.UUID,
    named: set[uuid.UUID],
) -> None:
    """Condition 3, lane B's L1 and the S2a eligibility check; errors never echo the ID.

    Whoever adjusts the approval never names themself: holding the right must not let anyone
    approve a request whose approval they changed (lane B's L1).
    """
    if person == subject.user_id:
        raise items.field_errors([("approver_id", "approver_not_eligible")])
    if person in {record.requester_id, requested_for(record)}:
        raise items.field_errors([("approver_id", "approver_is_requester")])
    if person in named:
        raise items.field_errors([("approver_id", "approver_already_named")])
    eligible = await request_stages.eligible(session, {person})
    if not eligible.get(person, False):
        raise items.field_errors([("approver_id", "approver_not_eligible")])


def _named_on(rows: Sequence[WorkItemApproval], stage: int) -> set[uuid.UUID]:
    """Who is already named on a stage (pending or decided; never a replaced one)."""
    return {
        r.approver_id
        for r in rows
        if r.stage == stage
        and r.approver_id is not None
        and r.state != rules.ApprovalState.REPLACED
    }


async def _said(  # noqa: PLR0913 - the record, what was done and why, explicit
    session: AsyncSession,
    record: WorkItem,
    action: Action,
    details: dict[str, Any],
    *,
    reason: str,
    source: Source,
    facts: RequestFacts,
    field: str = FIELD,
) -> None:
    """History (with the reason) and audit (IDs only) for one action."""
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_changed",
        changes=[Change(field, None, {"action": action.value, **details})],
        source=source,
        reason=reason,
        subtype=record.type,
    )
    await record_audit(
        session,
        action_code=MODIFIED,
        facts=facts,
        object_type="service_request",
        object_id=str(record.id),
        details={"display_id": record.display_id, "action": action.value, **details},
    )


def _like(row: WorkItemApproval, person: uuid.UUID) -> WorkItemApproval:
    """A new pending approval on the same stage as `row`, for `person`."""
    return WorkItemApproval(
        tenant_id=row.tenant_id,
        work_item_id=row.work_item_id,
        stage=row.stage,
        rule=row.rule,
        branch=row.branch,
        approver_id=person,
        origin=rules.ApproverOrigin.NAMED.value,
        state=rules.ApprovalState.PENDING.value,
        self_approval=False,  # never the requester (condition 3)
        comments_required=row.comments_required,
    )


async def add_approver(  # noqa: PLR0913 - the request, the person and why, explicit
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    stage: int,
    approver_id: uuid.UUID,
    reason: str,
    expected_version: int,
    source: Source,
    facts: RequestFacts,
) -> WorkItemApproval:
    """Add a person to a stage that is open now; they are asked at once."""
    why = _reason(reason)
    record = await _running(session, subject, record_id, expected_version)
    rows = await _rows(session, record)
    if stage not in _open_stages(rows):
        raise items.field_errors([("stage", "stage_not_open")])
    await _check_person(session, subject, record, approver_id, _named_on(rows, stage))
    template = next(r for r in rows if r.stage == stage)
    row = _like(template, approver_id)
    session.add(row)
    await session.flush()
    await approval_event(session, record, row, "opened")
    await _said(
        session,
        record,
        Action.ADDED,
        {"stage": stage, "approver_id": str(approver_id)},
        reason=why,
        source=source,
        facts=facts,
    )
    return row


async def replace_approver(  # noqa: PLR0913 - the request, the people and why, explicit
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    approval_id: uuid.UUID,
    *,
    approver_id: uuid.UUID,
    reason: str,
    expected_version: int,
    source: Source,
    facts: RequestFacts,
) -> WorkItemApproval:
    """Replace a pending approval's approver (AC1): the old one is withdrawn, the new one asked.

    The old approval becomes `replaced` and its e-mailed link stops working; a reminder or a
    queued notice never reaches them again (condition 5).
    """
    why = _reason(reason)
    record = await _running(session, subject, record_id, expected_version)
    rows = await _rows(session, record)
    old = next((r for r in rows if r.id == approval_id), None)
    if old is None:
        raise NotFound(code="approval_not_found")
    if old.state != rules.ApprovalState.PENDING:
        raise Conflict(code="approval_closed", params={"state": old.state})
    named = _named_on(rows, old.stage) - ({old.approver_id} if old.approver_id else set())
    await _check_person(session, subject, record, approver_id, named)
    old.state = rules.ApprovalState.REPLACED.value
    old.version += 1
    new = _like(old, approver_id)
    session.add(new)
    await session.flush()
    await approval_event(session, record, old, "closed")
    await action_links.revoke_for(session, LINK_OBJECT, old.id)
    await approval_event(session, record, new, "opened")
    details: dict[str, Any] = {"stage": old.stage, "approver_id": str(approver_id)}
    details["replaced_id"] = str(old.approver_id) if old.approver_id else None
    await _said(session, record, Action.REPLACED, details, reason=why, source=source, facts=facts)
    return new


async def add_stage(  # noqa: PLR0913 - the request, the people, the rule and why, explicit
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    approver_ids: Sequence[uuid.UUID],
    rule: rules.LevelRule,
    reason: str,
    expected_version: int,
    source: Source,
    facts: RequestFacts,
) -> int:
    """Add a stage after the request's last one; it opens when the stages before it pass.

    Professional (`catalog`), as stages are. A request on today's single stage gets a snapshot
    whose stage 1 is the stage already open (its people as named), so the stages engine takes
    over from here without asking anyone again.
    """
    why = _reason(reason)
    record = await _running(session, subject, record_id, expected_version)
    await licensing.require_feature(subject.tenant_id, items.REQUEST_STAGES_FEATURE)
    people = list(dict.fromkeys(approver_ids))
    if not people:
        raise items.field_errors([("approver_ids", "required")])
    if len(people) > MAX_APPROVERS:
        raise items.field_errors([("approver_ids", "too_many_approvers")])
    for person in people:
        await _check_person(session, subject, record, person, set())
    rows = await _rows(session, record)
    stages = (
        list(stage_snapshot.from_json(record.approval_stages))
        if record.approval_stages is not None
        else [_first_stage(rows)]
    )
    if len(stages) >= MAX_STAGES:
        raise items.field_errors([("approver_ids", "too_many_stages")], max=MAX_STAGES)
    stages.append(
        stage_snapshot.SnapStage(
            approvers=tuple(stage_snapshot.SnapApprover("person", p) for p in people),
            rule=rule.value,
        )
    )
    record.approval_stages = stage_snapshot.to_json(stages)
    await session.flush()
    number = len(stages)
    await _said(
        session,
        record,
        Action.STAGE_ADDED,
        {"stage": number, "approver_ids": [str(p) for p in people], "rule": rule.value},
        reason=why,
        source=source,
        facts=facts,
    )
    return number


def _first_stage(rows: Sequence[WorkItemApproval]) -> stage_snapshot.SnapStage:
    """Today's single stage as a snapshot stage: the people it is open for, as named."""
    first = [r for r in rows if r.stage == 1]
    people = list(dict.fromkeys(r.approver_id for r in first if r.approver_id is not None))
    return stage_snapshot.SnapStage(
        approvers=tuple(stage_snapshot.SnapApprover("person", p) for p in people),
        rule=first[0].rule or stage_snapshot.DEFAULT_RULE if first else stage_snapshot.DEFAULT_RULE,
        comments_required=any(r.comments_required for r in first),
    )


async def remind(  # noqa: PLR0913 - the request and why, explicit
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    reason: str,
    expected_version: int,
    source: Source,
    facts: RequestFacts,
) -> int:
    """Ask the open stages' named approvers again; how many were reminded.

    At most once every `REMIND_EVERY` and `REMINDERS_MAX` times per request (condition 5). Each
    pending approval's "opened" event is sent again, so the notice goes out with a fresh link
    (D-132); the administrators' approvals name nobody to mail.
    """
    why = _reason(reason)
    record = await _running(session, subject, record_id, expected_version)
    count, last = (
        await session.execute(
            select(func.count(), func.max(FieldChange.occurred_at)).where(
                FieldChange.record_type == RECORD_TYPE,
                FieldChange.record_id == record.id,
                FieldChange.field == REMINDED_FIELD,
            )
        )
    ).one()
    if count >= REMINDERS_MAX:
        raise Conflict(code="too_many_reminders", params={"max": REMINDERS_MAX})
    if last is not None and datetime.now(UTC) - last < REMIND_EVERY:
        raise Conflict(
            code="reminded_recently", params={"minutes": int(REMIND_EVERY.total_seconds() // 60)}
        )
    pending = [
        r
        for r in await _rows(session, record)
        if r.state == rules.ApprovalState.PENDING and r.approver_id is not None
    ]
    for row in pending:
        await approval_event(session, record, row, "opened")
    await _said(
        session,
        record,
        Action.REMINDED,
        {"stages": sorted({r.stage for r in pending}), "count": len(pending)},
        reason=why,
        source=source,
        facts=facts,
        field=REMINDED_FIELD,
    )
    return len(pending)


__all__ = [
    "FIELD_PROBLEMS",
    "MODIFIED",
    "MODIFY",
    "Action",
    "add_approver",
    "add_stage",
    "remind",
    "replace_approver",
]
