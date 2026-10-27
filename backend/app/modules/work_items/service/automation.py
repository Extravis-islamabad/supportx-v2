"""Work items on the automation engine (WP-029; ADR-035).

Registers each work item type with the automation module: the fields business rules may test
and set (standard and custom fields, plus the requester's attributes), how a value a rule would
set is checked now, and a category's suggested group for routing. Also builds the snapshot the
engine sees, and the members a group's auto-assignment may choose from (never outside the group,
REQ-ASG-002 AC5).
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.automation import (
    FieldKind,
    Member,
    RecordType,
    RuleEvent,
    RuleField,
    TraceLine,
    auto_assign,
    refusal_error,
    register_record_type,
    route_record,
    run_business_rules,
)
from app.modules.identity_access import person_placement, user_names
from app.modules.organization import active_unit_ids, existing_departments, users_in_groups
from app.modules.work_items.domain.classification import Scale
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.types import TYPES, Channel, WorkItemType
from app.modules.work_items.infra.models import WorkItem, WorkItemCategory
from app.modules.work_items.service import catalogue as config

_REFERENCES = (
    "requester_id",
    "on_behalf_of_id",
    "site_id",
    "department_id",
    "group_id",
    "technician_id",
    "category_id",
    "template_id",
)
# Fields a business rule may set (REQ-RUL-003). Status moves through life-cycle actions only.
_SETTABLE = frozenset(
    {
        "group_id",
        "technician_id",
        "category_id",
        "priority",
        "impact",
        "urgency",
        "level",
        "site_id",
        "department_id",
        "tags",
    }
)
_CUSTOM_KINDS: Mapping[str, FieldKind] = {
    "text": FieldKind.TEXT,
    "long_text": FieldKind.TEXT,
    "email": FieldKind.TEXT,
    "phone": FieldKind.TEXT,
    "url": FieldKind.TEXT,
    "integer": FieldKind.NUMBER,
    "decimal": FieldKind.NUMBER,
    "currency": FieldKind.NUMBER,
    "date": FieldKind.DATETIME,
    "datetime": FieldKind.DATETIME,
    "choice": FieldKind.CODE,
    "multi_choice": FieldKind.CODES,
    "yes_no": FieldKind.BOOLEAN,
    "person": FieldKind.REFERENCE,
}


def _fields_for(
    wtype: WorkItemType,
) -> Callable[[AsyncSession], Awaitable[Mapping[str, RuleField]]]:
    async def fields(session: AsyncSession) -> Mapping[str, RuleField]:
        cat = await config.load(session, wtype)
        codes = {
            scale: frozenset(v.code for v in cat.scales if v.scale == scale)
            for scale in (Scale.IMPACT.value, Scale.URGENCY.value, Scale.PRIORITY.value)
        }
        found: dict[str, RuleField] = {
            "subject": RuleField(FieldKind.TEXT),
            "description": RuleField(FieldKind.TEXT),
            "channel": RuleField(FieldKind.CODE, frozenset(c.value for c in Channel)),
            "status": RuleField(FieldKind.CODE, frozenset(s.code for s in cat.statuses)),
            "status_category": RuleField(
                FieldKind.CODE, frozenset(c.value for c in StatusCategory)
            ),
            "impact": RuleField(FieldKind.CODE, codes["impact"], settable=True),
            "urgency": RuleField(FieldKind.CODE, codes["urgency"], settable=True),
            "priority": RuleField(FieldKind.CODE, codes["priority"], settable=True),
            "level": RuleField(
                FieldKind.CODE,
                frozenset(r.code for r in cat.reasons if r.list == "level"),
                settable=True,
            ),
            "tags": RuleField(FieldKind.CODES, settable=True),
            "requester.vip": RuleField(FieldKind.BOOLEAN, derived=True),
            "requester.site_id": RuleField(FieldKind.REFERENCE, derived=True),
            "requester.department_id": RuleField(FieldKind.REFERENCE, derived=True),
        }
        for name in _REFERENCES:
            found[name] = RuleField(FieldKind.REFERENCE, settable=name in _SETTABLE)
        if wtype.code.value not in set(metadata.CustomFieldEntity):
            return found
        for key, definition in (await metadata.definitions(session, wtype.code.value)).items():
            if definition.retired:
                continue
            kind = _CUSTOM_KINDS.get(definition.type.value, FieldKind.TEXT)
            choices = (
                frozenset(definition.choice_codes(offered_only=True))
                if kind in {FieldKind.CODE, FieldKind.CODES}
                else None
            )
            found[f"custom.{key}"] = RuleField(kind, choices, settable=True)
        return found

    return fields


def _checks_for(  # noqa: C901 - one check per settable field, flat
    wtype: WorkItemType,
) -> Callable[[AsyncSession, Mapping[str, Any]], Awaitable[Mapping[str, str]]]:
    async def check(  # noqa: C901 - one check per settable field, flat
        session: AsyncSession, values: Mapping[str, Any]
    ) -> Mapping[str, str]:
        """Field → problem for values that cannot be set now (inactive, removed, unknown)."""
        problems: dict[str, str] = {}

        def ids(name: str) -> list[uuid.UUID]:
            value = values.get(name)
            try:
                return [uuid.UUID(str(value))] if value is not None else []
            except ValueError:
                problems[name] = "invalid_value"
                return []

        for name, kind in (("group_id", "group"), ("site_id", "site")):
            wanted = ids(name)
            if wanted and not await active_unit_ids(session, kind, wanted):  # type: ignore[arg-type]  # a unit kind
                problems[name] = f"{kind}_not_found"
        wanted = ids("department_id")
        if wanted and not await existing_departments(session, wanted):
            problems["department_id"] = "department_not_found"
        wanted = ids("technician_id")
        if wanted and not await user_names(session, [str(u) for u in wanted]):
            problems["technician_id"] = "user_not_found"
        wanted = ids("category_id")
        if wanted:
            found = await session.scalar(
                select(WorkItemCategory.id).where(
                    WorkItemCategory.id == wanted[0],
                    WorkItemCategory.type == wtype.code.value,
                    WorkItemCategory.deleted_at.is_(None),
                    WorkItemCategory.disabled_at.is_(None),
                )
            )
            if found is None:
                problems["category_id"] = "category_not_found"
        custom = {
            k.removeprefix("custom."): v for k, v in values.items() if k.startswith("custom.")
        }
        if custom and wtype.code.value in set(metadata.CustomFieldEntity):
            _cleaned, custom_problems = await metadata.clean(
                session, wtype.code.value, custom, current={}, creating=False
            )
            for path, code in custom_problems:
                problems[f"custom.{path.removeprefix('custom.')}"] = code
        return problems

    return check


def _category_group_for(
    wtype: WorkItemType,
) -> Callable[[AsyncSession, str], Awaitable[str | None]]:
    async def category_group(session: AsyncSession, category_id: str) -> str | None:
        try:
            wanted = uuid.UUID(category_id)
        except ValueError:
            return None
        group = await session.scalar(
            select(WorkItemCategory.default_group_id).where(
                WorkItemCategory.id == wanted, WorkItemCategory.type == wtype.code.value
            )
        )
        return str(group) if group is not None else None

    return category_group


def register_types() -> None:
    """Every work item type becomes an automation record type (called at import)."""
    for wtype in TYPES.values():
        register_record_type(
            RecordType(
                code=wtype.code.value,
                fields=_fields_for(wtype),
                check_values=_checks_for(wtype),
                category_group=_category_group_for(wtype),
            )
        )


async def requester_facts(
    session: AsyncSession, requester_id: uuid.UUID | str | None
) -> dict[str, Any]:
    """The requester's attributes a rule may test (REQ-RUL-002)."""
    if requester_id is None:
        return {"requester.vip": False, "requester.site_id": None, "requester.department_id": None}
    placement = await person_placement(session, uuid.UUID(str(requester_id)))
    return {
        "requester.vip": placement.vip,
        "requester.site_id": str(placement.site_id) if placement.site_id else None,
        "requester.department_id": (
            str(placement.department_id) if placement.department_id else None
        ),
    }


