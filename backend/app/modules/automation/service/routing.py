"""Routing: which group a record goes to (WP-029; REQ-ASG-001; D-097).

Ordered routing rules per record type, then the category's suggested group, then the type's
fallback group ("Service desk", created for every tenant). A group a person chose is kept unless
a matching rule says "overwrite".
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound
from app.modules.automation.domain.assignment import RoutingChoice, RoutingRuleDef, route
from app.modules.automation.domain.rules import (
    NAME_MAX,
    JsonValue,
    RuleState,
    check_conditions,
)
from app.modules.automation.events import AutomationChanged
from app.modules.automation.infra.models import AutomationRun, RoutingRule, RoutingSettings
from app.modules.automation.service.business_rules import _invalid
from app.modules.automation.service.registry import record_type as registered
from app.modules.organization import active_unit_ids
from app.shared.db.repository import Repository
from app.shared.events import record_event

MAX_ROUTING_RULES = 200


class RoutingRepository(Repository[RoutingRule]):
    """Routing rules of the session's tenant."""

    model = RoutingRule


async def _check(
    session: AsyncSession, values: Mapping[str, Any]
) -> tuple[dict[str, Any], list[tuple[str, str, Mapping[str, Any]]]]:
    problems: list[tuple[str, str, Mapping[str, Any]]] = []
    kind = registered(str(values.get("record_type", "")))
    if kind is None:
        return {}, [("record_type", "unknown_record_type", {})]
    name = str(values.get("name") or "").strip()
    if not name:
        problems.append(("name", "required", {}))
    elif len(name) > NAME_MAX:
        problems.append(("name", "value_too_long", {"max_length": NAME_MAX}))
    conditions = values.get("conditions")
    if conditions is not None:
        problems += check_conditions(conditions, await kind.fields(session))
    group_id = values.get("group_id")
    if group_id is None:
        problems.append(("group_id", "required", {}))
    elif not await active_unit_ids(session, "group", [group_id]):
        problems.append(("group_id", "group_not_found", {}))
    state = values.get("state", RuleState.DRAFT.value)
    if state not in {s.value for s in RuleState}:
        problems.append(("state", "invalid_choice", {}))
    return {
        "record_type": kind.code,
        "name": name,
        "conditions": conditions,
        "site_id": values.get("site_id"),
        "group_id": group_id,
        "overwrite": bool(values.get("overwrite", False)),
        "state": state,
    }, problems


async def _event(session: AsyncSession, rule: RoutingRule, change: str) -> None:
    await record_event(
        session,
        AutomationChanged(
            kind="routing_rule",
            definition_id=rule.id,
            record_type=rule.record_type,
            change=change,  # type: ignore[arg-type]  # one of the Literal's values
        ),
        aggregate_id=rule.id,
        aggregate_version=rule.version,
    )


async def list_routing(session: AsyncSession, record_type: str) -> list[RoutingRule]:
    """A type's routing rules in their order."""
    rows = await session.scalars(
        select(RoutingRule)
        .where(RoutingRule.record_type == record_type, RoutingRule.deleted_at.is_(None))
        .order_by(RoutingRule.position, RoutingRule.created_at, RoutingRule.id)
    )
    return list(rows)


async def create_routing(session: AsyncSession, values: Mapping[str, Any]) -> RoutingRule:
    """A new routing rule, last in the order."""
    cleaned, problems = await _check(session, values)
    if problems:
        raise _invalid(problems)
    count = await session.scalar(
        select(func.count())
        .select_from(RoutingRule)
        .where(RoutingRule.record_type == cleaned["record_type"], RoutingRule.deleted_at.is_(None))
    )
    if int(count or 0) >= MAX_ROUTING_RULES:
        raise Conflict(code="too_many_rules", params={"max": MAX_ROUTING_RULES})
    last = await session.scalar(
        select(func.max(RoutingRule.position)).where(
            RoutingRule.record_type == cleaned["record_type"]
        )
    )
    rule = await RoutingRepository(session).add(RoutingRule(**cleaned, position=int(last or 0) + 1))
    await _event(session, rule, "created")
    return rule


async def update_routing(
    session: AsyncSession, rule_id: uuid.UUID, values: Mapping[str, Any], *, expected_version: int
) -> RoutingRule:
    """Change a routing rule (If-Match)."""
    current = await RoutingRepository(session).get(rule_id)
    merged = {
        "record_type": current.record_type,
        "name": current.name,
        "conditions": current.conditions,
        "site_id": current.site_id,
        "group_id": current.group_id,
        "overwrite": current.overwrite,
        "state": current.state,
        **{k: v for k, v in values.items() if k != "record_type"},
    }
    cleaned, problems = await _check(session, merged)
    if problems:
        raise _invalid(problems)
    cleaned.pop("record_type")
    rule = await RoutingRepository(session).update(
        rule_id, expected_version=expected_version, changes=cleaned
    )
    await _event(session, rule, "updated")
    return rule


