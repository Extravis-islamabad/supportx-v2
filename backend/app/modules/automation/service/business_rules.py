"""Business rules: managed by admins, run inside a record's save (WP-029; REQ-RUL-001..007, 029).

Saving a rule checks it against its record type (fields, operators, values, settable fields);
a draft never runs. Running uses the enabled rules in their order; a value a rule would set that
is no longer valid (a group made inactive since) is skipped and the trace says so, never a
silent change. Every write is one transaction with its event; the routes audit them.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.automation.domain.rules import (
    LANGUAGES,
    MAX_RULES,
    NAME_MAX,
    ActionMode,
    JsonValue,
    Refusal,
    RuleAction,
    RuleDef,
    RuleEvent,
    RuleField,
    RulesOutcome,
    RuleState,
    TraceLine,
    check_actions,
    check_conditions,
    message_for,
    run_rules,
)
from app.modules.automation.events import AutomationChanged
from app.modules.automation.infra.models import AutomationRun, BusinessRule
from app.modules.automation.service.registry import record_type as registered
from app.shared.db.repository import Repository
from app.shared.events import record_event

DESCRIPTION_MAX = 2000
# Every field problem code this module returns (errors.field.<code> labels, checked in CI by
# tests/test_error_labels.py, which reads FIELD_PROBLEMS sets).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        "value_too_long",
        "invalid_choice",
        "invalid_value",
        "invalid_node",
        "invalid_group",
        "filter_too_deep",
        "too_many_conditions",
        "unknown_field",
        "unknown_operator",
        "operator_not_allowed",
        "field_not_settable",
        "field_set_twice",
        "too_many_actions",
        "message_required",
        "unknown_record_type",
        "value_no_longer_valid",
    }
)


class RuleRepository(Repository[BusinessRule]):
    """Business rules of the session's tenant."""

    model = BusinessRule


def _invalid(problems: Sequence[tuple[str, str, Mapping[str, Any]]]) -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(
                field=f"body.{path}",
                code=code,
                message_key=(
                    "errors.field.value_too_long_max"
                    if code == "value_too_long" and "max_length" in params
                    else f"errors.field.{code}"
                ),
                params={k: v for k, v in params.items() if isinstance(v, str | int | float | bool)},
            )
            for path, code, params in problems
        ]
    )


def _text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


async def check_rule(
    session: AsyncSession, values: Mapping[str, Any]
) -> tuple[dict[str, Any], list[tuple[str, str, Mapping[str, Any]]]]:
    """Cleaned values and their problems, against the rule's record type (REQ-RUL-029)."""
    problems: list[tuple[str, str, Mapping[str, Any]]] = []
    kind = registered(str(values.get("record_type", "")))
    if kind is None:
        return {}, [("record_type", "unknown_record_type", {})]
    fields = await kind.fields(session)
    name = _text(values.get("name"))
    if name is None:
        problems.append(("name", "required", {}))
    elif len(name) > NAME_MAX:
        problems.append(("name", "value_too_long", {"max_length": NAME_MAX}))
    description = _text(values.get("description"))
    if description is not None and len(description) > DESCRIPTION_MAX:
        problems.append(("description", "value_too_long", {"max_length": DESCRIPTION_MAX}))
    events = values.get("events") or []
    if not events or not set(events) <= {e.value for e in RuleEvent}:
        problems.append(("events", "invalid_choice", {}))
    conditions = values.get("conditions")
    if conditions is not None:
        problems += check_conditions(conditions, fields)
    actions = values.get("actions")
    problems += check_actions(actions, fields)
    if not problems and isinstance(actions, list):
        settable = {a["field"]: a.get("value") for a in actions if a.get("kind") == "set"}
        for field, code in (await kind.check_values(session, settable)).items():
            index = next(i for i, a in enumerate(actions) if a.get("field") == field)
            problems.append((f"actions.{index}.value", code, {"field": field}))
    cleaned = {
        "record_type": kind.code,
        "name": name,
        "description": description,
        "events": sorted(set(events)),
        "site_id": values.get("site_id"),
        "conditions": conditions,
        "actions": [
            {**a, "mode": a.get("mode", ActionMode.FILL_EMPTY.value)}
            if a.get("kind") == "set"
            else a
            for a in (actions or [])
        ],
        "stop_after": bool(values.get("stop_after", False)),
        "state": values.get("state", RuleState.DRAFT.value),
    }
    if cleaned["state"] not in {s.value for s in RuleState}:
        problems.append(("state", "invalid_choice", {}))
    return cleaned, problems


