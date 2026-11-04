"""Catalog categories and items (WP-030 s1, plan D2; REQ-SR-001, -005..008, -010, -021..023, -046).

Reading: staff (anyone holding `catalog_items.manage`, or a technician) see every item;
everyone else sees the enabled items open to everyone (REQ-SR-010 AC3). Writing needs
`catalog_items.manage`, follows If-Match, keeps field history and emits an event in the same
transaction. Every reference is checked through its own module's public interface.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules import sla
from app.modules.identity_access import Subject, user_contacts
from app.modules.organization import existing_unit_ids
from app.modules.service_catalog.domain.items import (
    ApprovalStage,
    Approver,
    ApproverKind,
    ItemAudience,
    ItemRules,
    PlannedTask,
    Question,
    QuestionKind,
    answer_problems,
    name_problems,
    needs_approval,
    rules_problems,
)
from app.modules.service_catalog.events import CatalogItemChanged, ServiceCategoryChanged
from app.modules.service_catalog.infra.models import CatalogItem, ServiceCategory
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

MANAGE = "catalog_items.manage"
ITEM_RECORD_TYPE = "catalog_item"
CATEGORY_RECORD_TYPE = "service_category"
SR_TYPE = "service_request"  # the SLA policies an item may name
PRIORITIES = frozenset({"p1", "p2", "p3", "p4"})
# What a write may set, as stored.
ITEM_FIELDS = (
    "category_id",
    "names",
    "descriptions",
    "audience",
    "enabled",
    "questions",
    "approval",
    "plan",
    "default_priority",
    "requester_sets_priority",
    "sla_policy_id",
    "group_id",
    "technician_id",
    "technician_after_approval",
    "count_approval_time",
    "auto_fulfil",
)


class ItemRepository(Repository[CatalogItem]):
    """Items: versioned updates with If-Match."""

    model = CatalogItem


class CategoryRepository(Repository[ServiceCategory]):
    """Categories: versioned updates with If-Match."""

    model = ServiceCategory


def _invalid(problems: Sequence[tuple[str, str]]) -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(field=f"body.{at}", code=code, message_key=f"errors.field.{code}")
            for at, code in problems
        ]
    )


def _is_staff(subject: Subject) -> bool:
    return subject.holds(MANAGE) or "technician" in subject.role_keys or subject.is_tenant_admin


def _require_manage(subject: Subject) -> None:
    if not subject.holds(MANAGE):
        raise PermissionDenied(params={"permission": MANAGE, "reason": "no_permission"})


# --- JSON <-> domain ------------------------------------------------------------------------------


def _uuid(value: Any) -> uuid.UUID | None:  # noqa: ANN401 - JSON value
    return None if value in {None, ""} else uuid.UUID(str(value))


def rules_of(item: CatalogItem) -> ItemRules:
    """The item's rules as the domain sees them (also for work_items, through the package)."""
    approval = item.approval
    stage = (
        ApprovalStage(
            approvers=tuple(
                Approver(ApproverKind(a["kind"]), _uuid(a.get("person_id")))
                for a in approval.get("approvers", [])
            ),
            backup_id=_uuid(approval.get("backup_id")),
            comments_required=bool(approval.get("comments_required", False)),
            self_approval=bool(approval.get("self_approval", False)),
        )
        if approval
        else None
    )
    return ItemRules(
        questions=tuple(
            Question(
                q["key"],
                q.get("label", {}),
                QuestionKind(q["kind"]),
                bool(q.get("required", False)),
                tuple(q.get("options", ())),
            )
            for q in item.questions
        ),
        approval=stage,
        plan=tuple(
            PlannedTask(
                t.get("title", {}),
                _uuid(t.get("group_id")),
                _uuid(t.get("owner_id")),
                bool(t.get("required", True)),
                bool(t.get("internal", False)),
            )
            for t in item.plan
        ),
        technician_after_approval=item.technician_after_approval,
        count_approval_time=item.count_approval_time,
        auto_fulfil=item.auto_fulfil,
    )


