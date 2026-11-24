"""A service request's approval stages (WP-047a S2a; REQ-SR-029..032).

A request whose item has stages beyond today's single one keeps them as a snapshot on the
record (`approval_stages`, `domain/stage_snapshot`), and its stages open one step at a time:

- A stage's condition (the shared DSL over the answers and the quantity) that does not hold
  makes a `skipped` row with `condition_not_met`, shown with the condition; it counts as passed.
- Its approvers resolve now: each kind to people, each person checked active and able to sign
  in. The requester never approves their own request (left out and audited, condition 2);
  nobody left means the backup, else the approval administrators, with the reason (condition 3).
- A decision settles the stage by its rule (`level_outcome`; a majority tie rejects, D-146). A
  rejected step ends the request's approval and withdraws the step's other pending rows; an
  approved one opens the next step; the last one finishes the request as today.

Items with one stage of today's kinds never come here (condition 5): the catalog says which,
through `RequestItem.uses_stages`, the same answer that gates saving the item.
"""

import contextlib
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import assets, cmdb, organization, service_catalog
from app.modules.audit import WORKER as AUDIT_WORKER
from app.modules.audit import record as record_audit
from app.modules.identity_access import active_user_ids, person_placement
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain import request_stages as progression
from app.modules.work_items.domain import stage_snapshot
from app.modules.work_items.domain.approval_reminders import family_states
from app.modules.work_items.domain.delegations import current_round
from app.modules.work_items.domain.request_stages import Candidate, Opened, StagePlan
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.infra.models import WorkItem, WorkItemApproval
from app.modules.work_items.service import approval_rows, asset_links
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service.approval_stage import approval_event, requested_for
from app.modules.work_items.service.followers import RECORD_TYPE
from app.shared.conditions import matches
from app.shared.history import Change, record_changes

REQUESTER_LEFT_OUT = "service_request.approver_was_requester"
# WP-047a S2b (REQ-SR-033): a stage approved with nobody asked, audited with why.
APPROVED_AUTOMATICALLY = "service_request.approved_automatically"
AUTOMATIC_FIELD = "approval_automatic"  # its history line on the record
MANAGER_KINDS = frozenset({"requested_for_manager", "manager_of_manager", "department_head"})


def snapshot_of(
    item: service_catalog.RequestItem, *, tenant_earlier: bool = False
) -> tuple[stage_snapshot.SnapStage, ...]:
    """The item's stages as the request keeps them (configuration only, condition 1).

    "Approved earlier" is resolved now (REQ-SR-033, the coordinator's Q1): the item's own
    setting, else the tenant's, so a later change to either never moves a request in flight.
    """
    return tuple(
        stage_snapshot.SnapStage(
            approvers=tuple(
                stage_snapshot.SnapApprover(a.kind, a.person_id, a.group_id, a.question_key)
                for a in s.approvers
            ),
            rule=s.rule,
            backup_id=s.backup_id,
            comments_required=s.comments_required,
            self_approval=s.self_approval,
            parallel_group=s.parallel_group,
            condition=s.condition,
            auto_earlier=tenant_earlier if s.auto_earlier is None else s.auto_earlier,
            auto_rules=tuple(
                stage_snapshot.SnapRule(dict(name), dict(condition))
                for name, condition in s.auto_rules
            ),
            escalate_to=s.escalate_to,
        )
        for s in item.stages
    )


def staged(item: service_catalog.RequestItem | None) -> bool:
    """Whether a new request from `item` runs on the stages (else today's single stage)."""
    return item is not None and item.needs_approval and item.uses_stages


def _values(record: WorkItem) -> dict[str, Any]:
    """What a stage's condition reads: the form's answers and the quantity."""
    return {**(record.answers or {}), "quantity": record.quantity}


async def _rule_values(session: AsyncSession, record: WorkItem) -> dict[str, Any]:
    """What an automatic rule reads (REQ-SR-033).

    The condition's values, and the requester's groups (`eq` a group: they are a member).
    """
    groups = (await organization.memberships(session, record.requester_id)).group_ids
    return {**_values(record), service_catalog.REQUESTER_GROUPS: sorted(str(g) for g in groups)}


def _earlier_approvers(rows: Sequence[WorkItemApproval], number: int) -> dict[uuid.UUID, int]:
    """Who approved an earlier stage of this request themselves, and the first such stage.

    Only their own decisions count: an automatic approval never carries on to a later stage.
    """
    found: dict[uuid.UUID, int] = {}
    for row in rows:
        if (
            row.stage < number
            and row.state == rules.ApprovalState.APPROVED
            and row.channel != rules.DecisionChannel.AUTOMATIC
            and row.approver_id is not None
            and row.decided_by == row.approver_id
        ):
            found[row.approver_id] = min(row.stage, found.get(row.approver_id, row.stage))
    return found