def flat_custom(custom: Mapping[str, Any] | None) -> dict[str, Any]:
    """`custom.<key>` → value, as rules see custom fields."""
    return {f"custom.{key}": value for key, value in (custom or {}).items()}


async def group_members(
    session: AsyncSession,
    wtype: WorkItemType,
    eligible: Sequence[uuid.UUID],
    group_id: uuid.UUID,
    *,
    count_paused: bool,
) -> list[Member]:
    """Members of the group who may work the type, with their open records' priorities."""
    members = set(await session.scalars(users_in_groups(frozenset({group_id}))))
    people = [u for u in eligible if u in members]
    if not people:
        return []
    categories = [StatusCategory.OPEN] + ([StatusCategory.PAUSED] if count_paused else [])
    rows = await session.execute(
        select(WorkItem.technician_id, WorkItem.priority).where(
            WorkItem.type == wtype.code,
            WorkItem.deleted_at.is_(None),
            WorkItem.technician_id.in_(people),
            WorkItem.status_category.in_(categories),
        )
    )
    loads: dict[uuid.UUID, list[str]] = {u: [] for u in people}
    for technician, priority in rows:
        if technician is not None:
            loads[technician].append(priority)
    return [Member(u, loads[u]) for u in people]


# --- the automation steps of one save (REQ-RUL-006) ----------------------------------------------


