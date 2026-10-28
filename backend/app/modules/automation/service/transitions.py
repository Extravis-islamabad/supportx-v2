"""Transition settings (WP-029 part 2; REQ-WF-003, 004).

Per record type and life-cycle action: who may run it (roles, groups, people relative to the
record), when it is offered (conditions), a confirmation text and "after" actions that run once
the move is committed (the trigger consumer runs them). An action without settings behaves as
before: the permission alone decides.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound
from app.modules.automation.domain.rules import JsonValue, check_conditions, matches
from app.modules.automation.domain.triggers import (
    People,
    Relative,
    TransitionRule,
    change_fields,
    check_after_actions,
    check_confirmation,
    may_run,
)
from app.modules.automation.events import AutomationChanged
from app.modules.automation.infra.models import TransitionSetting
from app.modules.automation.service.business_rules import _invalid
from app.modules.automation.service.registry import record_type as registered
from app.shared.events import record_event
from app.shared.history import stale_version

# Why an action is not offered to someone (the UI labels them `action_reason.<code>`).
NOT_OFFERED = "not_offered"  # its conditions do not hold for this record
NOT_FOR_YOU = "not_for_you"  # limited to other roles, groups or people
MAX_LIST = 50


async def list_settings(session: AsyncSession, record_type: str) -> list[TransitionSetting]:
    """A type's transition settings (only actions that have some)."""
    rows = await session.scalars(
        select(TransitionSetting)
        .where(TransitionSetting.record_type == record_type)
        .order_by(TransitionSetting.action)
    )
    return list(rows)


async def setting(session: AsyncSession, record_type: str, action: str) -> TransitionSetting | None:
    """One action's settings, or None (permission only)."""
    rows = await session.scalars(
        select(TransitionSetting).where(
            TransitionSetting.record_type == record_type, TransitionSetting.action == action
        )
    )
    return rows.first()


async def _check(
    session: AsyncSession, record_type: str, action: str, values: Mapping[str, Any]
) -> tuple[dict[str, Any], list[tuple[str, str, Mapping[str, Any]]]]:
    kind = registered(record_type)
    if kind is None:
        return {}, [("record_type", "unknown_record_type", {})]
    if action not in kind.transition_actions:
        raise NotFound(code="transition_not_found", params={"action": action})
    fields = await kind.fields(session)
    problems: list[tuple[str, str, Mapping[str, Any]]] = []
    roles = [str(r) for r in values.get("roles") or []]
    groups = [str(g) for g in values.get("group_ids") or []]
    relatives = [str(r) for r in values.get("relatives") or []]
    for name, items in (("roles", roles), ("group_ids", groups), ("relatives", relatives)):
        if len(items) > MAX_LIST:
            problems.append((name, "too_many_values", {"max": MAX_LIST}))
    if not set(relatives) <= {r.value for r in Relative}:
        problems.append(("relatives", "invalid_choice", {}))
    for index, group in enumerate(groups):
        found = await kind.check_values(session, {"group_id": group})
        if found:
            problems.append((f"group_ids.{index}", found["group_id"], {}))
    conditions = values.get("conditions")
    if conditions is not None:
        problems += check_conditions(conditions, fields)
        problems += [
            ("conditions", "operator_not_allowed", {"field": name})
            for name in change_fields(conditions)
        ]
    problems += check_confirmation(values.get("confirmation"))
    after = values.get("after_actions") or []
    if after:
        problems += [
            (path.replace("actions", "after_actions", 1), code, params)
            for path, code, params in check_after_actions(after, fields)
        ]
    cleaned = {
        "roles": sorted(set(roles)),
        "group_ids": sorted({uuid.UUID(g) for g in groups if not problems}, key=str),
        "relatives": sorted(set(relatives)),
        "conditions": conditions,
        "confirmation": values.get("confirmation"),
        "after_actions": [
            {"kind": "note", "text": str(a.get("text") or "").strip()}
            if a.get("kind") == "note"
            else {**a, "mode": a.get("mode", "fill_empty")}
            for a in after
        ],
    }
    return cleaned, problems


async def save_setting(
    session: AsyncSession,
    record_type: str,
    action: str,
    values: Mapping[str, Any],
    *,
    expected_version: int,
) -> TransitionSetting:
    """Create (version 0) or change one action's settings (If-Match)."""
    cleaned, problems = await _check(session, record_type, action, values)
    if problems:
        raise _invalid(problems)
    current = await setting(session, record_type, action)
    if (current.version if current is not None else 0) != expected_version:
        if current is None:  # reset by someone else: nobody to name
            raise Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": 0},
            )
        raise await stale_version(session, current, expected_version=expected_version)
    if current is None:
        context = session.info[SESSION_TENANT_KEY]
        current = TransitionSetting(
            tenant_id=context.tenant_id,
            record_type=record_type,
            action=action,
            version=1,
            **cleaned,
        )
        session.add(current)
    else:
        for name, value in cleaned.items():
            setattr(current, name, value)
        current.version += 1
    await session.flush()
    await _changed(session, record_type, "updated")
    return current


async def reset_setting(
    session: AsyncSession, record_type: str, action: str, *, expected_version: int
) -> None:
    """Back to "permission only" for this action."""
    current = await setting(session, record_type, action)
    if current is None:
        return
    if current.version != expected_version:
        raise await stale_version(session, current, expected_version=expected_version)
    await session.delete(current)
    await session.flush()
    await _changed(session, record_type, "deleted")


async def _changed(session: AsyncSession, record_type: str, change: str) -> None:
    await record_event(
        session,
        AutomationChanged(
            kind="transition_settings",
            definition_id=None,
            record_type=record_type,
            change=change,  # type: ignore[arg-type]  # one of the Literal's values
        ),
        aggregate_id=record_type,
    )


def rule_of(row: TransitionSetting) -> TransitionRule:
    """The settings as the engine checks them."""
    return TransitionRule(
        roles=frozenset(row.roles),
        group_ids=frozenset(str(g) for g in row.group_ids),
        relatives=frozenset(Relative(r) for r in row.relatives),
        conditions=row.conditions,
    )


@dataclass(frozen=True)
class Audience:
    """Who a transition is limited to (empty lists: anyone permitted)."""

    roles: list[str]
    group_ids: list[str]
    relatives: list[str]


def audience(row: TransitionSetting) -> Audience:
    """The roles, groups and people on the record who may run it, in the admin's order."""
    return Audience(
        roles=list(row.roles),
        group_ids=[str(g) for g in row.group_ids],
        relatives=list(row.relatives),
    )


def refusal(
    row: TransitionSetting | None, person: People, facts: Mapping[str, JsonValue]
) -> str | None:
    """Why `person` may not run the action on this record now (None: they may)."""
    if row is None:
        return None
    rule = rule_of(row)
    if not matches(rule.conditions, None, facts):
        return NOT_OFFERED
    if not may_run(rule, person):
        return NOT_FOR_YOU
    return None
