"""Approvals of a staged record's stages (WP-058a s5; REQ-REL-031; ADR-041).

The work-item approval engine (WP-030; lane A's review), with two additions for staged types:
each approval row names the record's stage it belongs to (`record_stage`) and how its level is
decided (`rule`: any, all, majority). The stage's settings (`work_item_stages.approvals`) say which
status raises them, which system-only statuses their outcome sets, and the levels with their
approvers: people, groups (each member) and record roles (the holders when the level opens,
REQ-REL-023 AC2).

A named approver decides their approval by being named (as in WP-030), with no extra permission;
`releases.approve` (admins by default) or `work_items.approve_any` decides approvals one is not
named on. Nobody is left without someone who can decide: an inactive approver, a role nobody
holds, or a requester barred by segregation of duties is replaced by one row for the approval
administrators, with the reason shown.

The release guard registered here keeps the rules inside the move's transaction: it opens level 1
when a record reaches the raising status, closes a stage's open approvals when the record goes back,
and refuses a person's move to a completing status while that stage still needs its approvals.
"""

import uuid
from collections.abc import Sequence
from dataclasses import replace

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import active_user_ids
from app.modules.organization import users_in_groups
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.change_boards import BoardRule
from app.modules.work_items.domain.stages import Move, SetBy
from app.modules.work_items.domain.types import TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemApproval,
    WorkItemRoleHolder,
    WorkItemStage,
    WorkItemStageEntry,
)
from app.modules.work_items.service import catalogue, change_boards
from app.modules.work_items.service import stages as stage_service
from app.modules.work_items.service.approval_stage import approval_event
from app.shared.history import Source

APPROVALS_PENDING = "approvals_pending"  # a guard refusal code (labels: action_reason.*)


async def settings_of(
    session: AsyncSession, wtype: WorkItemType, record: WorkItem, stage: str | None
) -> rules.StageApprovals | None:
    """The stage's approval settings (None: it needs none)."""
    if stage is None:
        return None
    row = await session.get(WorkItemStage, (catalogue.tenant_of(session), record.type, stage))
    if row is None or not row.approvals:
        return None
    model = await stage_service.load_model(session, wtype, record.lifecycle_version)
    statuses = {s.code: s.set_by == SetBy.SYSTEM for s in model.statuses_of(stage)}
    settings, _problems = rules.parse_stage_approvals(
        row.approvals,
        stage_statuses=statuses,
        roles=wtype.roles,
        boards=wtype.code is WorkItemTypeCode.CHANGE,
    )
    return settings  # checked on save; a status removed since makes it None (no approvals)


async def _rows(session: AsyncSession, record: WorkItem, stage: str) -> list[WorkItemApproval]:
    return list(
        await session.scalars(
            select(WorkItemApproval)
            .where(
                WorkItemApproval.work_item_id == record.id,
                WorkItemApproval.record_stage == stage,
                WorkItemApproval.deleted_at.is_(None),
            )
            .order_by(WorkItemApproval.stage, WorkItemApproval.created_at)
        )
    )


async def _candidates(
    session: AsyncSession, record: WorkItem, level: rules.LevelApprovers
) -> tuple[list[uuid.UUID], bool]:
    """The level's people now (in order, once each), and whether a named role had no holder."""
    people: list[uuid.UUID] = list(level.user_ids)
    groups = set(level.group_ids)
    unheld = False
    if level.roles:
        held = (
            await session.execute(
                select(
                    WorkItemRoleHolder.role, WorkItemRoleHolder.user_id, WorkItemRoleHolder.group_id
                ).where(
                    WorkItemRoleHolder.work_item_id == record.id,
                    WorkItemRoleHolder.role.in_(level.roles),
                )
            )
        ).all()
        unheld = {r.role for r in held} != set(level.roles)
        people += [r.user_id for r in held if r.user_id]
        groups |= {r.group_id for r in held if r.group_id}
    if groups:
        people += list(await session.scalars(users_in_groups(frozenset(groups))))
    return list(dict.fromkeys(people)), unheld


async def segregated(
    session: AsyncSession, record: WorkItem, *, strict: bool | None = None
) -> set[uuid.UUID]:
    """People who may not approve this record: holders of its type's segregated roles.

    The requester is kept out by the self-approval rule; these are the others (REQ-CHG-039,
    Haider's decision): by default the people assigned (a change's implementer) and the record's
    owner (its technician). Strict also bars every member of an implementing group; `None` takes
    the tenant's setting (`segregation_strict`, WP-045b S3), recommended for regulated
    organisations.
    """
    wtype = TYPES.get(WorkItemTypeCode(record.type))
    if wtype is None or not wtype.segregated_roles:
        return set()
    if strict is None:
        strict = (await catalogue.load(session, wtype)).segregation_strict
    held = (
        await session.execute(
            select(WorkItemRoleHolder.user_id, WorkItemRoleHolder.group_id).where(
                WorkItemRoleHolder.work_item_id == record.id,
                WorkItemRoleHolder.role.in_(wtype.segregated_roles),
            )
        )
    ).all()
    people = {r.user_id for r in held if r.user_id}
    if record.technician_id is not None:
        people.add(record.technician_id)  # the change owner
    groups = frozenset(r.group_id for r in held if r.group_id)
    if strict and groups:
        people |= set(await session.scalars(users_in_groups(groups)))
    return people


