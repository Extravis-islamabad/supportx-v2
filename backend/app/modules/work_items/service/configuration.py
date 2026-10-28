"""Admin edits of a type's values: statuses, reason prompts, scales, matrix, lists, numbering.

WP-020c (D-056). Pick lists are the reason lists, levels and closure codes.

MVP admins change values, not structure (D-056): labels, colours, the matrix, reason prompts,
list values. Adding or removing statuses and transitions waits for the life-cycle designer.

Every edit here is one optimistic-concurrency step on the type's configuration: it needs the
catalogue `version` the admin was looking at (If-Match), bumps it, writes field history on the
settings record and a `work_items.settings.changed` event in the same transaction (open forms
reload live). The routes add the audit entry (WP-018).
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.work_items.domain.classification import (
    Impact,
    MatrixError,
    Scale,
    Urgency,
    check_matrix,
)
from app.modules.work_items.domain.lifecycle import (
    OTHER_REASON,
    SYSTEM_ACTIONS,
    ReasonMode,
    WorkItemAction,
)
from app.modules.work_items.domain.templates import (
    ACTION_REASON_LIST,
    LIST_VALUES_MAX,
    REASON_LISTS,
    PickList,
    is_admin_code,
    new_value_code,
    order_problems,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.events import WorkItemSettingsChanged
from app.modules.work_items.infra.models import (
    WorkItemPriorityCell,
    WorkItemReason,
    WorkItemScaleValue,
    WorkItemStatus,
    WorkItemTransition,
    WorkItemTypeSettings,
)
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service.catalogue import Catalogue
from app.modules.work_items.service.settings import (
    SETTINGS_RECORD_TYPE,
    invalid,
    labels_of,
    stale_settings,
)
from app.shared.db.display_ids import NumberAlreadyUsedError, set_next_number
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

COLOUR_PATTERN = r"^#[0-9a-fA-F]{6}$"
_REASON_PICK_LISTS = frozenset(PickList(r) for r in REASON_LISTS)


def _colour(value: Any, field: str = "colour") -> str | None:  # noqa: ANN401 - JSON value
    if value is None:
        return None
    text = str(value)
    if not re.fullmatch(COLOUR_PATTERN, text):
        raise invalid(field, "invalid_colour")
    return text.lower()


async def _bump(  # noqa: PLR0913 - the step and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    *,
    current: Catalogue,
    expected_version: int,
    changes: Sequence[Change],
    changed_fields: Sequence[str],
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    """Check the version, then bump it, write history and the event; the new catalogue."""
    await _check_version(session, wtype, current, expected_version)
    if not changes:
        return current
    await session.execute(
        update(WorkItemTypeSettings)
        .where(WorkItemTypeSettings.type == wtype.code)
        .values(
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
        changes=list(changes),
        source=source,
    )
    await record_event(
        session,
        WorkItemSettingsChanged(type=wtype.code, changed_fields=sorted(set(changed_fields))),
        aggregate_id=settings_id,
        aggregate_version=expected_version + 1,
    )
    session.expire_all()
    return await config.load(session, wtype)


async def _check_version(
    session: AsyncSession, wtype: WorkItemType, current: Catalogue, expected_version: int
) -> None:
    if current.settings_version != expected_version:
        raise await stale_settings(session, wtype, current, expected_version)


# --- statuses -------------------------------------------------------------------------------------


async def update_status(  # noqa: PLR0913 - the change and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    code: str,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    """Labels (translations) and colour of a status; its category and code never change."""
    current = await config.load(session, wtype)
    await _check_version(session, wtype, current, expected_version)
    row = await session.scalar(
        select(WorkItemStatus).where(WorkItemStatus.type == wtype.code, WorkItemStatus.code == code)
    )
    if row is None:
        raise NotFound(code="status_not_found")
    changes: dict[str, Any] = {}
    if "labels" in values:
        changes["labels"] = labels_of(values["labels"], allow_none=True)
    if "colour" in values:
        colour = _colour(values["colour"])
        if colour is None:
            raise invalid(field="colour", field_code="required")
        changes["colour"] = colour
    changes = {k: v for k, v in changes.items() if getattr(row, k) != v}
    history = [Change(f"status.{code}.{k}", getattr(row, k), v) for k, v in changes.items()]
    if changes:
        await session.execute(
            update(WorkItemStatus)
            .where(WorkItemStatus.type == wtype.code, WorkItemStatus.code == code)
            .values(**changes)
        )
    return await _bump(
        session,
        wtype,
        current=current,
        expected_version=expected_version,
        changes=history,
        changed_fields=["statuses"],
        source=source,
        user_id=user_id,
    )


# --- reason prompts per transition (REQ-INC-047 AC3) ----------------------------------------------


async def update_transition(  # noqa: PLR0913 - the change and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    from_status: str,
    action: str,
    *,
    expected_version: int,
    reason_mode: str,
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    """Turn a transition's reason prompt off, optional or required."""
    current = await config.load(session, wtype)
    await _check_version(session, wtype, current, expected_version)
    if action not in set(WorkItemAction) or WorkItemAction(action) in SYSTEM_ACTIONS:
        raise NotFound(code="transition_not_found")
    found = current.lifecycle.transitions.get((from_status, WorkItemAction(action)))
    if found is None:
        raise NotFound(code="transition_not_found")
    if reason_mode not in set(ReasonMode):
        raise invalid(field="reason_mode", field_code="invalid_choice")
    mode = ReasonMode(reason_mode)
    # A prompt asks from the action's own list (pause, cancel ...); text only for the others.
    reason_list = None if mode == ReasonMode.NONE else ACTION_REASON_LIST.get(found.action)
    if mode == found.reason_mode and reason_list == found.reason_list:
        return await _bump(
            session,
            wtype,
            current=current,
            expected_version=expected_version,
            changes=[],
            changed_fields=[],
            source=source,
            user_id=user_id,
        )
    await session.execute(
        update(WorkItemTransition)
        .where(
            WorkItemTransition.type == wtype.code,
            WorkItemTransition.from_status == from_status,
            WorkItemTransition.action == action,
        )
        .values(reason_mode=mode, reason_list=reason_list)
    )
    return await _bump(
        session,
        wtype,
        current=current,
        expected_version=expected_version,
        changes=[Change(f"transition.{from_status}.{action}.reason_mode", found.reason_mode, mode)],
        changed_fields=["transitions"],
        source=source,
        user_id=user_id,
    )


