"""Triggers: run after a change is committed, from its event (WP-029 part 2).

Requirements: REQ-RUL-009, 010, 028; REQ-WF-003 "after".

The consumer `automation__triggers` reads each committed record event through the publishing
module's reader. A rolled-back save never reaches the outbox, and the consumer's idempotency
record means a redelivered event runs nothing twice. Each trigger's actions run in order, each
in its own savepoint: a failed action is logged as failed with its reason and the others still
apply. Every automated change carries its run log entry as the event's cause, so the next
event knows its chain: depth and triggers. The loop guard stops a chain at a clear limit, logs
it, marks the record and tells the owners once.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import AppError, Conflict
from app.modules.automation.domain.rules import (
    MAX_RULES,
    NAME_MAX,
    ActionMode,
    JsonValue,
    RuleState,
    matches,
)
from app.modules.automation.domain.triggers import (
    Cause,
    ChainLink,
    LoopStop,
    TriggerActionKind,
    TriggerEvent,
    before_from,
    check_trigger,
    loop_stop,
)
from app.modules.automation.events import AutomationChanged, AutomationStopped
from app.modules.automation.infra.models import (
    AutomationRun,
    AutomationTrigger,
    TransitionSetting,
)
from app.modules.automation.service.business_rules import DESCRIPTION_MAX, _invalid, _text
from app.modules.automation.service.registry import (
    AutomatedChange,
    RecordEvent,
    RecordType,
    event_reader,
)
from app.modules.automation.service.registry import record_type as registered
from app.shared.db.repository import Repository
from app.shared.events import EventEnvelope, record_event
from app.shared.ids import new_id

TOLD_AGAIN_AFTER = timedelta(hours=1)  # a loop stop is told once per record per hour
# Every work item event a trigger or a transition "after" may react to (the consumer's filter).
TRIGGER_EVENT_TYPES = (
    "work_items.work_item.created",
    "work_items.work_item.updated",
    "work_items.work_item.status_changed",
    "work_items.work_item.assigned",
    "work_items.conversation.added",
)


class TriggerRepository(Repository[AutomationTrigger]):
    """Triggers of the session's tenant."""

    model = AutomationTrigger


# --- definitions ---------------------------------------------------------------------------------


async def check(
    session: AsyncSession, values: Mapping[str, Any]
) -> tuple[dict[str, Any], list[tuple[str, str, Mapping[str, Any]]]]:
    """Cleaned values and their problems, against the trigger's record type (REQ-RUL-029)."""
    kind = registered(str(values.get("record_type", "")))
    if kind is None:
        return {}, [("record_type", "unknown_record_type", {})]
    fields = await kind.fields(session)
    problems: list[tuple[str, str, Mapping[str, Any]]] = []
    name = _text(values.get("name"))
    if name is None:
        problems.append(("name", "required", {}))
    elif len(name) > NAME_MAX:
        problems.append(("name", "value_too_long", {"max_length": NAME_MAX}))
    description = _text(values.get("description"))
    if description is not None and len(description) > DESCRIPTION_MAX:
        problems.append(("description", "value_too_long", {"max_length": DESCRIPTION_MAX}))
    problems += check_trigger(values, fields)
    actions = values.get("actions") or []
    if not problems:
        settable = {a["field"]: a.get("value") for a in actions if a.get("kind") == "set"}
        for field, code in (await kind.check_values(session, settable)).items():
            index = next(i for i, a in enumerate(actions) if a.get("field") == field)
            problems.append((f"actions.{index}.value", code, {"field": field}))
    state = values.get("state", RuleState.DRAFT.value)
    if state not in {s.value for s in RuleState}:
        problems.append(("state", "invalid_choice", {}))
    cleaned = {
        "record_type": kind.code,
        "name": name,
        "description": description,
        "events": sorted(set(values.get("events") or [])),
        "site_id": values.get("site_id"),
        "conditions": values.get("conditions"),
        "actions": [_clean_action(a) for a in actions],
        "fire_on_own_change": bool(values.get("fire_on_own_change", False)),
        "state": state,
    }
    return cleaned, problems


def _clean_action(action: Mapping[str, Any]) -> dict[str, Any]:
    if action.get("kind") == TriggerActionKind.NOTE.value:
        return {"kind": "note", "text": str(action.get("text") or "").strip()}
    return {
        "kind": "set",
        "field": action.get("field"),
        "value": action.get("value"),
        "mode": action.get("mode", ActionMode.FILL_EMPTY.value),
    }


