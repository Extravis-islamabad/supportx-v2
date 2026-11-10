"""Workflow commands on work items (WP-048b, ADR-043 §6; lane A's review).

Automation's `run_command` port, carried out through this module's public services only, as the
workflow's own identity (its compiled Subject and the worker policy, lane B's review), so every
check a person meets applies: permissions, field rights, stage access, reason and closure rules.

- `move`: a life-cycle action by its code (`transition`); on a staged type, a listed status move
  (`move_status`, ADR-041 §8). System statuses are refused by those services as for anyone.
- `update_fields`: the record's own edit (`update`).
- `add_note`: a note, private unless the node says public (`add_entry`); first response is
  stamped by the tenant's `first_response_on` exactly as for a person's note.

History names the workflow: each call runs inside `history.automated(ref)`, scoped to this
command only, so explicit refs still win and nothing outside the call inherits it. Status events
of a workflow's move are `automatic`, like a rule's.

A refusal is returned as the command's result (its stable code), never raised: the node's error
output decides (ADR-043 §6).
"""

import html
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, BadRequest
from app.modules import automation, sla
from app.modules.identity_access import Subject, worker_policy
from app.modules.work_items.domain.conversation import EntryKind, Visibility
from app.modules.work_items.domain.lifecycle import WorkItemAction
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.events import WorkItemWorkflowNotice
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import conversations, parts, workflow_approvals
from app.modules.work_items.service import work_items as items
from app.shared.events import record_event
from app.shared.history import Source, automated

SOURCE: Source = "workflow"
# The interpreter's command kinds (automation.CommandKind values).
MOVE, UPDATE_FIELDS, ADD_NOTE = "move", "update_fields", "add_note"
OPEN_APPROVAL = "open_approval"  # decided later: the result comes with the decision
OPEN_TASKS = "open_tasks"  # done later: the result comes when every task is done
NOTIFY = "notify"  # through the one notification engine (an outbox event), done at once
# The types whose notification source maps a workflow notice (REQ-WF-022): incidents now.
NOTICE_TYPES = frozenset({"incident"})


async def _version(session: AsyncSession, record_id: uuid.UUID) -> int | None:
    return await session.scalar(
        select(WorkItem.version).where(WorkItem.id == record_id, WorkItem.deleted_at.is_(None))
    )


def _note_body(text: Mapping[str, Any]) -> str:
    """The note's English text, else the first language given; plain text, escaped."""
    chosen = text.get("en") or next(iter(text.values()), "")
    return f"<p>{html.escape(str(chosen))}</p>"


def runner(wtype: WorkItemType) -> automation.CommandRunner:
    """The `run_command` of one work item type."""

    async def run(  # noqa: PLR0913, PLR0917 - the port's signature, positional by contract
        session: AsyncSession,
        subject: Subject,
        record_id: uuid.UUID,
        kind: str,
        payload: Mapping[str, Any],
        ref: Mapping[str, Any],
    ) -> automation.CommandResult:
        version = await _version(session, record_id)
        if version is None:
            return automation.CommandResult(ok=False, error="not_found")
        if kind in {OPEN_APPROVAL, OPEN_TASKS, NOTIFY}:
            return await _people_command(
                session, wtype, record_id, kind=kind, payload=payload, ref=ref
            )
        policy = worker_policy()
        try:
            with automated(session, ref):
                handled = await _carry_out(
                    session,
                    subject,
                    wtype,
                    record_id,
                    kind=kind,
                    payload=payload,
                    version=version,
                    policy=policy,
                )
        except AppError as refused:  # the person-like checks said no: the node decides
            return automation.CommandResult(ok=False, error=refused.instance_code)
        if not handled:
            return automation.CommandResult(ok=False, error="command_not_supported")
        return automation.CommandResult(ok=True)

    return run


async def _open_approval(
    session: AsyncSession,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    payload: Mapping[str, Any],
    ref: Mapping[str, Any],
) -> automation.CommandResult:
    """The approval node (REQ-WF-014): one level opened now; the decision continues the node."""
    if wtype.code not in workflow_approvals.APPROVAL_TYPES:
        return automation.CommandResult(ok=False, error="approval_not_offered")
    record = await session.get(WorkItem, record_id)
    if record is None:
        return automation.CommandResult(ok=False, error="not_found")
    try:
        await workflow_approvals.open_for(
            session,
            record,
            instance_id=uuid.UUID(str(ref["instance_id"])),
            command=str(ref["command"]),
            approvers=payload.get("approvers") or {},
            rule=str(payload.get("rule") or "any"),
        )
    except ValueError:  # an approver or a rule the definition should not have held
        return automation.CommandResult(ok=False, error="approval_invalid")
    return automation.CommandResult(ok=True, pending=True)


def _id(value: Any) -> uuid.UUID | None:  # noqa: ANN401 - untrusted JSON
    return uuid.UUID(str(value)) if value else None


