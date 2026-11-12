"""A person's cost per hour (REQ-INC-068; migration 0148). Lane A's worklog costs read it.

- **Who:** reading a person's rates needs `users.view_cost_rates`; every change needs
  `users.manage_cost_rates` as well (a change answers with the rates, so it shows money too).
  No built-in role holds them but the tenant admin. A service identity never has a rate
  (409 `not_a_person`).
- **Rates by date:** a rate starts at `effective_from` and holds until the next one starts
  (domain/cost_rates.py). The current and upcoming rates can change; a superseded one stays as
  it was (409 `cost_rate_superseded`): the correction is a new rate. Any rate can be removed
  (a soft delete; costs already worked out keep the rate they used).
- **Currency:** the tenant's base currency when the rate is set (organization's settings).
- **Never leaked:** rates are not part of the person's record, lists, search, exports or events.
  The person's own field history gets the rate's ID only (it is read with the person record);
  the amounts are in the rate's own history and the audit entry the route writes.
- **The port** `cost_rate` (exported by the module) is for system snapshotting: no permission
  check; the caller decides who sees money.

Every change: one transaction with its outbox event (rule b), If-Match on changes (rule g) and
field history (§7.4).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules.identity_access.domain.cost_rates import (
    RateState,
    require_aware,
    state_of,
    superseded,
)
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.events import UserCostRateChanged
from app.modules.identity_access.infra.models import User, UserCostRate
from app.modules.identity_access.service.directory import USER_RECORD_TYPE
from app.modules.organization import base_currency
from app.shared.clock import Clock, system_clock
from app.shared.events import record_event
from app.shared.history import Change, ChangeKind, Source, record_changes
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id

VIEW = "users.view_cost_rates"
MANAGE = "users.manage_cost_rates"
RECORD_TYPE = "user_cost_rate"
# The field on the person's own history (the rate's ID only, never the amount).
PERSON_FIELD = "cost_rate"
Action = Literal["created", "updated", "deleted"]
_OWN_KIND: dict[Action, ChangeKind] = {
    "created": "created",
    "updated": "updated",
    "deleted": "deleted",
}
_PART_KIND: dict[Action, ChangeKind] = {
    "created": "child_added",
    "updated": "child_changed",
    "deleted": "child_removed",
}


@dataclass(frozen=True, slots=True)
class RateView:
    """One rate and where it stands now."""

    row: UserCostRate
    state: RateState


@dataclass(frozen=True, slots=True)
class PersonRates:
    """A person's rates, newest start first, and the one in force now."""

    user_id: uuid.UUID
    currency: str  # the tenant's base currency now (a new rate gets it)
    rates: list[RateView]
    current: RateView | None


@dataclass(frozen=True, slots=True)
class RateChange:
    """What one change did, for the route's audit entry: the rate before and after."""

    rate: UserCostRate
    action: Action
    old_rate: Decimal | None
    old_effective_from: datetime | None
    new_rate: Decimal | None
    new_effective_from: datetime | None


def _require(subject: Subject, *permissions: str) -> None:
    for permission in permissions:
        if not subject.holds(permission):
            raise PermissionDenied(params={"permission": permission})


async def _person(session: AsyncSession, user_id: uuid.UUID) -> User:
    person = await session.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    if person is None:
        raise NotFound(code="user_not_found", params={"id": str(user_id)})
    if person.user_type == UserType.SERVICE.value:
        raise Conflict(code="not_a_person")
    return person


async def _rates(
    session: AsyncSession, user_id: uuid.UUID, *, lock: bool = False
) -> list[UserCostRate]:
    """The person's live rates, newest start first (locked while one of them changes)."""
    query = (
        select(UserCostRate)
        .where(UserCostRate.user_id == user_id, UserCostRate.deleted_at.is_(None))
        .order_by(UserCostRate.effective_from.desc())
    )
    if lock:
        query = query.with_for_update()
    return list(await session.scalars(query))


def _views(rates: Sequence[UserCostRate], now: datetime) -> list[RateView]:
    return [RateView(r, state_of(r, rates, now)) for r in rates]


async def list_rates(
    session: AsyncSession,
    subject: Subject,
    user_id: uuid.UUID,
    *,
    clock: Clock = system_clock,
) -> PersonRates:
    """A person's rates (newest first) and the current one. Needs `users.view_cost_rates`."""
    _require(subject, VIEW)
    await _person(session, user_id)
    rates = await _rates(session, user_id)
    views = _views(rates, clock.now())
    return PersonRates(
        user_id=user_id,
        currency=await base_currency(session),
        rates=views,
        current=next((v for v in views if v.state is RateState.CURRENT), None),
    )


def _json(value: object) -> object:
    """As field history stores it (JSON): amounts, times and IDs as text."""
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


async def _saved(  # noqa: PLR0913 - one save of a rate: the person, the rate, what and how
    session: AsyncSession,
    person: User,
    rate: UserCostRate,
    changes: list[Change],
    *,
    action: Action,
    source: Source,
) -> None:
    """History on the rate and (its ID only) on the person, and the event: same transaction."""
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=rate.id,
        version=rate.version,
        kind=_OWN_KIND[action],
        changes=changes,
        source=source,
    )
    part = str(rate.id)
    await record_changes(
        session,
        record_type=USER_RECORD_TYPE,
        record_id=person.id,
        version=person.version,
        kind=_PART_KIND[action],
        changes=[
            Change(
                PERSON_FIELD,
                None if action == "created" else part,
                None if action == "deleted" else part,
            )
        ],
        source=source,
    )
    await record_event(
        session,
        UserCostRateChanged(user_id=person.id, change=action),
        aggregate_id=rate.id,
        aggregate_version=rate.version,
    )