async def _automatic(  # noqa: PLR0913 - the stage, its row and why, explicit
    session: AsyncSession,
    record: WorkItem,
    number: int,
    row: WorkItemApproval,
    *,
    rule_name: Mapping[str, str] | None = None,
    keys: Sequence[str] = (),
) -> None:
    """Audit an automatic approval and name it in the record's history (condition 2).

    The rule's name and the answer keys it read; never the answers themselves.
    """
    details: dict[str, Any] = {
        "display_id": record.display_id,
        "stage": number,
        "reason": row.auto_reason,
        "ref": row.auto_ref,
    }
    if row.approver_id is not None:
        details["approver_id"] = str(row.approver_id)
    if keys:
        details["keys"] = list(keys)
    await record_audit(
        session,
        action_code=APPROVED_AUTOMATICALLY,
        facts=AUDIT_WORKER,
        object_type="service_request",
        object_id=str(record.id),
        details=details,
    )
    said: dict[str, Any] = {"stage": number, "reason": row.auto_reason, "ref": row.auto_ref}
    if rule_name is not None:
        said |= {"rule": dict(rule_name), "keys": list(keys)}
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_changed",
        changes=[Change(AUTOMATIC_FIELD, None, said)],
        source="rule",
        subtype=record.type,
    )


async def _rows(session: AsyncSession, record: WorkItem) -> list[WorkItemApproval]:
    """The request's approval rows of its current round (WP-047a S3b, REQ-SR-041).

    A restart opens the next round: earlier rounds stay in history and on the Approvals tab,
    never in what the stages' rules count or open.
    """
    found = list(
        await session.scalars(
            select(WorkItemApproval)
            .where(
                WorkItemApproval.work_item_id == record.id,
                WorkItemApproval.record_stage.is_(None),
                WorkItemApproval.purpose == rules.ApprovalPurpose.RECORD.value,
                WorkItemApproval.deleted_at.is_(None),
            )
            .order_by(WorkItemApproval.stage, WorkItemApproval.created_at)
        )
    )
    latest = current_round([r.round for r in found])
    return [r for r in found if r.round == latest]


def _outcomes(
    stages: Sequence[stage_snapshot.SnapStage], rows: Sequence[WorkItemApproval]
) -> dict[int, rules.LevelOutcome]:
    """Each opened stage's outcome so far (pending stages left out, as `next_step` expects)."""
    found: dict[int, rules.LevelOutcome] = {}
    for number, stage in enumerate(stages, start=1):
        mine = [r for r in rows if r.stage == number]
        if not mine:
            continue
        if any(r.state == rules.ApprovalState.SKIPPED for r in mine):
            found[number] = rules.LevelOutcome.APPROVED
            continue
        # 036 AC2: a primary and the rows escalated from it are one vote (approval_reminders).
        outcome = rules.level_outcome(rules.LevelRule(stage.rule), family_states(mine))
        if outcome is not rules.LevelOutcome.PENDING:
            found[number] = outcome
    return found


async def _eligible(session: AsyncSession, people: set[uuid.UUID]) -> dict[uuid.UUID, bool]:
    """Who may approve: a live, active person of this tenant who may sign in.

    Existence comes first (`active_user_ids`: this tenant's rows only, never deleted, inactive
    or service identities), so an ID nobody holds here (a random UUID in a "person" answer, or
    another tenant's user, which RLS hides) is never an approver (lane B's #582 review):
    `person_placement` alone answers an unknown ID with its defaults.
    """
    known = await active_user_ids(session, sorted(people, key=str))
    found: dict[uuid.UUID, bool] = {}
    for person in people:
        found[person] = person in known and (await person_placement(session, person)).can_sign_in
    return found


async def _group_members(session: AsyncSession, group_id: uuid.UUID) -> list[uuid.UUID]:
    if not await organization.active_groups(session, frozenset({group_id})):
        return []
    return list(await session.scalars(organization.users_in_groups(frozenset({group_id}))))


