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
from app.modules import metadata
from app.modules.organization import existing_unit_ids
from app.modules.work_items.domain.classification import Impact, Priority, Urgency
from app.modules.work_items.domain.closure import (
    AUTO_CLOSE_MAX,
    AUTO_CLOSE_MIN,
    WINDOW_MAX,
    WINDOW_MIN,
    OpenWorkKind,
    OpenWorkMode,
    rule_field_problems,
)
from app.modules.work_items.domain.conversation import FirstResponseAction
from app.modules.work_items.domain.types import WorkItemType, prefix_problems
from app.modules.work_items.events import WorkItemSettingsChanged
from app.modules.work_items.infra.models import WorkItemCategory, WorkItemTypeSettings
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import closing
from app.modules.work_items.service.catalogue import Catalogue
from app.shared.db.display_ids import NumberAlreadyUsedError, set_next_number
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes, stale_version

SETTINGS_RECORD_TYPE = "work_item_settings"
CATEGORY_RECORD_TYPE = "work_item_category"
LABEL_LANGUAGES = frozenset({"en", "ar", "ur"})
LABEL_MAX = 120


def invalid(field: str, field_code: str, **params: Any) -> ValidationFailed:  # noqa: ANN401 - problem params
    """One field problem (422) in the shared shape."""
    return ValidationFailed(
        errors=[
            FieldError(
                field=f"body.{field}",
                code=field_code,
                message_key=f"errors.field.{field_code}",
                params=params,
            )
        ]
    )


_invalid = invalid


async def stale_settings(
    session: AsyncSession, wtype: WorkItemType, current: Catalogue, expected_version: int
) -> Conflict:
    """409 for a stale save of a type's settings: who changed which settings, and when."""
    row = await session.scalar(
        select(WorkItemTypeSettings).where(WorkItemTypeSettings.type == wtype.code)
    )
    if row is None:
        return Conflict(
            code="version_conflict",
            params={
                "expected_version": expected_version,
                "current_version": current.settings_version,
            },
        )
    return await stale_version(
        session,
        row,
        expected_version=expected_version,
        record_type=SETTINGS_RECORD_TYPE,
        record_id=uuid.uuid5(uuid.NAMESPACE_URL, f"work_item_settings:{wtype.code}"),
    )


async def get_catalogue(session: AsyncSession, wtype: WorkItemType) -> Catalogue:
    """The tenant's configuration (statuses, actions, scales, matrix, reasons, prefix)."""
    return await config.load(session, wtype)


async def update_settings(  # noqa: PLR0913, C901, PLR0912, PLR0915 - one rule per setting, flat
    session: AsyncSession,
    wtype: WorkItemType,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    """Prefix, next number, defaults, automatic moves, hand-over, first response (If-Match).

    All or nothing (QA BUG-01): every value is checked first and every problem is named at its
    field; only then is anything written, in this one transaction, as one version step.
    """
    current = await config.load(session, wtype)
    changes: dict[str, Any] = {}
    problems: list[FieldError] = []

    def problem(field: str, code: str, **params: Any) -> None:  # noqa: ANN401 - problem params
        problems.extend(invalid(field=field, field_code=code, **params).errors)

    if "prefix" in values:
        prefix = str(values["prefix"] or "").strip().upper()
        if prefix_problems(prefix):
            problem("prefix", "invalid_prefix")
        changes["prefix"] = prefix
    next_number: int | None = None
    if values.get("next_number") is not None:
        next_number = int(values["next_number"])
        if next_number <= current.last_number:
            problem("next_number", "number_already_used", minimum=current.last_number + 1)
    if "default_priority" in values:
        if values["default_priority"] not in set(Priority):
            problem("default_priority", "invalid_choice")
        changes["default_priority"] = values["default_priority"]
    if "auto_status_on_assign" in values:
        changes["auto_status_on_assign"] = bool(values["auto_status_on_assign"])
    if "keep_following_on_handover" in values:
        changes["keep_following_on_handover"] = bool(values["keep_following_on_handover"])
    if "first_response_on" in values:
        chosen = list(values["first_response_on"] or [])
        if any(code not in set(FirstResponseAction) for code in chosen):
            problem("first_response_on", "invalid_choice")
        # Stored in the fixed order, so a re-ordered list is not a change.
        changes["first_response_on"] = [c for c in FirstResponseAction if c in chosen]
    for name, codes in (("default_impact", set(Impact)), ("default_urgency", set(Urgency))):
        if name in values:
            if values[name] is not None and values[name] not in codes:
                problem(name, "invalid_choice")
            changes[name] = values[name]
    if problems:
        raise ValidationFailed(errors=problems)
    before = {
        "prefix": current.prefix,
        "default_priority": current.default_priority,
        "auto_status_on_assign": current.auto_status_on_assign,
        "keep_following_on_handover": current.keep_following_on_handover,
        "first_response_on": list(current.first_response_on),
        "default_impact": current.default_impact,
        "default_urgency": current.default_urgency,
    }
    changes = {k: v for k, v in changes.items() if before[k] != v}
    if current.settings_version != expected_version:
        raise await stale_settings(session, wtype, current, expected_version)
    history = [Change(k, before[k], v) for k, v in changes.items()]
    if next_number is not None and next_number != current.last_number + 1:
        try:
            await set_next_number(session, wtype.counter_key, next_number)
        except NumberAlreadyUsedError as error:  # a create won the race since we read it
            raise invalid(
                field="next_number", field_code="number_already_used", minimum=next_number + 1
            ) from error
        history.append(Change("next_number", current.last_number + 1, next_number))
    if not history:
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
        changes=history,
        source=source,
    )
    await record_event(
        session,
        WorkItemSettingsChanged(type=wtype.code, changed_fields=sorted(c.field for c in history)),
        aggregate_id=settings_id,
        aggregate_version=expected_version + 1,
    )
    session.expire_all()
    return await config.load(session, wtype)