async def delete_routing(
    session: AsyncSession, rule_id: uuid.UUID, *, expected_version: int
) -> None:
    """Remove a routing rule."""
    rule = await RoutingRepository(session).soft_delete(rule_id, expected_version=expected_version)
    await _event(session, rule, "deleted")


async def reorder_routing(
    session: AsyncSession, record_type: str, rule_ids: Sequence[uuid.UUID]
) -> list[RoutingRule]:
    """The new order; the list must name each rule exactly once."""
    rules = await list_routing(session, record_type)
    if sorted(r.id for r in rules) != sorted(rule_ids) or len(set(rule_ids)) != len(rule_ids):
        raise Conflict(code="order_out_of_date")
    by_id = {r.id: r for r in rules}
    for position, rule_id in enumerate(rule_ids, start=1):
        if by_id[rule_id].position != position:
            by_id[rule_id].position = position
            by_id[rule_id].version += 1
    await session.flush()
    context = session.info[SESSION_TENANT_KEY]
    await record_event(
        session,
        AutomationChanged(
            kind="routing_rule", definition_id=None, record_type=record_type, change="reordered"
        ),
        aggregate_id=context.tenant_id,
    )
    return [by_id[i] for i in rule_ids]


async def routing_settings(session: AsyncSession, record_type: str) -> RoutingSettings:
    """A type's routing settings (created with defaults on first need)."""
    found = await session.scalar(
        select(RoutingSettings).where(RoutingSettings.record_type == record_type)
    )
    if found is not None:
        return found
    context = session.info[SESSION_TENANT_KEY]
    await session.execute(
        insert(RoutingSettings)
        .values(tenant_id=context.tenant_id, record_type=record_type)
        .on_conflict_do_nothing()
    )
    created = await session.scalar(
        select(RoutingSettings).where(RoutingSettings.record_type == record_type)
    )
    if created is None:  # pragma: no cover - the insert above or a parallel one made it
        raise NotFound
    return created


async def save_routing_settings(
    session: AsyncSession, record_type: str, values: Mapping[str, Any], *, expected_version: int
) -> RoutingSettings:
    """The fallback group and the category suggestion switch (If-Match)."""
    if registered(record_type) is None:
        raise _invalid([("record_type", "unknown_record_type", {})])
    settings = await routing_settings(session, record_type)
    if settings.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": settings.version},
        )
    fallback = values.get("fallback_group_id", settings.fallback_group_id)
    if fallback is not None and not await active_unit_ids(session, "group", [fallback]):
        raise _invalid([("fallback_group_id", "group_not_found", {})])
    settings.fallback_group_id = fallback
    settings.use_category_group = bool(
        values.get("use_category_group", settings.use_category_group)
    )
    settings.version += 1
    await session.flush()
    await record_event(
        session,
        AutomationChanged(
            kind="routing_settings", definition_id=None, record_type=record_type, change="updated"
        ),
        aggregate_id=settings.tenant_id,
        aggregate_version=settings.version,
    )
    return settings


async def route_record(
    session: AsyncSession,
    record_type: str,
    record: Mapping[str, JsonValue],
    *,
    record_id: uuid.UUID,
) -> RoutingChoice | None:
    """The group for a record (REQ-ASG-001), or None to keep what it has.

    Only active groups are ever chosen; a rule naming a group made inactive since is passed
    over, so the next rule (or the category, or the fallback) decides.
    """
    rows = await session.scalars(
        select(RoutingRule)
        .where(
            RoutingRule.record_type == record_type,
            RoutingRule.state == RuleState.ENABLED.value,
            RoutingRule.deleted_at.is_(None),
        )
        .order_by(RoutingRule.position, RoutingRule.created_at, RoutingRule.id)
    )
    rules = list(rows)
    active = await active_unit_ids(session, "group", [r.group_id for r in rules])
    definitions = [
        RoutingRuleDef(
            id=str(r.id),
            name=r.name,
            conditions=r.conditions,
            group_id=str(r.group_id),
            overwrite=r.overwrite,
            site_id=str(r.site_id) if r.site_id else None,
        )
        for r in rules
        if r.group_id in active
    ]
    settings = await routing_settings(session, record_type)
    category_group = None
    kind = registered(record_type)
    category = record.get("category_id")
    if settings.use_category_group and kind and kind.category_group and isinstance(category, str):
        category_group = await kind.category_group(session, category)
    fallback = settings.fallback_group_id
    if fallback is not None and not await active_unit_ids(session, "group", [fallback]):
        fallback = None
    choice = route(
        definitions,
        record,
        category_group=category_group,
        fallback_group=str(fallback) if fallback else None,
    )
    if choice is not None:
        context = session.info[SESSION_TENANT_KEY]
        session.add(
            AutomationRun(
                tenant_id=context.tenant_id,
                record_type=record_type,
                record_id=record_id,
                kind="routing",
                automation_id=uuid.UUID(choice.rule_id) if choice.rule_id else None,
                automation_name=choice.rule,
                outcome=choice.reason,
                detail={"group_id": choice.group_id},
            )
        )
        await session.flush()
    return choice
