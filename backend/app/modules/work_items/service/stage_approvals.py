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
from dataclasses import dataclass, replace

from sqlalchemy import func, select, update
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
from app.modules.work_items.service import catalogue, change_boards, record_roles
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
        # Through the record-roles overlay: a change's owner is its technician (F-02).
        held = await record_roles.role_holders(session, record, level.roles)
        unheld = any(held.get(r, ([], [])) == ([], []) for r in level.roles)
        people += [u for users, _ in held.values() for u in users]
        groups |= {g for _, grps in held.values() for g in grps}
    if groups:
        people += list(await session.scalars(users_in_groups(frozenset(groups))))
    return list(dict.fromkeys(people)), unheld


async def level_people(
    session: AsyncSession, record: WorkItem, level: rules.LevelApprovers
) -> tuple[list[uuid.UUID], bool]:
    """A level's people now and whether a named role had no holder (a workflow's node too)."""
    return await _candidates(session, record, level)


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


@dataclass(frozen=True)
class PlannedLevel:
    """Who a level names now, and why the administrators decide too (if they do).

    `barred` are the people left out, each with their reason, so a submit can warn before the
    approval opens (REQ-CHG-039: the fallback approver is named, never a silent skip).
    """

    level: rules.LevelApprovers
    named: tuple[uuid.UUID, ...]
    reason: rules.RouteReason | None
    barred: tuple[tuple[uuid.UUID, rules.RouteReason], ...]
    board_of: dict[uuid.UUID, change_boards.Reviewing]
    empty_board: change_boards.Reviewing | None
    advisory: tuple[uuid.UUID, ...] = ()  # optional board members: shown, never counted


async def plan_level(
    session: AsyncSession, record: WorkItem, settings: rules.StageApprovals, *, index: int
) -> PlannedLevel:
    """Level `index` (0-based) as it would open now; changes nothing."""
    level = settings.levels[index]
    people, unheld = await _candidates(session, record, level)
    boards = await _boards(session, record, level)
    board_of = {p: b for b in reversed(boards) for p in b.people}  # a person's first board
    people = list(dict.fromkeys([*people, *(p for b in boards for p in b.people)]))
    level = _with_board_rule(level, boards)
    active = await active_user_ids(session, people)
    barred = await segregated(session, record)
    named: list[uuid.UUID] = []
    left_out: list[tuple[uuid.UUID, rules.RouteReason]] = []
    reason: rules.RouteReason | None = rules.RouteReason.NO_HOLDER if unheld else None
    empty = next((b for b in boards if not b.people), None)
    if empty is not None:  # REQ-CHG-040: a board with no members yet
        reason = rules.RouteReason.BOARD_HAS_NO_MEMBERS
    for person in people:
        why: rules.RouteReason | None = None
        if person not in active:
            why = rules.RouteReason.APPROVER_INACTIVE
        elif not settings.self_approval and person == record.requester_id:
            why = rules.RouteReason.SELF_APPROVAL_BLOCKED
        elif person in barred:
            why = rules.RouteReason.SEGREGATION_OF_DUTIES
        if why is None:
            named.append(person)  # named: decides by being named, no extra permission needed
            continue
        left_out.append((person, why))
        reason = reason or why
    if not people and reason is None:
        reason = rules.RouteReason.NO_HOLDER
    active |= await active_user_ids(session, [p for b in boards for p in b.advisory])
    advisory = [
        p
        for b in boards
        for p in b.advisory
        if p in active and p not in barred and p not in named and p != record.requester_id
    ]
    for b in boards:
        for p in b.advisory:
            board_of.setdefault(p, b)
    return PlannedLevel(
        level,
        tuple(named),
        reason,
        tuple(left_out),
        board_of,
        empty,
        tuple(dict.fromkeys(advisory)),
    )