# --- impact, urgency and priority values ----------------------------------------------------------


async def update_scale_value(  # noqa: PLR0913 - the change and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    scale: str,
    code: str,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    """Labels and colour of one impact, urgency or priority value (the values are fixed)."""
    current = await config.load(session, wtype)
    await _check_version(session, wtype, current, expected_version)
    if scale not in set(Scale):
        raise NotFound(code="scale_value_not_found")
    row = await session.scalar(
        select(WorkItemScaleValue).where(
            WorkItemScaleValue.type == wtype.code,
            WorkItemScaleValue.scale == scale,
            WorkItemScaleValue.code == code,
        )
    )
    if row is None:
        raise NotFound(code="scale_value_not_found")
    changes: dict[str, Any] = {}
    if "labels" in values:
        changes["labels"] = labels_of(values["labels"], allow_none=True)
    if "colour" in values:
        changes["colour"] = _colour(values["colour"])
    changes = {k: v for k, v in changes.items() if getattr(row, k) != v}
    if changes:
        await session.execute(
            update(WorkItemScaleValue)
            .where(
                WorkItemScaleValue.type == wtype.code,
                WorkItemScaleValue.scale == scale,
                WorkItemScaleValue.code == code,
            )
            .values(**changes)
        )
    return await _bump(
        session,
        wtype,
        current=current,
        expected_version=expected_version,
        changes=[Change(f"{scale}.{code}.{k}", getattr(row, k), v) for k, v in changes.items()],
        changed_fields=["scales"],
        source=source,
        user_id=user_id,
    )


async def replace_matrix(  # noqa: PLR0913 - the change and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    *,
    expected_version: int,
    cells: Sequence[Mapping[str, str]],
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    """The whole matrix at once; an empty or unknown cell refuses all of it (REQ-INC-009 AC4)."""
    current = await config.load(session, wtype)
    await _check_version(session, wtype, current, expected_version)
    matrix = {(c.get("impact", ""), c.get("urgency", "")): c.get("priority", "") for c in cells}
    if len(matrix) != len(cells) or set(matrix) - {(i, u) for i in Impact for u in Urgency}:
        raise invalid(field="cells", field_code="matrix_incomplete")
    try:
        check_matrix(matrix)
    except MatrixError as error:
        raise invalid(field="cells", field_code="matrix_incomplete") from error
    changes = [
        Change(f"matrix.{i}.{u}", current.matrix.get((i, u)), p)
        for (i, u), p in sorted(matrix.items())
        if current.matrix.get((i, u)) != p
    ]
    for change in changes:
        _, impact, urgency = change.field.split(".")
        await session.execute(
            update(WorkItemPriorityCell)
            .where(
                WorkItemPriorityCell.type == wtype.code,
                WorkItemPriorityCell.impact == impact,
                WorkItemPriorityCell.urgency == urgency,
            )
            .values(priority=change.new)
        )
    return await _bump(
        session,
        wtype,
        current=current,
        expected_version=expected_version,
        changes=changes,
        changed_fields=["matrix"],
        source=source,
        user_id=user_id,
    )


# --- pick lists: reasons, levels, closure codes (REQ-ADM-043) -------------------------------------


def _list(name: str) -> PickList:
    if name not in set(PickList):
        raise NotFound(code="pick_list_not_found")
    return PickList(name)


async def add_list_value(  # noqa: PLR0913 - the value and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    list_name: str,
    *,
    expected_version: int,
    labels: Mapping[str, Any],
    colour: str | None,
    source: Source,
    user_id: uuid.UUID | None,
) -> tuple[Catalogue, str]:
    """A new value at the end of a list; returns the catalogue and the new value's code."""
    pick_list = _list(list_name)
    current = await config.load(session, wtype)
    await _check_version(session, wtype, current, expected_version)
    named = labels_of(labels, allow_none=False)
    if len(current.list_values(pick_list)) >= LIST_VALUES_MAX:
        raise invalid(field="labels", field_code="too_many")
    english = (named or {}).get("en", "").casefold()
    for value in current.list_values(pick_list):
        if value.labels and value.labels.get("en", "").casefold() == english:
            raise invalid(field="labels", field_code="duplicate_name")
    code = new_value_code()
    order = await session.scalar(
        select(func.coalesce(func.max(WorkItemReason.sort_order), -1) + 1).where(
            WorkItemReason.type == wtype.code, WorkItemReason.list == pick_list
        )
    )
    session.add(
        WorkItemReason(
            tenant_id=config.tenant_of(session),
            type=wtype.code,
            list=pick_list,
            code=code,
            labels=named,
            sort_order=int(order or 0),
            colour=_colour(colour),
        )
    )
    await session.flush()
    cat = await _bump(
        session,
        wtype,
        current=current,
        expected_version=expected_version,
        changes=[Change(f"{pick_list}.{code}", None, named)],
        changed_fields=[f"lists.{pick_list}"],
        source=source,
        user_id=user_id,
    )
    return cat, code


async def update_list_value(  # noqa: PLR0913, C901 - the change and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    list_name: str,
    code: str,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    """Rename / translate, colour, retire or bring back one value."""
    pick_list = _list(list_name)
    current = await config.load(session, wtype)
    await _check_version(session, wtype, current, expected_version)
    row = await session.scalar(
        select(WorkItemReason).where(
            WorkItemReason.type == wtype.code,
            WorkItemReason.list == pick_list,
            WorkItemReason.code == code,
        )
    )
    if row is None:
        raise NotFound(code="pick_list_value_not_found")
    changes: dict[str, Any] = {}
    if "labels" in values:
        # Seeded values may go back to the shipped labels (null); admin values must keep a name.
        changes["labels"] = labels_of(values["labels"], allow_none=not is_admin_code(code))
    if "colour" in values:
        changes["colour"] = _colour(values["colour"])
    if "disabled" in values:
        disabled = bool(values["disabled"])
        if disabled and code == OTHER_REASON and pick_list in _REASON_PICK_LISTS:
            # "Other" is the way out when no reason fits; text is asked for with it.
            raise invalid(field="disabled", field_code="value_required_by_system")
        if (
            disabled
            and len(
                [v for v in current.list_values(pick_list) if not v.disabled and v.code != code]
            )
            == 0
            and pick_list in _REASON_PICK_LISTS
        ):
            raise invalid(field="disabled", field_code="last_value")
        if disabled != (row.disabled_at is not None):
            changes["disabled_at"] = datetime.now(UTC) if disabled else None
    before = {k: getattr(row, k) for k in changes}
    changes = {k: v for k, v in changes.items() if before[k] != v}
    if changes:
        await session.execute(
            update(WorkItemReason)
            .where(
                WorkItemReason.type == wtype.code,
                WorkItemReason.list == pick_list,
                WorkItemReason.code == code,
            )
            .values(**changes)
        )

    def shown(name: str, value: Any) -> Any:  # noqa: ANN401 - JSON values
        if name == "disabled_at":
            return value is not None
        return value

    return await _bump(
        session,
        wtype,
        current=current,
        expected_version=expected_version,
        changes=[
            Change(
                f"{pick_list}.{code}.{'disabled' if k == 'disabled_at' else k}",
                shown(k, before[k]),
                shown(k, v),
            )
            for k, v in changes.items()
        ],
        changed_fields=[f"lists.{pick_list}"],
        source=source,
        user_id=user_id,
    )


async def reorder_list(  # noqa: PLR0913 - the order and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    list_name: str,
    *,
    expected_version: int,
    codes: Sequence[str],
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    """The new order of every value of a list (pickers and filters follow it at once)."""
    pick_list = _list(list_name)
    current = await config.load(session, wtype)
    await _check_version(session, wtype, current, expected_version)
    before = [v.code for v in current.list_values(pick_list)]
    if order_problems(before, codes):
        raise invalid(field="codes", field_code="order_must_list_every_value")
    if list(codes) == before:
        return current
    for index, code in enumerate(codes):
        await session.execute(
            update(WorkItemReason)
            .where(
                WorkItemReason.type == wtype.code,
                WorkItemReason.list == pick_list,
                WorkItemReason.code == code,
            )
            .values(sort_order=index)
        )
    return await _bump(
        session,
        wtype,
        current=current,
        expected_version=expected_version,
        changes=[Change(f"{pick_list}.order", before, list(codes))],
        changed_fields=[f"lists.{pick_list}"],
        source=source,
        user_id=user_id,
    )


# --- numbering (REQ-WI-002 AC4, REQ-ADM-045) ------------------------------------------------------


async def change_next_number(  # noqa: PLR0913 - the change and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    *,
    expected_version: int,
    next_number: int,
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    """The number the next record gets; never one already handed out (AC3)."""
    current = await config.load(session, wtype)
    await _check_version(session, wtype, current, expected_version)
    if next_number == current.last_number + 1:
        return current
    try:
        await set_next_number(session, wtype.counter_key, next_number)
    except NumberAlreadyUsedError as error:
        raise invalid(
            field="next_number", field_code="number_already_used", minimum=current.last_number + 1
        ) from error
    return await _bump(
        session,
        wtype,
        current=current,
        expected_version=expected_version,
        changes=[Change("next_number", current.last_number + 1, next_number)],
        changed_fields=["numbering"],
        source=source,
        user_id=user_id,
    )
