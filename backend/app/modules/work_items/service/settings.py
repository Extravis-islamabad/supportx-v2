"""Type settings and the category tree (WP-020; admin screens follow in WP-020c, D-056).

MVP admins edit values, not structure: the display prefix, the default priority, the automatic
status moves on assignment, and the category tree (add, rename / translate, disable). Statuses
and transitions keep their Appendix A shape until the life-cycle designer (REQ-INC-049).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.organization import existing_unit_ids
from app.modules.work_items.domain.classification import Impact, Priority, Urgency
from app.modules.work_items.domain.types import WorkItemType, prefix_problems
from app.modules.work_items.events import WorkItemSettingsChanged
from app.modules.work_items.infra.models import WorkItemCategory, WorkItemTypeSettings
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service.catalogue import Catalogue
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

SETTINGS_RECORD_TYPE = "work_item_settings"
CATEGORY_RECORD_TYPE = "work_item_category"
LABEL_LANGUAGES = frozenset({"en", "ar", "ur"})
LABEL_MAX = 120


def _invalid(field: str, field_code: str) -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(
                field=f"body.{field}",
                code=field_code,
                message_key=f"errors.field.{field_code}",
            )
        ]
    )


async def get_catalogue(session: AsyncSession, wtype: WorkItemType) -> Catalogue:
    """The tenant's configuration (statuses, actions, scales, matrix, reasons, prefix)."""
    return await config.load(session, wtype)


async def update_settings(  # noqa: PLR0913, C901 - one rule per setting, flat
    session: AsyncSession,
    wtype: WorkItemType,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    """Prefix, default priority and scales, automatic status moves (If-Match: settings version)."""
    current = await config.load(session, wtype)
    changes: dict[str, Any] = {}
    if "prefix" in values:
        prefix = str(values["prefix"] or "").strip().upper()
        if prefix_problems(prefix):
            raise _invalid(field="prefix", field_code="invalid_prefix")
        changes["prefix"] = prefix
    if "default_priority" in values:
        if values["default_priority"] not in set(Priority):
            raise _invalid(field="default_priority", field_code="invalid_choice")
        changes["default_priority"] = values["default_priority"]
    if "auto_status_on_assign" in values:
        changes["auto_status_on_assign"] = bool(values["auto_status_on_assign"])
    for name, codes in (("default_impact", set(Impact)), ("default_urgency", set(Urgency))):
        if name in values:
            if values[name] is not None and values[name] not in codes:
                raise _invalid(field=name, field_code="invalid_choice")
            changes[name] = values[name]
    before = {
        "prefix": current.prefix,
        "default_priority": current.default_priority,
        "auto_status_on_assign": current.auto_status_on_assign,
        "default_impact": current.default_impact,
        "default_urgency": current.default_urgency,
    }
    changes = {k: v for k, v in changes.items() if before[k] != v}
    if current.settings_version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={
                "expected_version": expected_version,
                "current_version": current.settings_version,
            },
        )
    if not changes:
        return current
    await session.execute(
        update(WorkItemTypeSettings)
        .where(WorkItemTypeSettings.type == wtype.code)
        .values(
            **changes,
            version=WorkItemTypeSettings.version + 1,
            updated_at=datetime.now(UTC),
            updated_by=user_id,
        )
    )
    settings_id = uuid.uuid5(uuid.NAMESPACE_URL, f"work_item_settings:{wtype.code}")
    await record_changes(
        session,
        record_type=SETTINGS_RECORD_TYPE,
        record_id=settings_id,
        version=expected_version + 1,
        kind="updated",
        changes=[Change(k, before[k], v) for k, v in changes.items()],
        source=source,
    )
    await record_event(
        session,
        WorkItemSettingsChanged(type=wtype.code, changed_fields=sorted(changes)),
        aggregate_id=settings_id,
        aggregate_version=expected_version + 1,
    )
    session.expire_all()
    return await config.load(session, wtype)


# --- categories -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class CategoryNode:
    """One node of the tree as screens show it."""

    record: WorkItemCategory


class CategoryRepository(Repository[WorkItemCategory]):
    """Category nodes of the session's tenant."""

    model = WorkItemCategory


async def list_categories(session: AsyncSession, wtype: WorkItemType) -> list[WorkItemCategory]:
    """Every node of the type's tree (disabled ones included, marked), parents first."""
    await config.ensure_seeded(session, wtype)
    return list(
        await session.scalars(
            select(WorkItemCategory)
            .where(WorkItemCategory.type == wtype.code, WorkItemCategory.deleted_at.is_(None))
            .order_by(WorkItemCategory.level, WorkItemCategory.sort_order, WorkItemCategory.id)
        )
    )


