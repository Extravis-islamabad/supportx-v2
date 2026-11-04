"""The stage engine on stored records (ADR-041; REQ-WI-026, REQ-REL-014..017).

A staged type's model is read from the tenant's own rows (seeded from the type's declaration by
`catalogue.ensure_seeded`, editable later), so a tenant's edits win over the seeds. Moves are
planned by the pure `domain.stages.plan_move`; this module keeps the stage entries and runs the
owning type's guard. The record write itself (columns, history, events) stays in
`service.work_items`, beside every other status change.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_items.domain.lifecycle import ReasonList, ReasonMode, StatusCategory
from app.modules.work_items.domain.stages import (
    FIRST_LIFECYCLE,
    Entry,
    Move,
    PathDef,
    RailStage,
    SetBy,
    StageDef,
    StagedStatusDef,
    StageModel,
    StatusTransitionDef,
    rail,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemPathStage,
    WorkItemStage,
    WorkItemStageEntry,
    WorkItemStagePath,
    WorkItemStatus,
    WorkItemStatusTransition,
)
from app.modules.work_items.service import catalogue
from app.shared.ids import new_id


@dataclass(frozen=True)
class Refusal:
    """Why a guard refuses a move: a machine code and its params (labels in the UI)."""

    code: str
    params: Mapping[str, Any] = field(default_factory=dict)


class StageGuard(Protocol):
    """The owning type's rules around a move, inside its transaction (ADR-041 §5)."""

    async def check(self, session: AsyncSession, record: WorkItem, move: Move) -> list[Refusal]:
        """Refusals for this move (empty: allowed)."""
        ...

    async def on_entered(
        self, session: AsyncSession, record: WorkItem, entry: WorkItemStageEntry
    ) -> None:
        """React to entering a stage (for example, supersede that stage's old approvals)."""
        ...


_GUARDS: dict[str, StageGuard] = {}


def register_guard(type_code: str, guard: StageGuard) -> None:
    """Register the guard of a staged type (changes and releases register theirs)."""
    _GUARDS[type_code] = guard


def guard_of(type_code: str) -> StageGuard | None:
    """The registered guard of a type, if any."""
    return _GUARDS.get(type_code)


def staged(wtype: WorkItemType) -> bool:
    """Whether the type moves through stages."""
    return wtype.stages is not None


async def load_model(
    session: AsyncSession, wtype: WorkItemType, lifecycle_version: int | None = None
) -> StageModel:
    """The tenant's stage model of `wtype` for a life cycle version (seeding it first)."""
    await catalogue.ensure_seeded(session, wtype)
    version = lifecycle_version or FIRST_LIFECYCLE
    stages = await session.scalars(
        select(WorkItemStage)
        .where(WorkItemStage.type == wtype.code)
        .order_by(WorkItemStage.sort_order, WorkItemStage.code)
    )
    statuses = await session.scalars(
        select(WorkItemStatus)
        .where(WorkItemStatus.type == wtype.code, WorkItemStatus.stage.is_not(None))
        .order_by(WorkItemStatus.sort_order, WorkItemStatus.code)
    )
    paths = list(
        await session.scalars(
            # Disabled paths stay in the model: records already on one keep moving (lane A);
            # only new records are never placed on a disabled path.
            select(WorkItemStagePath).where(
                WorkItemStagePath.type == wtype.code,
                _version_in(WorkItemStagePath.lifecycle_version, version),
            )
        )
    )
    path_stages = list(
        await session.scalars(
            select(WorkItemPathStage)
            .where(WorkItemPathStage.type == wtype.code)
            .order_by(WorkItemPathStage.sort_order)
        )
    )
    transitions = await session.scalars(
        select(WorkItemStatusTransition).where(
            WorkItemStatusTransition.type == wtype.code,
            _version_in(WorkItemStatusTransition.lifecycle_version, version),
        )
    )
    return StageModel(
        stages=tuple(StageDef(s.code) for s in stages),
        statuses=tuple(
            StagedStatusDef(
                s.code,
                str(s.stage),
                StatusCategory(s.category),
                s.colour,
                s.completing,
                SetBy(s.set_by),
            )
            for s in statuses
        ),
        paths=tuple(
            PathDef(
                p.code,
                tuple(ps.stage for ps in path_stages if ps.path == p.code),
                frozenset(ps.stage for ps in path_stages if ps.path == p.code and ps.optional),
            )
            for p in paths
        ),
        transitions=tuple(
            StatusTransitionDef(
                t.from_status,
                t.to_status,
                ReasonMode(t.reason_mode),
                ReasonList(t.reason_list) if t.reason_list else None,
                t.permission,
                t.path,
                tuple(t.required_fields or ()),
            )
            for t in transitions
        ),
    )