def _start_taken(rates: Sequence[UserCostRate], start: datetime, rate_id: uuid.UUID | None) -> None:
    if any(r.effective_from == start and r.id != rate_id for r in rates):
        raise Conflict(code="cost_rate_date_taken", params={"effective_from": start.isoformat()})


async def set_rate(  # noqa: PLR0913 - the person, the rate, its start, who and from where
    session: AsyncSession,
    subject: Subject,
    user_id: uuid.UUID,
    *,
    rate: Decimal,
    effective_from: datetime,
    source: Source = "api",
) -> RateChange:
    """A new rate from `effective_from` on (past, now or later), in the base currency."""
    _require(subject, VIEW, MANAGE)
    require_aware(effective_from)
    person = await _person(session, user_id)
    rates = await _rates(session, user_id, lock=True)
    _start_taken(rates, effective_from, None)
    row = UserCostRate(
        id=new_id(),
        tenant_id=person.tenant_id,
        user_id=person.id,
        rate=rate,
        currency=await base_currency(session),
        effective_from=effective_from,
        created_by=subject.user_id,
        updated_by=subject.user_id,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:  # a parallel save took the same start
        raise Conflict(code="cost_rate_date_taken") from exc
    await session.refresh(row)
    changes = [
        Change("rate", None, _json(row.rate)),
        Change("currency", None, row.currency),
        Change("effective_from", None, _json(row.effective_from)),
    ]
    await _saved(session, person, row, changes, action="created", source=source)
    return RateChange(row, "created", None, None, row.rate, row.effective_from)


async def _rate(
    session: AsyncSession, person: User, rate_id: uuid.UUID
) -> tuple[UserCostRate, list[UserCostRate]]:
    rates = await _rates(session, person.id, lock=True)
    row = next((r for r in rates if r.id == rate_id), None)
    if row is None:
        raise NotFound(code="cost_rate_not_found", params={"id": str(rate_id)})
    return row, rates


async def _fresh(session: AsyncSession, row: UserCostRate, expected_version: int) -> None:
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip


async def change_rate(  # noqa: PLR0913 - the rate, its version, the change and its source
    session: AsyncSession,
    subject: Subject,
    user_id: uuid.UUID,
    rate_id: uuid.UUID,
    *,
    expected_version: int,
    rate: Decimal | None = None,
    effective_from: datetime | None = None,
    source: Source = "api",
    clock: Clock = system_clock,
) -> RateChange:
    """Change the current or an upcoming rate (If-Match); a superseded one is refused."""
    _require(subject, VIEW, MANAGE)
    if effective_from is not None:
        require_aware(effective_from)
    person = await _person(session, user_id)
    row, rates = await _rate(session, person, rate_id)
    await _fresh(session, row, expected_version)
    now = clock.now()
    others = [r for r in rates if r.id != row.id]
    start = effective_from if effective_from is not None else row.effective_from
    if superseded(row.effective_from, others, now) or superseded(start, others, now):
        raise Conflict(code="cost_rate_superseded")
    _start_taken(rates, start, row.id)
    before_rate, before_start = row.rate, row.effective_from
    changes: list[Change] = []
    if rate is not None and rate != row.rate:
        changes.append(Change("rate", _json(row.rate), _json(rate)))
        row.rate = rate
    if start != row.effective_from:
        changes.append(Change("effective_from", _json(row.effective_from), _json(start)))
        row.effective_from = start
    if not changes:
        return RateChange(row, "updated", before_rate, before_start, row.rate, start)
    row.version += 1
    row.updated_by = subject.user_id
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict(code="cost_rate_date_taken") from exc
    await session.refresh(row)
    await _saved(session, person, row, changes, action="updated", source=source)
    return RateChange(row, "updated", before_rate, before_start, row.rate, row.effective_from)


async def remove_rate(  # noqa: PLR0913 - the rate, its version and the source
    session: AsyncSession,
    subject: Subject,
    user_id: uuid.UUID,
    rate_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source = "api",
    clock: Clock = system_clock,
) -> RateChange:
    """Remove a rate (If-Match): kept, marked removed; costs worked out with it keep it."""
    _require(subject, VIEW, MANAGE)
    person = await _person(session, user_id)
    row, _ = await _rate(session, person, rate_id)
    await _fresh(session, row, expected_version)
    row.deleted_at = clock.now()
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await session.refresh(row)
    removed = [Change("deleted", old=False, new=True)]
    await _saved(session, person, row, removed, action="deleted", source=source)
    return RateChange(row, "deleted", row.rate, row.effective_from, None, None)


async def cost_rate(session: AsyncSession, user_id: uuid.UUID, at: datetime) -> Decimal | None:
    """The person's cost per hour in force at `at`, or None when unset or not yet started.

    The latest live rate whose `effective_from` is at or before `at`, in the tenant's base
    currency as it was when the rate was set. `at` must be timezone-aware (ValueError
    otherwise). The session's tenant applies through RLS.

    **No permission check:** this is for system snapshotting (a worklog's cost when it is
    logged, REQ-INC-068); the caller decides who may see money (`users.view_cost_rates` or its
    own module's right).
    """
    require_aware(at)
    found: Decimal | None = await session.scalar(
        select(UserCostRate.rate)
        .where(
            UserCostRate.user_id == user_id,
            UserCostRate.deleted_at.is_(None),
            UserCostRate.effective_from <= at,
        )
        .order_by(UserCostRate.effective_from.desc())
        .limit(1)
    )
    return found
