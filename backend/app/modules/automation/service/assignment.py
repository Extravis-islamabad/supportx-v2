"""Auto-assignment inside a group (WP-029; REQ-ASG-002..004, 006, 011; D-097).

A group's set-up decides whether and how its new work is assigned. Candidates are the group's
members who may work the record (the record's module says who), filtered here by availability
(Away is never picked) and the load cap. The group's settings row is locked while choosing, so
records arriving at the same moment get distinct turns (REQ-ASG-003 AC2).
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict
from app.modules.automation.domain.assignment import (
    AssignmentChoice,
    AssignMethod,
    Availability,
    Candidate,
    choose,
    weighted_load,
)
from app.modules.automation.events import AssignmentWaiting, AutomationChanged, AvailabilityChanged
from app.modules.automation.infra.models import (
    AssignmentSettings,
    AssignmentTurn,
    AutomationRun,
    TechnicianAvailability,
)
from app.modules.automation.service.business_rules import _invalid
from app.modules.organization import active_unit_ids, memberships, unit_heads
from app.shared.events import record_event
from app.shared.history import (
    Change,
    Source,
    count_saves,
    history_page,
    people_names,
    record_changes,
    stale_version,
)

LOAD_CAP_MAX = 1000
SETTINGS_FIELDS = (
    "enabled",
    "method",
    "record_types",
    "on_create",
    "on_move",
    "unassigned_only",
    "count_paused",
    "load_cap",
)


@dataclass(frozen=True)
class Member:
    """A group member who may work the record, with the open records counting as load."""

    user_id: uuid.UUID
    open_priorities: Sequence[str]  # one priority code per open record (paused included or not)


# (count_paused) → members of the group who may work the record, with their open load.
MembersProvider = Callable[[bool], Awaitable[Sequence[Member]]]


async def group_settings(session: AsyncSession, group_id: uuid.UUID) -> AssignmentSettings | None:
    """A group's auto-assignment set-up, or None (never set up: off, D-097)."""
    found: AssignmentSettings | None = await session.scalar(
        select(AssignmentSettings).where(AssignmentSettings.group_id == group_id)
    )
    return found


async def save_group_settings(
    session: AsyncSession,
    group_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
) -> AssignmentSettings:
    """Switch a group's auto-assignment on or off and set it up (If-Match; 0 for the first)."""
    if not await active_unit_ids(session, "group", [group_id]):
        raise _invalid([("group_id", "group_not_found", {})])
    problems: list[tuple[str, str, Mapping[str, Any]]] = []
    method = values.get("method", AssignMethod.ROUND_ROBIN.value)
    if method not in {m.value for m in AssignMethod}:
        problems.append(("method", "invalid_choice", {}))
    cap = values.get("load_cap")
    if cap is not None and (
        not isinstance(cap, int) or isinstance(cap, bool) or not 1 <= cap <= LOAD_CAP_MAX
    ):
        problems.append(("load_cap", "out_of_range", {"min": 1, "max": LOAD_CAP_MAX}))
    if problems:
        raise _invalid(problems)
    current = await group_settings(session, group_id)
    version = current.version if current is not None else 0
    if version != expected_version:
        if current is None:
            raise Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": version},
            )
        raise await stale_version(session, current, expected_version=expected_version)
    context = session.info[SESSION_TENANT_KEY]
    changes = {name: values[name] for name in SETTINGS_FIELDS if name in values}
    if current is None:
        current = AssignmentSettings(
            tenant_id=context.tenant_id, group_id=group_id, version=1, **changes
        )
        current.created_by = current.updated_by = context.user_id
        session.add(current)
    else:
        for name, value in changes.items():
            setattr(current, name, value)
        current.version += 1
        current.updated_by = context.user_id
        current.updated_at = datetime.now(UTC)
    await session.flush()
    await record_event(
        session,
        AutomationChanged(
            kind="assignment_settings", definition_id=group_id, record_type=None, change="updated"
        ),
        aggregate_id=group_id,
        aggregate_version=current.version,
    )
    return current