async def list_rules(session: AsyncSession, record_type: str) -> list[BusinessRule]:
    """A type's rules in their order (drafts and disabled ones included, marked)."""
    rows = await session.scalars(
        select(BusinessRule)
        .where(BusinessRule.record_type == record_type, BusinessRule.deleted_at.is_(None))
        .order_by(BusinessRule.position, BusinessRule.created_at, BusinessRule.id)
    )
    return list(rows)


async def _event(session: AsyncSession, rule: BusinessRule, change: str) -> None:
    await record_event(
        session,
        AutomationChanged(
            kind="business_rule",
            definition_id=rule.id,
            record_type=rule.record_type,
            change=change,  # type: ignore[arg-type]  # one of the Literal's values
        ),
        aggregate_id=rule.id,
        aggregate_version=rule.version,
    )


async def create_rule(session: AsyncSession, values: Mapping[str, Any]) -> BusinessRule:
    """A new rule, last in its type's order; a draft unless switched on deliberately."""
    cleaned, problems = await check_rule(session, values)
    if problems:
        raise _invalid(problems)
    count = await session.scalar(
        select(func.count())
        .select_from(BusinessRule)
        .where(
            BusinessRule.record_type == cleaned["record_type"], BusinessRule.deleted_at.is_(None)
        )
    )
    if int(count or 0) >= MAX_RULES:
        raise Conflict(code="too_many_rules", params={"max": MAX_RULES})
    last = await session.scalar(
        select(func.max(BusinessRule.position)).where(
            BusinessRule.record_type == cleaned["record_type"]
        )
    )
    context = session.info[SESSION_TENANT_KEY]
    rule = await RuleRepository(session).add(
        BusinessRule(**cleaned, position=int(last or 0) + 1, owner_id=context.user_id)
    )
    await _event(session, rule, "created")
    return rule


async def update_rule(
    session: AsyncSession, rule_id: uuid.UUID, values: Mapping[str, Any], *, expected_version: int
) -> BusinessRule:
    """Change a rule (If-Match). Its record type never changes."""
    current = await RuleRepository(session).get(rule_id)
    merged = {
        "record_type": current.record_type,
        "name": current.name,
        "description": current.description,
        "events": current.events,
        "site_id": current.site_id,
        "conditions": current.conditions,
        "actions": current.actions,
        "stop_after": current.stop_after,
        "state": current.state,
        **{k: v for k, v in values.items() if k != "record_type"},
    }
    cleaned, problems = await check_rule(session, merged)
    if problems:
        raise _invalid(problems)
    cleaned.pop("record_type")
    rule = await RuleRepository(session).update(
        rule_id, expected_version=expected_version, changes=cleaned
    )
    await _event(session, rule, "updated")
    return rule


async def delete_rule(session: AsyncSession, rule_id: uuid.UUID, *, expected_version: int) -> None:
    """Remove a rule (kept for the record's history, which names it)."""
    rule = await RuleRepository(session).soft_delete(rule_id, expected_version=expected_version)
    await _event(session, rule, "deleted")


async def reorder_rules(
    session: AsyncSession, record_type: str, rule_ids: Sequence[uuid.UUID]
) -> list[BusinessRule]:
    """The new order of a type's rules; the list must name each rule exactly once."""
    rules = await list_rules(session, record_type)
    if sorted(r.id for r in rules) != sorted(rule_ids) or len(set(rule_ids)) != len(rule_ids):
        raise Conflict(code="order_out_of_date")
    by_id = {r.id: r for r in rules}
    for position, rule_id in enumerate(rule_ids, start=1):
        rule = by_id[rule_id]
        if rule.position != position:
            rule.position = position
            rule.version += 1
    await session.flush()
    context = session.info[SESSION_TENANT_KEY]
    await record_event(
        session,
        AutomationChanged(
            kind="business_rule", definition_id=None, record_type=record_type, change="reordered"
        ),
        aggregate_id=context.tenant_id,
    )
    return [by_id[i] for i in rule_ids]


# --- running -------------------------------------------------------------------------------------


@dataclass
class RulesRun:
    """The outcome of one save's business rules, ready for the record's history and log."""

    outcome: RulesOutcome
    event: RuleEvent