async def open_level(
    session: AsyncSession,
    record: WorkItem,
    settings: rules.StageApprovals,
    *,
    stage: str,
    index: int,
) -> list[WorkItemApproval]:
    """Level `index` (0-based) of the stage: one row per approver, never none."""
    level = settings.levels[index]
    people, unheld = await _candidates(session, record, level)
    boards = await _boards(session, record, level)
    board_of = {p: b for b in reversed(boards) for p in b.people}  # a person's first board
    people = list(dict.fromkeys([*people, *(p for b in boards for p in b.people)]))
    level = _with_board_rule(level, boards)
    active = await active_user_ids(session, people)
    barred = await segregated(session, record)
    named: list[uuid.UUID] = []
    reason: rules.RouteReason | None = rules.RouteReason.NO_HOLDER if unheld else None
    empty = next((b for b in boards if not b.people), None)
    if empty is not None:  # REQ-CHG-040: a board with no members yet
        reason = rules.RouteReason.BOARD_HAS_NO_MEMBERS
    for person in people:
        if person not in active:
            reason = reason or rules.RouteReason.APPROVER_INACTIVE
            continue
        if not settings.self_approval and person == record.requester_id:
            reason = reason or rules.RouteReason.SELF_APPROVAL_BLOCKED
            continue
        if person in barred:
            reason = reason or rules.RouteReason.SEGREGATION_OF_DUTIES
            continue
        named.append(person)  # named: decides by being named, no extra permission needed
    if not people and reason is None:
        reason = rules.RouteReason.NO_HOLDER
    rows = [
        _row(
            record,
            stage=stage,
            index=index,
            level=level,
            approver=p,
            origin=rules.ApproverOrigin.NAMED,
            reason=None,
            board=board_of.get(p),
        )
        for p in named
    ]
    if reason is not None:  # someone could not be named: the administrators decide for them
        rows.append(
            _row(
                record,
                stage=stage,
                index=index,
                level=level,
                approver=None,
                origin=rules.ApproverOrigin.ADMINISTRATORS,
                reason=reason,
                board=empty,
            )
        )
    for row in rows:
        row.self_approval = settings.self_approval
        session.add(row)
    await session.flush()
    for row in rows:
        await approval_event(session, record, row, "opened")
    return rows


async def _boards(
    session: AsyncSession, record: WorkItem, level: rules.LevelApprovers
) -> list[change_boards.Reviewing]:
    """The change advisory boards the level names (WP-045b S3), chosen for this record."""
    if not level.boards:
        return []
    wtype = TYPES[WorkItemTypeCode(record.type)]
    every = (await catalogue.load(session, wtype)).cab_every_match
    return await change_boards.reviewing(session, record, level.boards, every_match=every)


def _with_board_rule(
    level: rules.LevelApprovers, boards: Sequence[change_boards.Reviewing]
) -> rules.LevelApprovers:
    """A level of boards only decides by its (first) board's rule (REQ-CHG-042).

    A level naming people, groups or roles as well keeps its own rule. The chair's tie-break
    (D-146) comes with lane C's WP-048b S2; until then a chaired board decides by majority.
    """
    if not boards or level.user_ids or level.group_ids or level.roles:
        return level
    rule = boards[0].rule
    # Lane C wires the board's chair into level_outcome(chair=, chair_vote=) with WP-048b S2.
    if rule is BoardRule.MAJORITY_WITH_CHAIR:
        return replace(level, rule=rules.LevelRule.MAJORITY)
    return replace(level, rule=rules.LevelRule(rule.value))


def _row(  # noqa: PLR0913 - one approval row, explicit
    record: WorkItem,
    *,
    stage: str,
    index: int,
    level: rules.LevelApprovers,
    approver: uuid.UUID | None,
    origin: rules.ApproverOrigin,
    reason: rules.RouteReason | None,
    board: change_boards.Reviewing | None = None,
) -> WorkItemApproval:
    return WorkItemApproval(
        board_id=board.board_id if board else None,
        board_reason=board.reason if board else None,
        tenant_id=record.tenant_id,
        work_item_id=record.id,
        stage=index + 1,  # the engine's levels count from 1
        record_stage=stage,
        rule=level.rule.value,
        approver_id=approver,
        origin=origin.value,
        route_reason=reason.value if reason else None,
        state=rules.ApprovalState.PENDING.value,
    )