async def list_triggers(session: AsyncSession, record_type: str) -> list[AutomationTrigger]:
    """A type's triggers in their order (drafts and disabled ones included)."""
    rows = await session.scalars(
        select(AutomationTrigger)
        .where(AutomationTrigger.record_type == record_type, AutomationTrigger.deleted_at.is_(None))
        .order_by(AutomationTrigger.position, AutomationTrigger.created_at, AutomationTrigger.id)
    )
    return list(rows)


async def _changed(session: AsyncSession, trigger: AutomationTrigger, change: str) -> None:
    await record_event(
        session,
        AutomationChanged(
            kind="trigger",
            definition_id=trigger.id,
            record_type=trigger.record_type,
            change=change,  # type: ignore[arg-type]  # one of the Literal's values
        ),
        aggregate_id=trigger.id,
        aggregate_version=trigger.version,
    )


async def create_trigger(session: AsyncSession, values: Mapping[str, Any]) -> AutomationTrigger:
    """A new trigger, last in its type's order; a draft unless switched on deliberately."""
    cleaned, problems = await check(session, values)
    if problems:
        raise _invalid(problems)
    existing = await list_triggers(session, cleaned["record_type"])
    if len(existing) >= MAX_RULES:
        raise Conflict(code="too_many_rules", params={"max": MAX_RULES})
    context = session.info[SESSION_TENANT_KEY]
    trigger = await TriggerRepository(session).add(
        AutomationTrigger(
            **cleaned,
            position=max((t.position for t in existing), default=0) + 1,
            owner_id=context.user_id,
        )
    )
    await _changed(session, trigger, "created")
    return trigger


async def update_trigger(
    session: AsyncSession,
    trigger_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
) -> AutomationTrigger:
    """Change a trigger (If-Match). Its record type never changes."""
    current = await TriggerRepository(session).get(trigger_id)
    merged = {
        "record_type": current.record_type,
        "name": current.name,
        "description": current.description,
        "events": current.events,
        "site_id": current.site_id,
        "conditions": current.conditions,
        "actions": current.actions,
        "fire_on_own_change": current.fire_on_own_change,
        "state": current.state,
        **{k: v for k, v in values.items() if k != "record_type"},
    }
    cleaned, problems = await check(session, merged)
    if problems:
        raise _invalid(problems)
    cleaned.pop("record_type")
    trigger = await TriggerRepository(session).update(
        trigger_id, expected_version=expected_version, changes=cleaned
    )
    await _changed(session, trigger, "updated")
    return trigger


async def delete_trigger(
    session: AsyncSession, trigger_id: uuid.UUID, *, expected_version: int
) -> None:
    """Remove a trigger (kept for the history and log entries that name it)."""
    trigger = await TriggerRepository(session).soft_delete(
        trigger_id, expected_version=expected_version
    )
    await _changed(session, trigger, "deleted")


async def reorder_triggers(
    session: AsyncSession, record_type: str, trigger_ids: Sequence[uuid.UUID]
) -> list[AutomationTrigger]:
    """The new order of a type's triggers; the list must name each trigger exactly once."""
    triggers = await list_triggers(session, record_type)
    if sorted(t.id for t in triggers) != sorted(trigger_ids) or len(set(trigger_ids)) != len(
        trigger_ids
    ):
        raise Conflict(code="order_out_of_date")
    by_id = {t.id: t for t in triggers}
    for position, trigger_id in enumerate(trigger_ids, start=1):
        if by_id[trigger_id].position != position:
            by_id[trigger_id].position = position
            by_id[trigger_id].version += 1
    await session.flush()
    context = session.info[SESSION_TENANT_KEY]
    await record_event(
        session,
        AutomationChanged(
            kind="trigger", definition_id=None, record_type=record_type, change="reordered"
        ),
        aggregate_id=context.tenant_id,
    )
    return [by_id[i] for i in trigger_ids]


# --- running -------------------------------------------------------------------------------------


async def _cause(session: AsyncSession, envelope: EventEnvelope) -> Cause:
    """The chain an event belongs to: its cause is a run log entry of an earlier trigger."""
    if envelope.causation_id is None:
        return Cause()
    run = await session.get(AutomationRun, envelope.causation_id)
    if run is None or run.kind != "trigger":
        return Cause()
    detail = run.detail or {}
    chain = tuple(ChainLink(str(c["id"]), str(c["name"])) for c in detail.get("chain", []))
    return Cause(int(detail.get("depth", len(chain))), chain)


async def _recent_changes(session: AsyncSession, record_id: uuid.UUID) -> int:
    since = datetime.now(UTC) - timedelta(minutes=1)
    count = await session.scalar(
        select(func.count())
        .select_from(AutomationRun)
        .where(
            AutomationRun.record_id == record_id,
            AutomationRun.kind == "trigger",
            AutomationRun.outcome.in_(("applied", "partial")),
            AutomationRun.occurred_at >= since,
        )
    )
    return int(count or 0)