def _definition(rule: BusinessRule) -> RuleDef:
    return RuleDef(
        id=str(rule.id),
        name=rule.name,
        events=frozenset(RuleEvent(e) for e in rule.events),
        conditions=rule.conditions,
        actions=tuple(
            RuleAction(
                kind=a["kind"],
                field=a.get("field"),
                value=a.get("value"),
                mode=ActionMode(a.get("mode", ActionMode.FILL_EMPTY.value)),
                message=a.get("message") or {},
            )
            for a in rule.actions
        ),
        stop_after=rule.stop_after,
        site_id=str(rule.site_id) if rule.site_id else None,
    )


async def run_business_rules(
    session: AsyncSession,
    record_type: str,
    event: RuleEvent,
    before: Mapping[str, JsonValue] | None,
    after: Mapping[str, JsonValue],
) -> RulesRun:
    """Run a type's enabled rules on one save (REQ-RUL-001..006).

    A value no longer valid (a group made inactive since the rule was saved) is not set; the
    trace line says which field and why.
    """
    rows = await session.scalars(
        select(BusinessRule)
        .where(
            BusinessRule.record_type == record_type,
            BusinessRule.state == RuleState.ENABLED.value,
            BusinessRule.deleted_at.is_(None),
        )
        .order_by(BusinessRule.position, BusinessRule.created_at, BusinessRule.id)
    )
    rules = [_definition(r) for r in rows]
    outcome = run_rules(rules, event, before, after) if rules else RulesOutcome()
    kind = registered(record_type)
    if outcome.values and kind is not None:
        problems = await kind.check_values(session, outcome.values)
        for field in problems:
            if field not in outcome.made_by:
                continue
            rule_id, _name = outcome.made_by.pop(field)
            outcome.values.pop(field)
            for line in outcome.trace:
                if line.rule_id == rule_id and field in line.changes:
                    line.changes.pop(field)
                    line.kept.append(f"{field}:value_no_longer_valid")
    return RulesRun(outcome, event)


def refusal_error(refusal: Refusal) -> ValidationFailed:
    """REQ-RUL-004: 422 `rule_refused` with the rule's message in each language.

    The labels pick the reader's own (`errors.rule_refused` is "{{message}}" in English,
    "{{message_ar}}" in Arabic ...); a language the admin left empty falls back to English.
    """
    return ValidationFailed(
        code="rule_refused",
        params={
            "rule": refusal.rule,
            "message": message_for(refusal.message, "en"),
            "message_ar": message_for(refusal.message, "ar"),
            "message_ur": message_for(refusal.message, "ur"),
        },
    )


async def log_trace(
    session: AsyncSession,
    record_type: str,
    record_id: uuid.UUID,
    trace: Sequence[TraceLine],
    *,
    change_id: uuid.UUID | None = None,
) -> None:
    """The run log: one line per rule that did something (kept 30 days, REQ-RUL-006)."""
    context = session.info[SESSION_TENANT_KEY]
    for line in trace:
        if line.outcome == "no_match":
            continue
        session.add(
            AutomationRun(
                tenant_id=context.tenant_id,
                record_type=record_type,
                record_id=record_id,
                kind="business_rule",
                automation_id=uuid.UUID(line.rule_id),
                automation_name=line.rule,
                outcome=line.outcome,
                detail={
                    "changed": sorted(line.changes),
                    "kept": line.kept,
                    "stopped": line.stopped,
                },
                change_id=change_id,
            )
        )
    await session.flush()


def languages() -> tuple[str, ...]:
    """The languages a refusal message may be written in."""
    return LANGUAGES


async def get_rule(session: AsyncSession, rule_id: uuid.UUID) -> BusinessRule:
    """One rule (404 when removed or another tenant's)."""
    try:
        return await RuleRepository(session).get(rule_id)
    except NotFound as exc:
        raise NotFound(code="rule_not_found") from exc


async def record_runs(session: AsyncSession, record_id: uuid.UUID) -> list[AutomationRun]:
    """A record's automation log, newest first (the latest 200)."""
    rows = await session.scalars(
        select(AutomationRun)
        .where(AutomationRun.record_id == record_id)
        .order_by(AutomationRun.occurred_at.desc(), AutomationRun.id.desc())
        .limit(200)
    )
    return list(rows)


async def rule_fields(session: AsyncSession, record_type: str) -> Mapping[str, RuleField]:
    """The fields of a record type (404 `unknown_record_type` for an unregistered one)."""
    kind = registered(record_type)
    if kind is None:
        raise NotFound(code="unknown_record_type")
    return await kind.fields(session)