def _version_in(column: Any, version: int) -> Any:  # noqa: ANN401 - SQL expressions
    """Rows for every version (NULL) or for this one."""
    return column.is_(None) | (column == version)


def first_columns(model: StageModel, path: str) -> dict[str, Any]:
    """Where a new record of a staged type starts: the path's first stage and its first status."""
    first = model.path(path).stages[0]
    return {
        "stage": first,
        "stage_path": path,
        "lifecycle_version": FIRST_LIFECYCLE,
        "status": model.first_status(first).code,
    }


async def enter(  # noqa: PLR0913 - the record, the stages and the move's reason, explicit
    session: AsyncSession,
    record: WorkItem,
    stages: Sequence[str],
    *,
    now: datetime,
    reason_code: str | None = None,
    reason_text: str | None = None,
) -> list[WorkItemStageEntry]:
    """Close the open entry and add one per stage entered, in order (never rewritten, §6).

    Passing through a stage on an automatic advance gives it an entry that is left at once, so
    the rail shows it done.
    """
    if not stages:
        return []
    await session.execute(
        update(WorkItemStageEntry)
        .where(WorkItemStageEntry.work_item_id == record.id, WorkItemStageEntry.left_at.is_(None))
        .values(left_at=now, updated_at=now)
    )
    entries = [
        WorkItemStageEntry(
            id=new_id(),
            tenant_id=catalogue.tenant_of(session),
            work_item_id=record.id,
            stage=stage,
            path=str(record.stage_path),
            entered_at=now,
            left_at=now if index < len(stages) - 1 else None,
            reason_code=reason_code if index == 0 else None,
            reason_text=reason_text if index == 0 else None,
        )
        for index, stage in enumerate(stages)
    ]
    session.add_all(entries)
    await session.flush()
    guard = guard_of(record.type)
    if guard is not None:
        for entry in entries:
            await guard.on_entered(session, record, entry)
    return entries


async def start(session: AsyncSession, record: WorkItem, *, now: datetime) -> None:
    """A new staged record's first entry (nothing for a type without stages)."""
    if record.stage is not None:
        await enter(session, record, [record.stage], now=now)


async def entries_of(session: AsyncSession, record: WorkItem) -> list[WorkItemStageEntry]:
    """A record's stage entries, oldest first."""
    return list(
        await session.scalars(
            select(WorkItemStageEntry)
            .where(WorkItemStageEntry.work_item_id == record.id)
            # Entries of one auto-advance share entered_at: the UUIDv7 id keeps their order.
            .order_by(WorkItemStageEntry.entered_at, WorkItemStageEntry.id)
        )
    )


async def rail_of(session: AsyncSession, wtype: WorkItemType, record: WorkItem) -> list[RailStage]:
    """The record's rail (ADR-041 §7), computed from its entries."""
    model = await load_model(session, wtype, record.lifecycle_version)
    rows = await entries_of(session, record)
    return rail(
        model,
        path=str(record.stage_path),
        current=str(record.stage),
        entries=[Entry(e.stage, e.entered_at, e.left_at) for e in rows],
    )