async def _people_command(  # noqa: PLR0913 - one command and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    kind: str,
    payload: Mapping[str, Any],
    ref: Mapping[str, Any],
) -> automation.CommandResult:
    """An approval, a checklist or a notice: their results come through the record's own parts."""
    if kind == OPEN_APPROVAL:
        return await _open_approval(session, wtype, record_id, payload, ref)
    if kind == OPEN_TASKS:
        return await _open_tasks(session, record_id, payload, ref)
    return await _notify(session, wtype, record_id, payload, ref)


async def _notify(
    session: AsyncSession,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    payload: Mapping[str, Any],
    ref: Mapping[str, Any],
) -> automation.CommandResult:
    """The notify node (REQ-WF-022): one outbox event the notification engine sends.

    Never mail from here: the engine resolves the audience, checks each person's access to the
    record and their preferences at send time, and logs the delivery (lane A's design).
    """
    if wtype.code.value not in NOTICE_TYPES:
        return automation.CommandResult(ok=False, error="notify_not_offered")
    audience = payload.get("audience") or {}
    await record_event(
        session,
        WorkItemWorkflowNotice(
            record_id=record_id,
            type=wtype.code.value,
            instance_id=uuid.UUID(str(ref["instance_id"])),
            audience={
                key: [str(v) for v in audience.get(key, [])]
                for key in ("relatives", "user_ids", "group_ids")
            },
            subject={str(k): str(v) for k, v in dict(payload.get("subject") or {}).items()},
            body={str(k): str(v) for k, v in dict(payload.get("body") or {}).items()},
        ),
        aggregate_id=record_id,
    )
    return automation.CommandResult(ok=True)


async def _open_tasks(
    session: AsyncSession,
    record_id: uuid.UUID,
    payload: Mapping[str, Any],
    ref: Mapping[str, Any],
) -> automation.CommandResult:
    """The task node (REQ-WF-015): its checklist opened now; all done continues the node."""
    record = await session.get(WorkItem, record_id)
    if record is None:
        return automation.CommandResult(ok=False, error="not_found")
    due_days = payload.get("due_days")
    due_at = None
    if isinstance(due_days, int) and not isinstance(due_days, bool):
        # Working days on the record's own calendar (its resolution target's, else the
        # tenant's operating hours), as the record's other business-day rules count.
        calendar = await sla.record_calendar(session, record_id)
        due_at = calendar.add_working_days(datetime.now(UTC), due_days)
    try:
        await parts.open_workflow_tasks(
            session,
            record,
            instance_id=uuid.UUID(str(ref["instance_id"])),
            command=str(ref["command"]),
            titles=[dict(t) for t in payload.get("titles") or []],
            owner_id=_id(payload.get("owner_user_id")),
            group_id=_id(payload.get("owner_group_id")),
            due_at=due_at,
        )
    except ValueError:  # an owner id the definition should not have held
        return automation.CommandResult(ok=False, error="tasks_invalid")
    return automation.CommandResult(ok=True, pending=True)


async def _carry_out(  # noqa: PLR0913 - the command and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    kind: str,
    payload: Mapping[str, Any],
    version: int,
    policy: Any,  # noqa: ANN401 - identity's worker policy (holders and subjects)
) -> bool:
    """Carry out one command; False: not a command this module knows."""
    if kind == MOVE:
        raw = payload.get("action")
        if not isinstance(raw, str) or raw == "":
            # A move with no action is the definition's fault: a clear refusal, never "None"
            # sent on as a target (lane A's review).
            raise BadRequest(code="workflow_move_without_action")
        action = raw
        if action in {a.value for a in WorkItemAction}:
            await items.transition(
                session,
                subject,
                wtype,
                record_id,
                WorkItemAction(action),
                expected_version=version,
                reason_code=None,
                reason_text=None,
                source=SOURCE,
                holders=policy,
            )
        else:  # a staged type's listed status move (ADR-041 §8)
            await items.move_status(
                session,
                subject,
                wtype,
                record_id,
                target=action,
                expected_version=version,
                reason_code=None,
                reason_text=None,
                source=SOURCE,
            )
    elif kind == UPDATE_FIELDS:
        await items.update(
            session,
            subject,
            wtype,
            record_id,
            expected_version=version,
            values=dict(payload.get("values", {})),
            source=SOURCE,
        )
    elif kind == ADD_NOTE:
        await conversations.add_entry(
            session,
            subject,
            wtype,
            record_id,
            kind=EntryKind.NOTE,
            visibility=Visibility.PRIVATE if payload.get("private", True) else Visibility.PUBLIC,
            body=_note_body(dict(payload.get("text", {}))),
            reply_mode=None,
            to=(),
            cc=(),
            source=SOURCE,
            policy=policy,
        )
    else:
        return False
    return True
