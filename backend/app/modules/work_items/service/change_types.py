"""A new change's type, model and path (WP-045a D2; REQ-CHG-005, -006, -011).

The change type comes from the create request or the template's defaults (a template binds the
type, file 05 §3). Its model decides the path when the template names none, and a standard
change is approved at creation: the system's move to `submission_accepted`, which completes
submission, with a history line saying so (never an unexplained tick, REQ-CHG-006 AC1).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import person_placement
from app.modules.work_items.domain import changes as rules
from app.modules.work_items.domain.templates import PickList
from app.modules.work_items.domain.types import WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemChangeDetails,
    WorkItemRoleHolder,
    WorkItemStageSchedule,
    WorkItemTemplate,
)
from app.modules.work_items.service import stages as stage_service
from app.modules.work_items.service.catalogue import Catalogue
from app.shared.history import Change

# The create request's fields that only changes take.
CREATE_FIELDS = rules.DETAIL_FIELDS
ONLY_CHANGES = (*rules.DETAIL_FIELDS, *rules.RETROSPECTIVE_FIELDS)


@dataclass(frozen=True)
class NewChange:
    """What a new change starts with: its own fields, its model and its path."""

    details: Mapping[str, str]
    model: rules.ChangeModel | None
    path: str | None
    # Logged after the fact (REQ-CHG-004): its actual start and end, else None.
    retrospective: tuple[datetime, datetime] | None = None


def problems_for(wtype: WorkItemType, values: Mapping[str, Any]) -> list[tuple[str, str]]:
    """A change's fields sent for another type are refused, not dropped."""
    if wtype.code is WorkItemTypeCode.CHANGE:
        return []
    return [(n, "not_allowed") for n in ONLY_CHANGES if values.get(n) not in (None, False)]


def prepare(
    wtype: WorkItemType,
    cat: Catalogue,
    values: Mapping[str, Any],
    template: WorkItemTemplate,
) -> tuple[NewChange | None, list[tuple[str, str]]]:
    """The new change's type, reason, model and path; (None, []) for other types."""
    if wtype.code is not WorkItemTypeCode.CHANGE:
        return None, []
    defaults = template.defaults or {}
    chosen = {
        n: values.get(n) if values.get(n) is not None else defaults.get(n) for n in CREATE_FIELDS
    }
    problems: list[tuple[str, str]] = []
    for name, pick in (
        ("change_type", PickList.CHANGE_TYPE),
        ("change_reason", PickList.CHANGE_REASON),
    ):
        value = chosen[name]
        if value is not None and value not in cat.reason_codes(pick):
            problems.append((name, "invalid_choice"))
    problems += rules.retrospective_problems(values, datetime.now(UTC))
    times = (
        (values["actual_start"], values["actual_end"])
        if values.get("retrospective") and not problems
        else None
    )
    change_type = chosen["change_type"]
    if problems or change_type is None:
        details = {n: v for n, v in chosen.items() if v is not None}
        return NewChange(details, None, None, times), problems
    attributes = next(
        (v.attributes for v in cat.list_values(PickList.CHANGE_TYPE) if v.code == change_type),
        None,
    )
    model = rules.model_of(change_type, attributes)
    # A template binds a type and its path (file 05 §3, REQ-CHG-022); a type chosen on the form
    # that differs from the template's takes its own path, so any template serves every type.
    bound = defaults.get("change_type") == change_type and template.stage_path is not None
    path = template.stage_path if bound else rules.path_of(change_type, model)
    return NewChange({n: v for n, v in chosen.items() if v is not None}, model, path, times), []


def pre_approved(new: NewChange | None) -> bool:
    """Whether the new change is approved at creation (a standard model, REQ-CHG-006).

    A retrospective change is not: it enters at its review instead (REQ-CHG-004).
    """
    return new is not None and new.model is rules.ChangeModel.STANDARD and new.retrospective is None


async def retrospective_start(
    session: AsyncSession, wtype: WorkItemType, new: NewChange | None, columns: dict[str, Any]
) -> None:
    """A retrospective change starts at its review, in that stage's first status (AC2)."""
    if new is None or new.retrospective is None or not columns:
        return
    model = await stage_service.load_model(session, wtype)
    stage = rules.RETROSPECTIVE_STAGE
    if stage in model.path(str(columns["stage_path"])).stages:
        columns.update({"stage": stage, "status": model.first_status(stage).code})


async def store(session: AsyncSession, record: WorkItem, new: NewChange | None) -> dict[str, Any]:
    """Keep a new change's own fields (0101); what was kept, for the creation's history.

    A retrospective one is marked so, and its implementation keeps the actual times (AC1).
    """
    own: dict[str, Any] = dict(new.details) if new is not None else {}
    if new is not None and new.retrospective is not None:
        own["retrospective"] = True
        started, ended = new.retrospective
        session.add(
            WorkItemStageSchedule(
                tenant_id=record.tenant_id,
                work_item_id=record.id,
                stage=rules.IMPLEMENTATION,
                actual_start=started,
                actual_end=ended,
                version=1,
            )
        )
    if own:
        session.add(
            WorkItemChangeDetails(tenant_id=record.tenant_id, work_item_id=record.id, **own)
        )
        await session.flush()
    return own


LINE_MANAGER = "line_manager"


def _holding(users: list[uuid.UUID]) -> dict[str, list[str]]:
    """A role's holders as history shows them (as set_role writes them)."""
    return {"users": [str(u) for u in users], "groups": []}


async def _line_manager_rows(
    session: AsyncSession, record_id: uuid.UUID
) -> list[WorkItemRoleHolder]:
    return list(
        await session.scalars(
            select(WorkItemRoleHolder).where(
                WorkItemRoleHolder.work_item_id == record_id,
                WorkItemRoleHolder.role == LINE_MANAGER,
            )
        )
    )


async def fill_line_manager(
    session: AsyncSession, record: WorkItem, *, was_requester: uuid.UUID | None = None
) -> list[Change]:
    """The line manager from the requester's reporting manager (REQ-CHG-036); history lines.

    On creation (`was_requester` None) and when the requester changes. A role someone set by
    hand is kept: it is replaced only while it still holds the earlier requester's manager (or
    nobody). No manager: the role stays empty, and a stage needing it goes to the approval
    administrators, saying why (the approvals' `no_holder`, AC2).
    """
    if record.type != WorkItemTypeCode.CHANGE:
        return []
    rows = await _line_manager_rows(session, record.id)
    held = [r.user_id for r in rows if r.user_id is not None]
    if any(r.group_id is not None for r in rows):
        return []  # a group set by hand
    before = (
        None
        if was_requester is None
        else (await person_placement(session, was_requester)).manager_id
    )
    if held and held != [before]:
        return []  # someone chose the line manager: theirs stays
    manager = (await person_placement(session, record.requester_id)).manager_id
    now = [manager] if manager is not None else []
    if now == held:
        return []
    await session.execute(
        delete(WorkItemRoleHolder).where(
            WorkItemRoleHolder.work_item_id == record.id, WorkItemRoleHolder.role == LINE_MANAGER
        )
    )
    session.add_all(
        WorkItemRoleHolder(
            tenant_id=record.tenant_id,
            work_item_id=record.id,
            type=record.type,
            role=LINE_MANAGER,
            user_id=u,
        )
        for u in now
    )
    await session.flush()
    return [Change(f"role.{LINE_MANAGER}", _holding(held), _holding(now))]