def _shape_problems(values: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Types and codes of the incoming fields (before the domain rules)."""
    found: list[tuple[str, str]] = []
    if "audience" in values and values["audience"] not in set(ItemAudience):
        found.append(("audience", "invalid_choice"))
    if "default_priority" in values and values["default_priority"] not in (PRIORITIES | {None}):
        found.append(("default_priority", "invalid_choice"))
    found += [
        (name, "invalid_value")
        for name in ("names", "descriptions")
        if name in values and not isinstance(values[name], Mapping)
    ]
    if "names" in values and isinstance(values["names"], Mapping):
        found += name_problems("names", values["names"], required=True)
    for i, q in enumerate(values.get("questions") or []):
        if not isinstance(q, Mapping) or q.get("kind") not in set(QuestionKind):
            found.append((f"questions.{i}.kind", "invalid_choice"))
    approval = values.get("approval")
    if approval is not None:
        if not isinstance(approval, Mapping):
            found.append(("approval", "invalid_value"))
        else:
            for i, a in enumerate(approval.get("approvers") or []):
                if not isinstance(a, Mapping) or a.get("kind") not in set(ApproverKind):
                    found.append((f"approval.approvers.{i}.kind", "invalid_choice"))
    return found


def _stored(values: Mapping[str, Any]) -> dict[str, Any]:
    """The fields as the columns keep them (IDs as text inside the JSON)."""
    out = {k: values[k] for k in ITEM_FIELDS if k in values}
    for name in ("category_id", "sla_policy_id", "group_id", "technician_id"):
        if name in out:
            out[name] = _uuid(out[name])
    if out.get("questions") is not None:
        out["questions"] = [
            {
                "key": q["key"],
                "label": dict(q.get("label") or {}),
                "kind": q["kind"],
                "required": bool(q.get("required", False)),
                "options": list(q.get("options") or []),
            }
            for q in out["questions"]
        ]
    if out.get("plan") is not None:
        out["plan"] = [
            {
                "title": dict(t.get("title") or {}),
                "group_id": None if t.get("group_id") is None else str(t["group_id"]),
                "owner_id": None if t.get("owner_id") is None else str(t["owner_id"]),
                "required": bool(t.get("required", True)),
                "internal": bool(t.get("internal", False)),
            }
            for t in out["plan"]
        ]
    if out.get("approval") is not None:
        a = out["approval"]
        out["approval"] = {
            "approvers": [
                {
                    "kind": x["kind"],
                    "person_id": None if x.get("person_id") is None else str(x["person_id"]),
                }
                for x in a.get("approvers") or []
            ],
            "backup_id": None if a.get("backup_id") is None else str(a["backup_id"]),
            "comments_required": bool(a.get("comments_required", False)),
            "self_approval": bool(a.get("self_approval", False)),
        }
    return out


async def _group_problems(
    session: AsyncSession, item: CatalogItem, rules: ItemRules
) -> list[tuple[str, str]]:
    wanted = {g for g in (item.group_id, *(t.group_id for t in rules.plan)) if g is not None}
    known = await existing_unit_ids(session, "group", sorted(wanted, key=str))
    found = [("group_id", "not_found")] if item.group_id not in {None, *known} else []
    return found + [
        (f"plan.{i}.group_id", "not_found")
        for i, task in enumerate(rules.plan)
        if task.group_id is not None and task.group_id not in known
    ]


def _people_named(item: CatalogItem, rules: ItemRules) -> dict[str, uuid.UUID]:
    people: dict[str, uuid.UUID] = {}
    if item.technician_id is not None:
        people["technician_id"] = item.technician_id
    if rules.approval is not None:
        people |= {
            f"approval.approvers.{i}.person_id": a.person_id
            for i, a in enumerate(rules.approval.approvers)
            if a.person_id is not None
        }
        if rules.approval.backup_id is not None:
            people["approval.backup_id"] = rules.approval.backup_id
    people |= {
        f"plan.{i}.owner_id": task.owner_id
        for i, task in enumerate(rules.plan)
        if task.owner_id is not None
    }
    return people


async def _reference_problems(
    session: AsyncSession, item: CatalogItem, rules: ItemRules
) -> list[tuple[str, str]]:
    """Every ID the item names exists in this tenant (through each module's public interface)."""
    found: list[tuple[str, str]] = []
    if item.category_id is not None:
        category = await session.scalar(
            select(ServiceCategory.id).where(
                ServiceCategory.id == item.category_id, ServiceCategory.deleted_at.is_(None)
            )
        )
        if category is None:
            found.append(("category_id", "not_found"))
    if item.sla_policy_id is not None and not await sla.existing_policy_ids(
        session, SR_TYPE, [item.sla_policy_id]
    ):
        found.append(("sla_policy_id", "not_found"))
    found += await _group_problems(session, item, rules)
    people = _people_named(item, rules)
    known = await user_contacts(session, sorted({str(p) for p in people.values()}))
    return found + [(at, "not_found") for at, person in people.items() if str(person) not in known]


# --- views ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemView:
    """An item for a screen: the row, its rules and whether the viewer may change it."""

    item: CatalogItem
    rules: ItemRules
    can_manage: bool


def _visible(subject: Subject) -> Select[CatalogItem]:
    query = select(CatalogItem).where(CatalogItem.deleted_at.is_(None))
    if not _is_staff(subject):
        query = query.where(
            CatalogItem.enabled.is_(True), CatalogItem.audience == ItemAudience.EVERYONE.value
        )
    return query


async def list_items(
    session: AsyncSession, subject: Subject, *, category_id: uuid.UUID | None = None
) -> list[ItemView]:
    """The items the viewer may raise (staff: all, disabled ones marked)."""
    query = _visible(subject)
    if category_id is not None:
        query = query.where(CatalogItem.category_id == category_id)
    rows = list(await session.scalars(query.order_by(CatalogItem.created_at, CatalogItem.id)))
    manage = subject.holds(MANAGE)
    return [ItemView(r, rules_of(r), manage) for r in rows]


async def get_item(session: AsyncSession, subject: Subject, item_id: uuid.UUID) -> ItemView:
    """One item the viewer may see; otherwise 404."""
    row = await session.scalar(_visible(subject).where(CatalogItem.id == item_id))
    if row is None:
        raise NotFound(code="catalog_item_not_found")
    return ItemView(row, rules_of(row), subject.holds(MANAGE))


def _snapshot(item: CatalogItem) -> dict[str, Any]:
    return {
        name: (str(v) if isinstance(v := getattr(item, name), uuid.UUID) else v)
        for name in ITEM_FIELDS
    }


async def _check(session: AsyncSession, item: CatalogItem) -> None:
    rules = rules_of(item)
    problems = rules_problems(rules) + await _reference_problems(session, item, rules)
    if problems:
        raise _invalid(problems)


async def create_item(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> ItemView:
    """A new item (names in English at least)."""
    _require_manage(subject)
    if problems := _shape_problems({"names": {}, **values}):
        raise _invalid(problems)
    item = CatalogItem(**{"descriptions": {}, "questions": [], "plan": [], **_stored(values)})
    await _check(session, item)
    await ItemRepository(session).add(item)
    after = _snapshot(item)
    await record_changes(
        session,
        record_type=ITEM_RECORD_TYPE,
        record_id=item.id,
        version=item.version,
        kind="created",
        changes=[Change(k, None, v) for k, v in after.items() if v not in (None, [], {})],
        source=source,
    )
    await record_event(
        session,
        CatalogItemChanged(item_id=item.id, changed_fields=sorted(after)),
        aggregate_id=item.id,
        aggregate_version=item.version,
    )
    return ItemView(item, rules_of(item), can_manage=True)


async def update_item(  # noqa: PLR0913 - the item, its version and the change
    session: AsyncSession,
    subject: Subject,
    item_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> ItemView:
    """Change an item; unchanged input keeps the version and emits nothing."""
    _require_manage(subject)
    row = await session.scalar(
        select(CatalogItem).where(CatalogItem.id == item_id, CatalogItem.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="catalog_item_not_found")
    if problems := _shape_problems(values):
        raise _invalid(problems)
    before = _snapshot(row)
    wanted = _stored(values)
    changes = {k: v for k, v in wanted.items() if getattr(row, k) != v}
    if not changes:
        if row.version != expected_version:
            raise Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": row.version},
            )
        return ItemView(row, rules_of(row), can_manage=True)
    probe = CatalogItem(**{**{k: getattr(row, k) for k in ITEM_FIELDS}, **changes})
    await _check(session, probe)
    updated = await ItemRepository(session).update(
        row.id, expected_version=expected_version, changes=changes
    )
    after = _snapshot(updated)
    changed = [Change(k, before[k], after[k]) for k in ITEM_FIELDS if before[k] != after[k]]
    await record_changes(
        session,
        record_type=ITEM_RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=changed,
        source=source,
    )
    await record_event(
        session,
        CatalogItemChanged(item_id=updated.id, changed_fields=[c.field for c in changed]),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return ItemView(updated, rules_of(updated), can_manage=True)


# --- categories -----------------------------------------------------------------------------------


async def list_categories(session: AsyncSession) -> list[ServiceCategory]:
    """Every live category, in their order (everyone may read the names)."""
    return list(
        await session.scalars(
            select(ServiceCategory)
            .where(ServiceCategory.deleted_at.is_(None))
            .order_by(ServiceCategory.sort_order, ServiceCategory.id)
        )
    )


async def create_category(
    session: AsyncSession,
    subject: Subject,
    names: Mapping[str, str],
    *,
    sort_order: int,
    source: Source,
) -> ServiceCategory:
    """A new category (an English name at least)."""
    _require_manage(subject)
    if problems := name_problems("names", names, required=True):
        raise _invalid(problems)
    category = ServiceCategory(names=dict(names), sort_order=sort_order)
    await CategoryRepository(session).add(category)
    await record_changes(
        session,
        record_type=CATEGORY_RECORD_TYPE,
        record_id=category.id,
        version=category.version,
        kind="created",
        changes=[Change("names", None, dict(names)), Change("sort_order", None, sort_order)],
        source=source,
    )
    await record_event(
        session,
        ServiceCategoryChanged(category_id=category.id, changed_fields=["names", "sort_order"]),
        aggregate_id=category.id,
        aggregate_version=category.version,
    )
    return category


# --- for work_items: what an item decides for a new request ---------------------------------------


@dataclass(frozen=True)
class RequestItem:
    """What a service request takes from its item (plain values; work_items decides with them)."""

    item_id: uuid.UUID
    needs_approval: bool
    default_priority: str | None
    sla_policy_id: uuid.UUID | None
    group_id: uuid.UUID | None
    technician_id: uuid.UUID | None
    technician_after_approval: bool
    count_approval_time: bool
    auto_fulfil: bool
    answer_problems: tuple[tuple[str, str], ...]  # the answers checked against the form
    # The approval stage (WP-030 s2), as plain values for work_items' engine: each approver as
    # (manager of the requested-for person?, person id), the backup, and the stage's switches.
    approvers: tuple[tuple[bool, uuid.UUID | None], ...] = ()
    backup_id: uuid.UUID | None = None
    self_approval: bool = False
    comments_required: bool = False


async def request_item(
    session: AsyncSession,
    subject: Subject,
    item_id: uuid.UUID,
    answers: Mapping[str, Any],
) -> RequestItem:
    """The item a person raises a request from, if they may (enabled, open to them); else 404."""
    view = await get_item(session, subject, item_id)
    if not view.item.enabled:
        raise NotFound(code="catalog_item_not_found")
    return _decides(view.item, answers)


def _decides(item: CatalogItem, answers: Mapping[str, Any]) -> RequestItem:
    rules = rules_of(item)
    stage = rules.approval
    return RequestItem(
        item_id=item.id,
        needs_approval=needs_approval(rules),
        default_priority=item.default_priority,
        sla_policy_id=item.sla_policy_id,
        group_id=item.group_id,
        technician_id=item.technician_id,
        technician_after_approval=rules.technician_after_approval,
        count_approval_time=rules.count_approval_time,
        auto_fulfil=rules.auto_fulfil,
        answer_problems=tuple(answer_problems(rules.questions, answers)),
        approvers=tuple(
            (a.kind is ApproverKind.REQUESTED_FOR_MANAGER, a.person_id)
            for a in (stage.approvers if stage else ())
        ),
        backup_id=stage.backup_id if stage else None,
        self_approval=stage.self_approval if stage else False,
        comments_required=stage.comments_required if stage else False,
    )


async def item_decides(session: AsyncSession, item_id: uuid.UUID) -> RequestItem | None:
    """What an existing request's item says, for a step after submission (WP-030 s2).

    Read by the system (the technician after approval): no viewer check and deleted items
    included, since the request already exists and its approver may not see the item.
    """
    row = await session.get(CatalogItem, item_id)
    return None if row is None else _decides(row, {})


__all__ = [
    "MANAGE",
    "ItemView",
    "RequestItem",
    "create_category",
    "create_item",
    "get_item",
    "item_decides",
    "list_categories",
    "list_items",
    "request_item",
    "rules_of",
    "update_item",
]