@dataclass
class Automated:
    """What automation changed in one save, ready for the record and its history."""

    values: dict[str, Any] = field(default_factory=dict)  # snapshot name → JSON value
    # One history entry per rule, routing or assignment: (automation_ref, [(field, old, new)])
    entries: list[tuple[dict[str, Any], list[tuple[str, Any, Any]]]] = field(default_factory=list)
    trace: list[TraceLine] = field(default_factory=list)


EligibleProvider = Callable[[], Awaitable[Sequence[uuid.UUID]]]


async def automate(  # noqa: PLR0913 - the documented order, one step after the other
    session: AsyncSession,
    wtype: WorkItemType,
    *,
    event: RuleEvent,
    record_id: uuid.UUID,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any],
    eligible: EligibleProvider | None,
    route: bool,
    assign_moment: Literal["create", "move"] | None,
) -> Automated:
    """Business rules, then routing, then auto-assignment (REQ-RUL-006 steps 2 and 4).

    The priority matrix (step 3) is the caller's: it runs after the rules on the final impact
    and urgency. A refusal raises 422 `rule_refused` with the rule's message.
    """
    done = Automated()
    current = dict(after)
    run = await run_business_rules(session, wtype.code.value, event, before, current)
    outcome = run.outcome
    if outcome.refusal is not None:
        raise refusal_error(outcome.refusal)
    for line in outcome.trace:
        if line.changes:
            done.entries.append(
                (
                    {"kind": "business_rule", "rule_id": line.rule_id, "rule": line.rule},
                    [(name, old, new) for name, (old, new) in line.changes.items()],
                )
            )
    current.update(outcome.values)
    done.values.update(outcome.values)
    done.trace = outcome.trace
    if route:
        choice = await route_record(session, wtype.code.value, current, record_id=record_id)
        if choice is not None:
            ref: dict[str, Any] = {"kind": "routing", "reason": choice.reason}
            if choice.rule_id is not None:
                ref |= {"rule_id": choice.rule_id, "rule": choice.rule}
            done.entries.append((ref, [("group_id", current.get("group_id"), choice.group_id)]))
            current["group_id"] = done.values["group_id"] = choice.group_id
    group = current.get("group_id")
    if assign_moment is not None and group is not None and eligible is not None:
        people = await eligible()
        result = await auto_assign(
            session,
            record_type=wtype.code.value,
            record_id=record_id,
            group_id=uuid.UUID(str(group)),
            moment=assign_moment,
            has_technician=current.get("technician_id") is not None,
            members=lambda count_paused: group_members(
                session, wtype, people, uuid.UUID(str(group)), count_paused=count_paused
            ),
        )
        if result is not None and result.choice.user_id is not None:
            ref = {
                "kind": "auto_assign",
                "method": result.choice.method.value,
                "group_id": str(group),
            }
            if result.choice.loads:
                ref["loads"] = result.choice.loads
            done.entries.append(
                (ref, [("technician_id", current.get("technician_id"), result.choice.user_id)])
            )
            current["technician_id"] = done.values["technician_id"] = result.choice.user_id
    return done