async def _close(session: AsyncSession, record: WorkItem, rows: Sequence[WorkItemApproval]) -> None:
    """Pending rows no longer needed (the level was decided, or the record went back)."""
    pending = [r for r in rows if r.state == rules.ApprovalState.PENDING]
    if not pending:
        return
    await session.execute(
        update(WorkItemApproval)
        .where(WorkItemApproval.id.in_([r.id for r in pending]))
        .values(state=rules.ApprovalState.NOT_NEEDED.value, version=WorkItemApproval.version + 1)
        .execution_options(synchronize_session="fetch")
    )
    # Imported here: the links service reaches the approval decisions, which import this module.
    from app.modules.work_items.service.approvals import LINK_OBJECT  # noqa: PLC0415 - see above
    from app.shared import action_links  # noqa: PLC0415 - with the line above

    for row in pending:
        await approval_event(session, record, row, "closed")
        await action_links.revoke_for(session, LINK_OBJECT, row.id)


async def after_decision(
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    decided: WorkItemApproval,
    *,
    source: Source,
) -> None:
    """A staged approval was decided: its level's rule says what happens (REQ-REL-031 AC3)."""
    stage = str(decided.record_stage)
    settings = await settings_of(session, wtype, record, stage)
    rows = await _rows(session, record, stage)
    level_rows = [r for r in rows if r.stage == decided.stage]
    outcome = rules.level_outcome(
        rules.LevelRule(decided.rule or rules.LevelRule.ANY),
        [rules.ApprovalState(r.state) for r in level_rows],
    )
    if outcome is rules.LevelOutcome.PENDING or settings is None:
        return
    await _close(session, record, level_rows)
    # Imported here: the work item service imports the stage guard registered below.
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - see above

    if outcome is rules.LevelOutcome.APPROVED and decided.stage < len(settings.levels):
        await open_level(session, record, settings, stage=stage, index=decided.stage)
        return
    target = settings.approved if outcome is rules.LevelOutcome.APPROVED else settings.rejected
    await items.system_stage_move(session, wtype, record, target=target, source=source)


class StagedApprovalGuard:
    """The engine's hooks for approvals (ADR-041 §5); registered for releases."""

    def __init__(self, wtype: WorkItemType) -> None:
        self.wtype = wtype

    async def check(
        self, session: AsyncSession, record: WorkItem, move: Move
    ) -> list[stage_service.Refusal]:
        """The release's own refusals for a move.

        A person may not complete a stage that still needs its approvals; a parent may not enter
        deployment before its sub-releases pass testing (REQ-REL-037).
        """
        from app.modules.work_items.service import release_links  # noqa: PLC0415 - cycle

        refusals = await release_links.sub_release_refusals(session, self.wtype, record, move)
        if move.target.set_by == SetBy.SYSTEM or not move.target.completing:
            return refusals
        settings = await settings_of(session, self.wtype, record, move.target.stage)
        if settings is None:
            return refusals
        return [*refusals, stage_service.Refusal(APPROVALS_PENDING, {"stage": move.target.stage})]

    async def on_entered(
        self, session: AsyncSession, record: WorkItem, entry: WorkItemStageEntry
    ) -> None:
        """Going back or on: the open approvals of the other stages are not needed any more."""
        others = list(
            await session.scalars(
                select(WorkItemApproval).where(
                    WorkItemApproval.work_item_id == record.id,
                    WorkItemApproval.record_stage.is_not(None),
                    WorkItemApproval.record_stage != entry.stage,
                    WorkItemApproval.state == rules.ApprovalState.PENDING,
                )
            )
        )
        await _close(session, record, others)

    async def on_moved(self, session: AsyncSession, record: WorkItem, move: Move) -> None:
        """Reaching the raising status opens level 1 (once: not while it is open)."""
        settings = await settings_of(session, self.wtype, record, record.stage)
        if settings is None or record.status != settings.raised_by:
            return
        stage = str(record.stage)
        if any(r.state == rules.ApprovalState.PENDING for r in await _rows(session, record, stage)):
            return
        await open_level(session, record, settings, stage=stage, index=0)
        del move


def register(types: Sequence[WorkItemType]) -> None:
    """Register the guard for every staged type with approvals (releases)."""
    for wtype in types:
        if wtype.stages is not None and wtype.code is WorkItemTypeCode.RELEASE:
            stage_service.register_guard(wtype.code, StagedApprovalGuard(wtype))