def _labels(raw: Mapping[str, Any] | None) -> dict[str, str] | None:
    if raw is None:
        return None
    labels = {k: " ".join(str(v).split()) for k, v in raw.items() if v is not None}
    if not labels.get("en"):
        raise _invalid(field="labels", field_code="english_label_required")
    if set(labels) - LABEL_LANGUAGES:
        raise _invalid(field="labels", field_code="unknown_language")
    if any(len(v) > LABEL_MAX for v in labels.values()):
        raise _invalid(field="labels", field_code="value_too_long")
    return labels


async def _group_ok(session: AsyncSession, group_id: uuid.UUID | None) -> None:
    if group_id is not None and group_id not in await existing_unit_ids(
        session, "group", [group_id]
    ):
        raise _invalid(field="default_group_id", field_code="group_not_found")


async def create_category(  # noqa: PLR0913 - the node's inputs, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    *,
    parent_id: uuid.UUID | None,
    labels: Mapping[str, Any],
    default_group_id: uuid.UUID | None,
    source: Source,
) -> WorkItemCategory:
    """A new node under `parent_id` (or a new top-level category); at most three levels."""
    await config.ensure_seeded(session, wtype)
    level = 1
    if parent_id is not None:
        parent = await session.scalar(
            select(WorkItemCategory).where(
                WorkItemCategory.id == parent_id,
                WorkItemCategory.type == wtype.code,
                WorkItemCategory.deleted_at.is_(None),
            )
        )
        if parent is None:
            raise _invalid(field="parent_id", field_code="category_not_found")
        if parent.level >= 3:  # noqa: PLR2004 - category, subcategory, item
            raise _invalid(field="parent_id", field_code="too_deep")
        level = parent.level + 1
    await _group_ok(session, default_group_id)
    siblings = await session.scalar(
        select(func.count()).where(
            WorkItemCategory.type == wtype.code,
            WorkItemCategory.parent_id.is_(None)
            if parent_id is None
            else WorkItemCategory.parent_id == parent_id,
        )
    )
    node = WorkItemCategory(
        type=wtype.code,
        parent_id=parent_id,
        level=level,
        labels=_labels(labels),
        sort_order=int(siblings or 0),
        default_group_id=default_group_id,
    )
    await CategoryRepository(session).add(node)
    await record_changes(
        session,
        record_type=CATEGORY_RECORD_TYPE,
        record_id=node.id,
        version=node.version,
        kind="created",
        changes=[
            Change("labels", None, node.labels),
            Change("parent_id", None, str(parent_id) if parent_id else None),
        ],
        source=source,
    )
    await record_event(
        session,
        WorkItemSettingsChanged(type=wtype.code, changed_fields=["categories"]),
        aggregate_id=node.id,
        aggregate_version=node.version,
    )
    return node


async def update_category(  # noqa: PLR0913 - the change and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    category_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> WorkItemCategory:
    """Rename / translate, set the default group, or disable / enable a node."""
    node = await session.scalar(
        select(WorkItemCategory).where(
            WorkItemCategory.id == category_id,
            WorkItemCategory.type == wtype.code,
            WorkItemCategory.deleted_at.is_(None),
        )
    )
    if node is None:
        raise NotFound(code="category_not_found")
    changes: dict[str, Any] = {}
    if "labels" in values:
        changes["labels"] = _labels(values["labels"])
        if changes["labels"] is None and node.code is None:
            raise _invalid(field="labels", field_code="english_label_required")
    if "default_group_id" in values:
        await _group_ok(session, values["default_group_id"])
        changes["default_group_id"] = values["default_group_id"]
    if "disabled" in values:
        disabled = bool(values["disabled"])
        if disabled != (node.disabled_at is not None):
            changes["disabled_at"] = datetime.now(UTC) if disabled else None
    before = {k: getattr(node, k) for k in changes}
    changes = {k: v for k, v in changes.items() if before[k] != v}
    if not changes:
        if node.version != expected_version:
            raise Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": node.version},
            )
        return node
    updated = await CategoryRepository(session).update(
        node.id, expected_version=expected_version, changes=changes
    )

    def plain(value: Any) -> Any:  # noqa: ANN401 - JSON values
        return (
            value.isoformat()
            if isinstance(value, datetime)
            else str(value)
            if isinstance(value, uuid.UUID)
            else value
        )

    await record_changes(
        session,
        record_type=CATEGORY_RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=[Change(k, plain(before[k]), plain(v)) for k, v in changes.items()],
        source=source,
    )
    await record_event(
        session,
        WorkItemSettingsChanged(type=wtype.code, changed_fields=["categories"]),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return updated
