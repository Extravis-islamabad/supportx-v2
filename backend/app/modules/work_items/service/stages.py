"""The stage engine on stored records (ADR-041; REQ-WI-026, REQ-REL-014..017).

A staged type's model is read from the tenant's own rows (seeded from the type's declaration by
`catalogue.ensure_seeded`, editable later), so a tenant's edits win over the seeds. Moves are
planned by the pure `domain.stages.plan_move`; this module keeps the stage entries and runs the
owning type's guard. The record write itself (columns, history, events) stays in
`service.work_items`, beside every other status change.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import AccessRule
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
    read_only_in,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemPathStage,
    WorkItemRoleHolder,
    WorkItemStage,
    WorkItemStageEntry,
    WorkItemStagePath,
    WorkItemStageSchedule,
    WorkItemStatus,
    WorkItemStatusTransition,
    WorkItemTemplate,
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


# A guard may also define `async on_moved(session, record, move)`, called after every move of
# the record in the same transaction (releases open a stage's approvals from it). Optional, so a
# guard written against the protocol above keeps working.
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


async def enabled_paths(session: AsyncSession, wtype: WorkItemType) -> set[str]:
    """The paths a new record or a template may be put on (disabled ones are kept for old ones)."""
    await catalogue.ensure_seeded(session, wtype)
    return set(
        await session.scalars(
            select(WorkItemStagePath.code).where(
                WorkItemStagePath.type == wtype.code, WorkItemStagePath.disabled_at.is_(None)
            )
        )
    )


EDIT, MOVE_OUT = "edit", "move_out"  # the two kinds of stage access (REQ-REL-019)
# A rule that names only groups or people could leave a record in a stage nobody may move: those
# who configure the service desk always pass (lane B's review; ADR-041 §8).
ALWAYS_ADMITTED = frozenset({"config.service_desk", "settings.manage"})


async def access_rule(
    session: AsyncSession, record: WorkItem, kind: str, stage: str | None = None
) -> AccessRule | None:
    """The stage's access rule of `kind` for the record (None: no stage or no rule).

    Named roles resolve to the record's current holders, people and groups (REQ-REL-019).
    """
    code = stage or record.stage
    if code is None:
        return None
    row = await session.get(WorkItemStage, (catalogue.tenant_of(session), record.type, code))
    rule = ((row.access if row is not None else None) or {}).get(kind) or {}
    roles = [str(r) for r in rule.get("roles") or ()]
    role_users, role_groups = await _role_holders(session, record, roles)
    named = AccessRule(
        group_ids=frozenset(uuid.UUID(str(g)) for g in rule.get("group_ids") or ()) | role_groups,
        permissions=frozenset(str(p) for p in rule.get("permissions") or ()),
        user_ids=role_users,
    )
    if named.empty() and not roles:  # a cleared rule ({"group_ids": []}) restricts nobody
        return None
    # A rule naming only roles nobody holds yet still admits the configurers (never stranded).
    return AccessRule(
        group_ids=named.group_ids,
        permissions=named.permissions | ALWAYS_ADMITTED,
        user_ids=named.user_ids,
    )


async def _role_holders(
    session: AsyncSession, record: WorkItem, roles: Sequence[str]
) -> tuple[frozenset[uuid.UUID], frozenset[uuid.UUID]]:
    """The people and groups holding any of `roles` on the record now."""
    if not roles:
        return frozenset(), frozenset()
    rows = (
        await session.execute(
            select(WorkItemRoleHolder.user_id, WorkItemRoleHolder.group_id).where(
                WorkItemRoleHolder.work_item_id == record.id, WorkItemRoleHolder.role.in_(roles)
            )
        )
    ).all()
    return (
        frozenset(r.user_id for r in rows if r.user_id),
        frozenset(r.group_id for r in rows if r.group_id),
    )


async def template_rules(session: AsyncSession, record: WorkItem) -> Mapping[str, Any] | None:
    """The stage rules of the record's template (None when it has none)."""
    if record.template_id is None:
        return None
    template = await session.get(WorkItemTemplate, record.template_id)
    return template.stage_rules if template is not None else None


async def read_only_fields(session: AsyncSession, record: WorkItem) -> frozenset[str]:
    """Fields the record's template makes read-only in its current stage (REQ-REL-013 AC1)."""
    if record.stage is None or record.template_id is None:
        return frozenset()
    template = await session.get(WorkItemTemplate, record.template_id)
    return read_only_in(template.stage_rules if template else None, record.stage)


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
    left: str | None = None,
    reason_code: str | None = None,
    reason_text: str | None = None,
) -> list[WorkItemStageEntry]:
    """Close the open entry and add one per stage entered, in order (never rewritten, §6).

    Passing through a stage on an automatic advance gives it an entry that is left at once, so
    the rail shows it done.
    """
    if not stages:
        return []
    await _stamp_actual(session, record, stages, left=left, now=now)
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


async def _stamp_actual(
    session: AsyncSession,
    record: WorkItem,
    stages: Sequence[str],
    *,
    left: str | None,
    now: datetime,
) -> None:
    """The engine's actual dates (REQ-REL-026 AC1).

    The stage left ends; each stage entered starts (its first start kept on going back); each
    stage passed through on an automatic advance ends at once.
    """
    tenant = catalogue.tenant_of(session)
    if left is not None:
        await _upsert_schedule(session, tenant, record.id, left, actual_end=now)
    for index, stage in enumerate(stages):
        passed = index < len(stages) - 1
        await _upsert_schedule(
            session, tenant, record.id, stage, actual_start=now, actual_end=now if passed else None
        )


async def _upsert_schedule(  # noqa: PLR0913 - the row's key and the dates, explicit
    session: AsyncSession,
    tenant: uuid.UUID,
    record_id: uuid.UUID,
    stage: str,
    *,
    actual_start: datetime | None = None,
    actual_end: datetime | None = None,
) -> None:
    row = await session.get(WorkItemStageSchedule, (tenant, record_id, stage))
    if row is None:
        row = WorkItemStageSchedule(tenant_id=tenant, work_item_id=record_id, stage=stage)
        session.add(row)
    if actual_start is not None and row.actual_start is None:
        row.actual_start = actual_start
    if actual_start is not None:
        row.actual_end = None  # entered again (going back): open until it is left
    if actual_end is not None:
        row.actual_end = actual_end
    row.version = (row.version or 0) + 1
    await session.flush()


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
