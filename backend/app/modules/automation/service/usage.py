"""Units and custom fields that automation uses cannot be removed (REQ-RUL-029 AC3).

Removing one is refused while a rule points at it, so a rule never breaks silently: the
organization module counts "automation rules" for a group or site, the metadata module names
the rules that use a custom field.
"""

import uuid

from sqlalchemy import ColumnElement, Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata, organization
from app.modules.automation.infra.models import BusinessRule, RoutingRule, RoutingSettings


def _mentions(value: str) -> tuple[ColumnElement[bool], ColumnElement[bool], ColumnElement[bool]]:
    """Rule JSON (conditions, actions) that names `value` as a whole JSON string."""
    quoted = f'"{value}"'
    return (
        cast(BusinessRule.conditions, Text).contains(quoted),
        cast(BusinessRule.actions, Text).contains(quoted),
        cast(RoutingRule.conditions, Text).contains(quoted),
    )


async def _rules_naming(
    session: AsyncSession, value: str, record_type: str | None = None
) -> list[str]:
    in_conditions, in_actions, in_routing = _mentions(value)
    business_query = select(BusinessRule.name).where(
        BusinessRule.deleted_at.is_(None), or_(in_conditions, in_actions)
    )
    routing_query = select(RoutingRule.name).where(RoutingRule.deleted_at.is_(None), in_routing)
    if record_type is not None:
        business_query = business_query.where(BusinessRule.record_type == record_type)
        routing_query = routing_query.where(RoutingRule.record_type == record_type)
    business = await session.scalars(business_query)
    routing = await session.scalars(routing_query)
    return sorted({*business, *routing})


async def _group_use(session: AsyncSession, group_id: uuid.UUID) -> int:
    routed = await session.scalar(
        select(func.count())
        .select_from(RoutingRule)
        .where(RoutingRule.deleted_at.is_(None), RoutingRule.group_id == group_id)
    )
    fallback = await session.scalar(
        select(func.count())
        .select_from(RoutingSettings)
        .where(RoutingSettings.fallback_group_id == group_id)
    )
    named = await _rules_naming(session, str(group_id))
    return (routed or 0) + (fallback or 0) + len(named)


async def _site_use(session: AsyncSession, site_id: uuid.UUID) -> int:
    scoped = await session.scalar(
        select(func.count())
        .select_from(RoutingRule)
        .where(RoutingRule.deleted_at.is_(None), RoutingRule.site_id == site_id)
    )
    return (scoped or 0) + len(await _rules_naming(session, str(site_id)))


async def _field_use(session: AsyncSession, entity: str, key: str) -> list[str]:
    return await _rules_naming(session, f"custom.{key}", record_type=entity)


def register_usage_checks() -> None:
    """Tell organization and metadata what automation uses (module import)."""
    organization.register_usage("group", "automation_rules", _group_use)
    organization.register_usage("site", "automation_rules", _site_use)
    organization.register_usage("department", "automation_rules", _department_use)
    metadata.register_field_usage("automation", _field_use)


async def _department_use(session: AsyncSession, department_id: uuid.UUID) -> int:
    return len(await _rules_naming(session, str(department_id)))