async def _candidates(  # noqa: C901, PLR0912 - one branch per approver kind, flat
    session: AsyncSession, record: WorkItem, stage: stage_snapshot.SnapStage
) -> list[Candidate]:
    """The people the stage's approvers name now, in the item's order (REQ-SR-031)."""
    target = requested_for(record)
    placement = await person_placement(session, target)
    named, manager = rules.ApproverOrigin.NAMED, rules.ApproverOrigin.MANAGER
    found: list[Candidate] = []
    for approver in stage.approvers:
        kind = approver.kind
        if kind == "person" and approver.person_id is not None:
            found.append(Candidate(approver.person_id, named))
        elif kind == "requested_for_manager" and placement.manager_id is not None:
            found.append(Candidate(placement.manager_id, manager))
        elif kind == "manager_of_manager" and placement.manager_id is not None:
            above = (await person_placement(session, placement.manager_id)).manager_id
            if above is not None:
                found.append(Candidate(above, manager))
        elif kind == "department_head" and placement.department_id is not None:
            _, head = await organization.unit_heads(session, None, placement.department_id)
            if head is not None:
                found.append(Candidate(head, manager))
        elif kind == "group_leads" and record.group_id is not None:
            lead, _ = await organization.unit_heads(session, record.group_id, None)
            if lead is not None:
                found.append(Candidate(lead, named))
        elif kind == "group" and approver.group_id is not None:
            found += [Candidate(u, named) for u in await _group_members(session, approver.group_id)]
        elif kind == "person_answer" and approver.question_key:
            answer = (record.answers or {}).get(approver.question_key)
            with contextlib.suppress(ValueError):  # unanswered or not a person: nobody here
                found.append(Candidate(uuid.UUID(str(answer)), named))
        elif kind == "asset_owner":
            owners = await assets.owners_of(
                session, await asset_links.asset_ids_of(session, record.id)
            )
            found += [Candidate(u, named) for u in dict.fromkeys(owners.values())]
        elif kind == "ci_owner":
            # A request's CIs come with WP-053 S5 (work_item_cis); until then none are linked,
            # so this approver names nobody and the stage falls back, recorded (condition 3).
            ci_ids: list[uuid.UUID] = []
            ci_owners = await cmdb.owners_of(session, ci_ids)
            people, groups = progression.ci_owner_targets(
                [(o.user_id, o.group_id) for o in ci_owners.values()]
            )
            found += [Candidate(u, named) for u in people]
            for group in groups:
                found += [Candidate(u, named) for u in await _group_members(session, group)]
    return found


async def _open_one(
    session: AsyncSession,
    record: WorkItem,
    number: int,
    stage: stage_snapshot.SnapStage,
) -> list[WorkItemApproval]:
    """Open one stage: a skipped row when its condition does not hold, else its approvals."""
    base: dict[str, Any] = {
        "tenant_id": record.tenant_id,
        "work_item_id": record.id,
        "stage": number,
        "rule": stage.rule,
        "branch": stage.parallel_group,
        "self_approval": False,  # condition 2: never the requester, whatever the item says
        "comments_required": stage.comments_required,
    }
    matched = (
        progression.first_matching_rule(
            [r.condition for r in stage.auto_rules], await _rule_values(session, record)
        )
        if stage.auto_rules
        else None
    )
    if stage.condition is not None and not matches(stage.condition, _values(record)):
        rows = [
            WorkItemApproval(
                **base,
                approver_id=None,
                origin=rules.ApproverOrigin.ADMINISTRATORS.value,
                state=rules.ApprovalState.SKIPPED.value,
                skip_reason=rules.SkipReason.CONDITION_NOT_MET.value,
            )
        ]
    elif matched is not None:  # REQ-SR-033: a rule holds, so the stage is approved now
        rule = stage.auto_rules[matched - 1]
        row = _decided_automatically(
            base,
            Opened(
                rules.Assignment(None, rules.ApproverOrigin.ADMINISTRATORS),
                rules.ApprovalState.APPROVED,
                rules.AutoReason.RULE_MATCHED,
                matched,
            ),
        )
        session.add(row)
        await session.flush()
        await _automatic(
            session,
            record,
            number,
            row,
            rule_name=rule.name,
            keys=progression.matched_keys(rule.condition),
        )
        await approval_event(session, record, row, "decided")
        return [row]
    else:
        candidates = await _candidates(session, record, stage)
        people = {c.user_id for c in candidates}
        if stage.backup_id is not None:
            people.add(stage.backup_id)
        assignments, left_out = progression.assign(
            candidates,
            await _eligible(session, people),
            requester=record.requester_id,
            backup_id=stage.backup_id,
        )
        if left_out:
            await record_audit(
                session,
                action_code=REQUESTER_LEFT_OUT,
                facts=AUDIT_WORKER,
                object_type="service_request",
                object_id=str(record.id),
                details={"display_id": record.display_id, "stage": number},
            )
        earlier = (
            _earlier_approvers(await _rows(session, record), number) if stage.auto_earlier else {}
        )
        opened = progression.open_with_earlier(assignments, rules.LevelRule(stage.rule), earlier)
        rows = [_decided_automatically(base, o) for o in opened]
    await approval_rows.prepare(session, record, rows)  # WP-047a S3b: round, delegation
    session.add_all(rows)
    await session.flush()
    for row in rows:
        if row.auto_reason is not None:
            await _automatic(session, record, number, row)
            await approval_event(session, record, row, "decided")
        elif row.state == rules.ApprovalState.NOT_NEEDED:
            await approval_event(session, record, row, "closed")
        else:
            await approval_event(session, record, row, "opened")
    return rows