def _definitions(
    triggers: Sequence[AutomationTrigger], happened: RecordEvent
) -> list[tuple[ChainLink, AutomationTrigger | None, Mapping[str, Any] | None, list[Any]]]:
    return [
        (ChainLink(str(t.id), t.name), t, t.conditions, list(t.actions))
        for t in triggers
        if happened.event is not None and happened.event.value in t.events
    ]


async def _transition_after(
    session: AsyncSession, happened: RecordEvent
) -> list[tuple[ChainLink, AutomationTrigger | None, Mapping[str, Any] | None, list[Any]]]:
    if happened.event != TriggerEvent.STATUS_CHANGED or happened.action is None:
        return []
    setting = await session.get(
        TransitionSetting, (_tenant(session), happened.record_type, happened.action)
    )
    if setting is None or not setting.after_actions:
        return []
    return [
        (
            ChainLink(f"transition:{happened.action}", happened.action),
            None,
            None,
            list(setting.after_actions),
        )
    ]


def _tenant(session: AsyncSession) -> uuid.UUID:
    return uuid.UUID(str(session.info[SESSION_TENANT_KEY].tenant_id))


async def on_record_event(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: run the triggers (and a move's "after" actions) for one committed event."""
    assert session is not None  # noqa: S101 - transactional consumer
    reader = event_reader(envelope.event_type)
    happened = await reader(session, envelope) if reader is not None else None
    if happened is None:
        return
    kind = registered(happened.record_type)
    if kind is None or kind.facts is None:
        return
    triggers = await session.scalars(
        select(AutomationTrigger)
        .where(
            AutomationTrigger.record_type == happened.record_type,
            AutomationTrigger.state == RuleState.ENABLED.value,
            AutomationTrigger.deleted_at.is_(None),
        )
        .order_by(AutomationTrigger.position, AutomationTrigger.created_at, AutomationTrigger.id)
    )
    candidates = [
        *await _transition_after(session, happened),
        *_definitions(list(triggers), happened),
    ]
    if not candidates:
        return
    cause = await _cause(session, envelope)
    for link, trigger, conditions, actions in candidates:
        after = await kind.facts(session, happened.record_id)
        if after is None:
            return  # deleted meanwhile: nothing to act on
        if (
            trigger is not None
            and trigger.site_id is not None
            and str(after.get("site_id")) != str(trigger.site_id)
        ):
            continue
        before = before_from(after, happened.changed, happened.known_before)
        if not matches(conditions, before, after):
            continue
        stop = loop_stop(
            cause,
            link.trigger_id,
            fire_on_own_change=trigger.fire_on_own_change if trigger is not None else False,
            recent_changes=await _recent_changes(session, happened.record_id),
        )
        if stop == LoopStop.OWN_CHANGE:
            await _log(session, happened, link, "own_change", {"event_id": str(envelope.event_id)})
            continue
        if stop is not None:
            await _stopped(session, happened, cause.then(link), stop)
            return
        await _run(
            session,
            kind=kind,
            happened=happened,
            link=link,
            actions=actions,
            current=after,
            cause=cause.then(link),
            envelope=envelope,
        )


async def _run(  # noqa: PLR0913 - one trigger's run and its context, explicit
    session: AsyncSession,
    *,
    kind: RecordType,
    happened: RecordEvent,
    link: ChainLink,
    actions: Sequence[Mapping[str, Any]],
    current: Mapping[str, JsonValue],
    cause: Cause,
    envelope: EventEnvelope,
) -> None:
    """One trigger's actions in order, each in its own savepoint (REQ-RUL-010)."""
    run_id = new_id()
    is_transition = link.trigger_id.startswith("transition:")
    ref: dict[str, Any] = (
        {"kind": "transition", "action": link.name}
        if is_transition
        else {"kind": "trigger", "trigger_id": link.trigger_id, "trigger": link.name}
    )
    change = AutomatedChange(ref=ref, cause_id=run_id)
    outcomes = [
        await _action(
            session,
            kind=kind,
            record_id=happened.record_id,
            action=a,
            current=current,
            change=change,
        )
        for a in actions
    ]
    outcome = _overall([o["outcome"] for o in outcomes])
    session.add(
        AutomationRun(
            id=run_id,
            record_type=happened.record_type,
            record_id=happened.record_id,
            kind="trigger",
            automation_id=None if is_transition else uuid.UUID(link.trigger_id),
            automation_name=link.name,
            outcome=outcome,
            detail={
                "event_id": str(envelope.event_id),
                "source": "transition" if is_transition else "trigger",
                "depth": cause.depth,
                "chain": [{"id": c.trigger_id, "name": c.name} for c in cause.chain],
                "actions": outcomes,
            },
        )
    )
    await session.flush()


def _overall(outcomes: Sequence[str]) -> str:
    """A run's outcome from its actions': failed, partial, applied or no change."""
    failed, applied = "failed" in outcomes, "applied" in outcomes
    if failed:
        return "partial" if applied else "failed"
    return "applied" if applied else "no_change"


async def _action(  # noqa: PLR0913 - the action and the record it works on, explicit
    session: AsyncSession,
    *,
    kind: RecordType,
    record_id: uuid.UUID,
    action: Mapping[str, Any],
    current: Mapping[str, JsonValue],
    change: AutomatedChange,
) -> dict[str, Any]:
    """Run one action; a failure is rolled back to its savepoint and reported, never raised."""
    shown = {"kind": action.get("kind"), "field": action.get("field")}
    try:
        async with session.begin_nested():
            if action.get("kind") == TriggerActionKind.NOTE.value:
                result = await _note(session, kind, record_id, action, change)
            else:
                result = await _set(
                    session,
                    kind=kind,
                    record_id=record_id,
                    action=action,
                    current=current,
                    change=change,
                )
    except AppError as error:
        result = {"outcome": "failed", "reason": error.code}
    return {**shown, **result}


async def _note(
    session: AsyncSession,
    kind: RecordType,
    record_id: uuid.UUID,
    action: Mapping[str, Any],
    change: AutomatedChange,
) -> dict[str, Any]:
    if kind.add_note is None:
        return {"outcome": "failed", "reason": "not_supported"}
    await kind.add_note(session, record_id, str(action.get("text") or ""), change)
    return {"outcome": "applied"}


async def _set(  # noqa: PLR0913 - the action and the record it works on, explicit
    session: AsyncSession,
    *,
    kind: RecordType,
    record_id: uuid.UUID,
    action: Mapping[str, Any],
    current: Mapping[str, JsonValue],
    change: AutomatedChange,
) -> dict[str, Any]:
    if kind.apply is None:
        return {"outcome": "failed", "reason": "not_supported"}
    field = str(action.get("field"))
    filled = current.get(field) not in (None, "", [])
    if action.get("mode") != ActionMode.OVERWRITE.value and filled:
        return {"outcome": "kept", "reason": "has_value"}
    problems = await kind.check_values(session, {field: action.get("value")})
    if problems:
        return {"outcome": "failed", "reason": problems[field]}
    changed = await kind.apply(session, record_id, {field: action.get("value")}, change)
    return {"outcome": "applied" if changed else "no_change"}


async def _log(
    session: AsyncSession,
    happened: RecordEvent,
    link: ChainLink,
    outcome: str,
    detail: Mapping[str, Any],
) -> None:
    session.add(
        AutomationRun(
            record_type=happened.record_type,
            record_id=happened.record_id,
            kind="trigger",
            automation_id=None
            if link.trigger_id.startswith("transition:")
            else uuid.UUID(link.trigger_id),
            automation_name=link.name,
            outcome=outcome,
            detail=dict(detail),
        )
    )
    await session.flush()


async def _stopped(
    session: AsyncSession, happened: RecordEvent, chain: Cause, stop: LoopStop
) -> None:
    """A cap was hit: log it, naming the triggers, and tell the owners once (REQ-RUL-028)."""
    cap = "chain_depth" if stop == LoopStop.DEPTH else "per_minute"
    names = chain.names()
    told_since = datetime.now(UTC) - TOLD_AGAIN_AFTER
    already = await session.scalar(
        select(func.count())
        .select_from(AutomationRun)
        .where(
            AutomationRun.record_id == happened.record_id,
            AutomationRun.kind == "loop_guard",
            AutomationRun.occurred_at >= told_since,
        )
    )
    session.add(
        AutomationRun(
            record_type=happened.record_type,
            record_id=happened.record_id,
            kind="loop_guard",
            automation_name=", ".join(names)[:200],
            outcome=cap,
            detail={"triggers": names, "depth": chain.depth},
        )
    )
    await session.flush()
    if already:
        return
    ids = sorted(
        {uuid.UUID(c.trigger_id) for c in chain.chain if not c.trigger_id.startswith("transition:")}
    )
    await record_event(
        session,
        AutomationStopped(
            record_type=happened.record_type,
            record_id=happened.record_id,
            cap=cap,  # type: ignore[arg-type]  # one of the Literal's values
            automation_ids=ids,
        ),
        aggregate_id=happened.record_id,
    )