async def availability(
    session: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Availability]:
    """Each person's state (no row: available, D-097)."""
    if not user_ids:
        return {}
    rows = await session.execute(
        select(TechnicianAvailability.user_id, TechnicianAvailability.state).where(
            TechnicianAvailability.user_id.in_(list(user_ids))
        )
    )
    found = {row.user_id: Availability(row.state) for row in rows}
    return {u: found.get(u, Availability.AVAILABLE) for u in user_ids}


AVAILABILITY_RECORD_TYPE = "technician_availability"


@dataclass(frozen=True)
class AvailabilityState:
    """Someone's state, and who set it when (QA WP-029 follow-up: "set Away by <name>")."""

    state: Availability
    changed_at: datetime | None
    changed_by: str | None


async def _named(session: AsyncSession, user_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    names: dict[uuid.UUID, str] = {}
    for user_id in set(user_ids):
        found = await people_names(session, [str(user_id)])
        if found:
            names[user_id] = found[0]
    return names


async def availability_states(
    session: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, AvailabilityState]:
    """Each person's state with its last change (no row: available, never changed)."""
    if not user_ids:
        return {}
    rows = (
        await session.execute(
            select(TechnicianAvailability).where(TechnicianAvailability.user_id.in_(list(user_ids)))
        )
    ).scalars()
    found = {row.user_id: row for row in rows}
    names = await _named(session, [r.changed_by for r in found.values() if r.changed_by])
    states: dict[uuid.UUID, AvailabilityState] = {}
    for user_id in user_ids:
        row = found.get(user_id)
        states[user_id] = (
            AvailabilityState(Availability.AVAILABLE, None, None)
            if row is None
            else AvailabilityState(
                Availability(row.state),
                row.changed_at,
                names.get(row.changed_by) if row.changed_by else None,
            )
        )
    return states


async def may_set_availability(
    session: AsyncSession, setter: uuid.UUID, user_id: uuid.UUID, *, manages_people: bool
) -> bool:
    """Yourself; anyone with `users.manage`; or the lead of a group the person is in."""
    if setter == user_id or manages_people:
        return True
    for group_id in (await memberships(session, user_id)).group_ids:
        lead, _ = await unit_heads(session, group_id, None)
        if lead == setter:
            return True
    return False


async def set_availability(
    session: AsyncSession,
    user_id: uuid.UUID,
    state: Availability,
    source: Source = "ui",
) -> Availability:
    """Set someone Available or Away (REQ-ASG-006): themselves, their group lead or an admin.

    Each change is a line in the person's availability history (who, when, from what).
    """
    context = session.info[SESSION_TENANT_KEY]
    now = datetime.now(UTC)
    before = (await availability(session, [user_id]))[user_id]
    await session.execute(
        insert(TechnicianAvailability)
        .values(
            tenant_id=context.tenant_id,
            user_id=user_id,
            state=state.value,
            changed_at=now,
            changed_by=context.user_id,
        )
        .on_conflict_do_update(
            index_elements=[TechnicianAvailability.tenant_id, TechnicianAvailability.user_id],
            set_={"state": state.value, "changed_at": now, "changed_by": context.user_id},
        )
    )
    if before != state:
        saves = await count_saves(session, AVAILABILITY_RECORD_TYPE, user_id)
        await record_changes(
            session,
            record_type=AVAILABILITY_RECORD_TYPE,
            record_id=user_id,
            version=saves + 1,
            kind="updated",
            changes=[Change("state", before.value, state.value)],
            source=source,
        )
    await record_event(
        session,
        AvailabilityChanged(user_id=user_id, state=state.value),
        aggregate_id=user_id,
    )
    return state


async def availability_history(
    session: AsyncSession, user_id: uuid.UUID, limit: int = 20
) -> list[AvailabilityState]:
    """The person's availability changes, newest first: the state set, by whom, when."""
    entries, _ = await history_page(session, AVAILABILITY_RECORD_TYPE, user_id, limit=limit)
    actors = [uuid.UUID(e.actor_id) for e in entries if e.actor_id]
    names = await _named(session, actors)
    return [
        AvailabilityState(
            Availability(str(change.new)),
            entry.occurred_at,
            names.get(uuid.UUID(entry.actor_id)) if entry.actor_id else None,
        )
        for entry in entries
        for change in entry.changes
        if change.field == "state"
    ]


@dataclass(frozen=True)
class AssignmentResult:
    """What auto-assignment did, for the record's history and the log."""

    choice: AssignmentChoice
    group_id: uuid.UUID


async def auto_assign(  # noqa: PLR0913 - the record, the group, the moment and who may work it
    session: AsyncSession,
    *,
    record_type: str,
    record_id: uuid.UUID,
    group_id: uuid.UUID,
    moment: Literal["create", "move"],
    has_technician: bool,
    members: MembersProvider,
) -> AssignmentResult | None:
    """Pick a technician inside `group_id` only (REQ-ASG-002 AC5), or None when it does not apply.

    "Nobody available" or "all at the cap" leaves the record in the group queue and says so
    (event and log): never a silent skip (REQ-ASG-011).
    """
    settings: AssignmentSettings | None = await session.scalar(
        select(AssignmentSettings)
        .where(AssignmentSettings.group_id == group_id)
        .with_for_update()  # one choice at a time per group: distinct turns under bursts
    )
    if settings is None or not settings.enabled:
        return None
    if settings.record_types and record_type not in settings.record_types:
        return None
    if (moment == "create" and not settings.on_create) or (
        moment == "move" and not settings.on_move
    ):
        return None
    if has_technician and settings.unassigned_only:
        return None
    people = list(await members(settings.count_paused))
    states = await availability(session, [m.user_id for m in people])
    turns = dict(
        (
            await session.execute(
                select(AssignmentTurn.user_id, AssignmentTurn.last_assigned_at).where(
                    AssignmentTurn.group_id == group_id
                )
            )
        ).all()
    )
    candidates = [
        Candidate(
            user_id=str(m.user_id),
            available=states[m.user_id] == Availability.AVAILABLE,
            load=weighted_load(m.open_priorities),
            open_count=len(m.open_priorities),
            last_assigned_at=turns.get(m.user_id),
        )
        for m in people
    ]
    choice = choose(AssignMethod(settings.method), candidates, load_cap=settings.load_cap)
    context = session.info[SESSION_TENANT_KEY]
    if choice.user_id is not None:
        now = datetime.now(UTC)
        await session.execute(
            insert(AssignmentTurn)
            .values(
                tenant_id=context.tenant_id,
                group_id=group_id,
                user_id=uuid.UUID(choice.user_id),
                last_assigned_at=now,
            )
            .on_conflict_do_update(
                index_elements=[
                    AssignmentTurn.tenant_id,
                    AssignmentTurn.group_id,
                    AssignmentTurn.user_id,
                ],
                set_={"last_assigned_at": now},
            )
        )
    else:
        await record_event(
            session,
            AssignmentWaiting(
                record_type=record_type,
                record_id=record_id,
                group_id=group_id,
                reason=choice.reason,  # type: ignore[arg-type]  # one of the Literal's values
            ),
            aggregate_id=record_id,
        )
    session.add(
        AutomationRun(
            tenant_id=context.tenant_id,
            record_type=record_type,
            record_id=record_id,
            kind="assignment",
            automation_id=group_id,
            automation_name=None,
            outcome=choice.reason,
            detail={"method": choice.method.value, "loads": choice.loads, "moment": moment},
        )
    )
    await session.flush()
    return AssignmentResult(choice, group_id)