def _decided_automatically(base: Mapping[str, Any], opened: Opened) -> WorkItemApproval:
    """One new approval row: pending, not needed, or approved automatically (with why)."""
    a = opened.assignment
    automatic = opened.auto_reason is not None
    return WorkItemApproval(
        **base,
        approver_id=a.approver_id,
        origin=a.origin.value,
        route_reason=a.reason.value if a.reason else None,
        state=opened.state.value,
        channel=rules.DecisionChannel.AUTOMATIC.value if automatic else None,
        auto_reason=opened.auto_reason.value if opened.auto_reason else None,
        auto_ref=opened.auto_ref,
        decided_at=datetime.now(UTC) if automatic else None,
    )


async def advance(session: AsyncSession, record: WorkItem) -> rules.LevelOutcome:
    """Open whatever is next; the request's approval outcome once nothing more opens.

    Skipped stages pass at once, so this keeps going until a step waits on a person (PENDING)
    or the whole approval is decided.
    """
    stages = stage_snapshot.from_json(record.approval_stages)
    plans = [StagePlan(n, s.parallel_group) for n, s in enumerate(stages, start=1)]
    for _ in range(len(stages) + 1):  # each round opens at least one stage, or returns
        rows = await _rows(session, record)
        outcomes = _outcomes(stages, rows)
        overall = progression.request_outcome(plans, outcomes)
        if overall is not rules.LevelOutcome.PENDING:
            return overall
        step = progression.next_step(plans, outcomes) or []
        opened = {r.stage for r in rows}
        new = [n for n in step if n not in opened]
        if not new:
            return rules.LevelOutcome.PENDING  # the step waits on its approvers
        for number in new:
            await _open_one(session, record, number, stages[number - 1])
    return rules.LevelOutcome.PENDING


async def open_first(
    session: AsyncSession, record: WorkItem, item: service_catalog.RequestItem
) -> rules.LevelOutcome:
    """Snapshot the item's stages on the new request and open its first step."""
    settings = await config.load(session, SERVICE_REQUEST)
    record.approval_stages = stage_snapshot.to_json(
        snapshot_of(item, tenant_earlier=settings.auto_approve_earlier)
    )
    await session.flush()
    return await advance(session, record)


async def withdraw_step(
    session: AsyncSession, record: WorkItem, numbers: Sequence[int]
) -> list[WorkItemApproval]:
    """A rejected step's other pending rows: not needed any more (REQ-SR-030 AC2)."""
    return [
        r
        for r in await _rows(session, record)
        if r.stage in numbers and r.state == rules.ApprovalState.PENDING
    ]


def step_of(record: WorkItem, number: int) -> list[int]:
    """The stage numbers that run together with stage `number`."""
    stages = stage_snapshot.from_json(record.approval_stages)
    plans = [StagePlan(n, s.parallel_group) for n, s in enumerate(stages, start=1)]
    return next((step for step in progression.steps(plans) if number in step), [number])


def stage_outcome(
    record: WorkItem, rows: Sequence[WorkItemApproval], number: int
) -> rules.LevelOutcome:
    """One stage's outcome now (PENDING while it waits)."""
    stages = stage_snapshot.from_json(record.approval_stages)
    return _outcomes(stages, rows).get(number, rules.LevelOutcome.PENDING)


def auto_rule_of(record: WorkItem, number: int, rule: int | None) -> stage_snapshot.SnapRule | None:
    """Stage `number`'s automatic rule `rule` (1-based) as snapshotted, if any."""
    if record.approval_stages is None or rule is None:
        return None
    stages = stage_snapshot.from_json(record.approval_stages)
    if not 0 < number <= len(stages):
        return None
    found = stages[number - 1].auto_rules
    return found[rule - 1] if 0 < rule <= len(found) else None


eligible = _eligible  # REQ-SR-042: a person added or swapped in is checked the same way
# WP-047a S3a (REQ-SR-034): an escalation reads the stage's rows and a group as opening does.
rows_of = _rows
group_members = _group_members


def condition_of(record: WorkItem, number: int) -> Mapping[str, Any] | None:
    """Stage `number`'s condition as snapshotted (shown with a skipped stage)."""
    if record.approval_stages is None:
        return None
    stages = stage_snapshot.from_json(record.approval_stages)
    return stages[number - 1].condition if 0 < number <= len(stages) else None