CLOSURE_FIELDS = (
    "resolve_requires",
    "close_requires",
    "open_work",
    "complete_open_work",
    "auto_close_days",
    "reopen_window_days",
)


def _closure_before(current: Catalogue) -> dict[str, Any]:
    c = current.closure
    return {
        "resolve_requires": list(c.resolve_requires),
        "close_requires": list(c.close_requires),
        "open_work": dict(c.open_work),
        "complete_open_work": c.complete_open_work,
        "auto_close_days": c.auto_close_days,
        "reopen_window_days": c.reopen_window_days,
    }


def _days(value: Any, low: int, high: int) -> int | None:  # noqa: ANN401 - JSON value
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        return None
    return value


async def update_closure_settings(  # noqa: PLR0913, C901, PLR0912 - one rule per setting, flat
    session: AsyncSession,
    wtype: WorkItemType,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    """Closure rules, open work, auto-close and the reopen window (WP-020f; If-Match).

    Auto-close cannot be switched on while no channel can tell requesters of a resolution: an
    incident is never auto-closed for a requester who was never told (product owner).
    """
    current = await config.load(session, wtype)
    problems: list[FieldError] = []
    changes: dict[str, Any] = {}

    def problem(field: str, code: str, **params: Any) -> None:  # noqa: ANN401 - problem params
        problems.extend(invalid(field=field, field_code=code, **params).errors)

    custom = await metadata.definitions(session, wtype.code.value)
    for name in ("resolve_requires", "close_requires"):
        if name in values:
            chosen = list(dict.fromkeys(values[name] or []))
            if rule_field_problems(chosen, custom):
                problem(name, "invalid_choice")
            changes[name] = chosen
    if "open_work" in values:
        saved = dict(values["open_work"] or {})
        kinds, modes = set(OpenWorkKind), set(OpenWorkMode)
        if any(k not in kinds or v not in modes for k, v in saved.items()):
            problem("open_work", "invalid_choice")
        changes["open_work"] = saved
    if "complete_open_work" in values:
        changes["complete_open_work"] = bool(values["complete_open_work"])
    if "auto_close_days" in values:
        days = values["auto_close_days"]
        if days is not None and _days(days, AUTO_CLOSE_MIN, AUTO_CLOSE_MAX) is None:
            problem("auto_close_days", "out_of_range", min=AUTO_CLOSE_MIN, max=AUTO_CLOSE_MAX)
        elif days is not None and not closing.requester_channels():
            problem("auto_close_days", "auto_close_needs_notifications")
        changes["auto_close_days"] = days
    if "reopen_window_days" in values:
        window = _days(values["reopen_window_days"], WINDOW_MIN, WINDOW_MAX)
        if window is None:
            problem("reopen_window_days", "out_of_range", min=WINDOW_MIN, max=WINDOW_MAX)
        changes["reopen_window_days"] = values["reopen_window_days"]
    if problems:
        raise ValidationFailed(errors=problems)
    before = _closure_before(current)
    changes = {k: v for k, v in changes.items() if before[k] != v}
    if current.settings_version != expected_version:
        raise await stale_settings(session, wtype, current, expected_version)
    if not changes:
        return current
    await session.execute(
        update(WorkItemTypeSettings)
        .where(WorkItemTypeSettings.type == wtype.code)
        .values(**changes, version=WorkItemTypeSettings.version + 1, updated_by=user_id)
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


def labels_of(raw: Mapping[str, Any] | None, *, allow_none: bool) -> dict[str, str] | None:
    """Clean translations {en, ar, ur}; English required. None only where shipped labels exist."""
    if raw is None:
        if not allow_none:
            raise _invalid(field="labels", field_code="english_label_required")
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
        labels=labels_of(labels, allow_none=False),
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
        changes["labels"] = labels_of(values["labels"], allow_none=node.code is not None)
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
            raise await stale_version(
                session,
                node,
                expected_version=expected_version,
                record_type=CATEGORY_RECORD_TYPE,
                record_id=node.id,
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