async def open_level(
    session: AsyncSession,
    record: WorkItem,
    settings: rules.StageApprovals,
    *,
    stage: str,
    index: int,
) -> list[WorkItemApproval]:
    """Level `index` (0-based) of the stage: one row per approver, never none."""
    plan = await plan_level(session, record, settings, index=index)
    rows = [
        _row(
            record,
            stage=stage,
            index=index,
            level=plan.level,
            approver=p,
            origin=rules.ApproverOrigin.NAMED,
            reason=None,
            board=plan.board_of.get(p),
        )
        for p in plan.named
    ]
    if plan.reason is not None:  # someone could not be named: the administrators decide too
        rows.append(
            _row(
                record,
                stage=stage,
                index=index,
                level=plan.level,
                approver=None,
                origin=rules.ApproverOrigin.ADMINISTRATORS,
                reason=plan.reason,
                board=plan.empty_board,
            )
        )
    for person in plan.advisory:  # Haider: recorded and shown, never counted
        advisory = _row(
            record,
            stage=stage,
            index=index,
            level=plan.level,
            approver=person,
            origin=rules.ApproverOrigin.NAMED,
            reason=None,
            board=plan.board_of.get(person),
        )
        advisory.advisory = True
        rows.append(advisory)
    for row in rows:
        row.self_approval = settings.self_approval
        session.add(row)
    await session.flush()
    for row in rows:
        await approval_event(session, record, row, "opened")
    if plan.empty_board is not None:  # REQ-CHG-040: the change manager hears of it
        from app.modules.work_items.service import reapproval  # noqa: PLC0415 - cycle

        await reapproval.notice(
            session,
            record,
            "board_has_no_members",
            stage=stage,
            board_id=plan.empty_board.board_id,
        )
    return rows


async def rerouted_in_this_save(
    session: AsyncSession, record_id: uuid.UUID
) -> list[WorkItemApproval]:
    """The administrators' rows this transaction opened, with why (for the audit, WP-045b S3).

    `created_at` defaults to now(), the transaction's start, so equal means "opened just now".
    """
    return list(
        await session.scalars(
            select(WorkItemApproval).where(
                WorkItemApproval.work_item_id == record_id,
                WorkItemApproval.origin == rules.ApproverOrigin.ADMINISTRATORS.value,
                WorkItemApproval.route_reason.is_not(None),
                WorkItemApproval.created_at == func.now(),
            )
        )
    )


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


async def withdraw_pending(session: AsyncSession, record: WorkItem, stage: str) -> None:
    """The stage's open approvals are not needed any more (an emergency override, D-144)."""
    await _close(session, record, await _rows(session, record, stage))


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
    if decided.advisory:  # an optional member's vote: shown, never counted (Haider)
        return
    outcome = rules.level_outcome(
        rules.LevelRule(decided.rule or rules.LevelRule.ANY),
        [rules.ApprovalState(r.state) for r in level_rows if not r.advisory],
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
    if outcome is rules.LevelOutcome.APPROVED:  # WP-045b S4: keep what was approved
        from app.modules.work_items.service import reapproval  # noqa: PLC0415 - as above

        await reapproval.take(session, record, stage)
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
        """Reaching the raising status opens level 1, or moves on when nobody can approve."""
        del move
        await raise_or_move_on(session, self.wtype, record)


async def raise_or_move_on(session: AsyncSession, wtype: WorkItemType, record: WorkItem) -> None:
    """The record's stage asks for its approvals now, if it is at the raising status.

    Level 1 opens (once: not while it is open). A stage whose approvals were removed moves on by
    itself instead (QA10-P4-29): its outcome statuses are set by approvals only, so a record at
    the status that used to raise them would wait for a decision nobody can make. Every path that
    may raise a stage's approvals calls this (a move's guard, a send-back for re-approval), so all
    of them behave the same (lane A's review).
    """
    settings = await settings_of(session, wtype, record, record.stage)
    if settings is None:
        await _move_on_without_approvers(session, wtype, record)
        return
    if record.status != settings.raised_by:
        return
    stage = str(record.stage)
    if any(r.state == rules.ApprovalState.PENDING for r in await _rows(session, record, stage)):
        return
    await open_level(session, record, settings, stage=stage, index=0)


async def _move_on_without_approvers(
    session: AsyncSession, wtype: WorkItemType, record: WorkItem
) -> None:
    """With nothing to approve, take the approved outcome at once, recorded as the system's."""
    default = wtype.stage_approvals.get(str(record.stage))
    if default is None or record.status != default.get("raised_by"):
        return
    # Imported here: the work item service imports the stage guard registered below.
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - see above

    await items.system_stage_move(
        session, wtype, record, target=str(default["approved"]), source="system"
    )


def register(types: Sequence[WorkItemType]) -> None:
    """Register the guard for every staged type with approvals (releases)."""
    for wtype in types:
        if wtype.stages is not None and wtype.code is WorkItemTypeCode.RELEASE:
            stage_service.register_guard(wtype.code, StagedApprovalGuard(wtype))
