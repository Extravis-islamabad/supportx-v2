"""Bookings ahead (WP-049b s1; REQ-AST-032).

- **One specific asset** is booked for a period, for a person (and, if given, their department).
  Only loanable assets that are not retired or disposed can be booked.
- **No double booking (AC1):** the asset's row is locked first (as a loan does), then the period
  is checked against its live bookings and its open loan, so two bookings racing for the same
  time never both commit. A refusal names the next free day: the same length, whole days later.
- **Handover (AC2):** handing a booked asset over makes a loan with the booking's own dates
  (through the loan service, so every loan rule holds) and marks the booking handed over.
- **The portal (AC3):** a requester books for themselves only when the tenant's setting
  `portal_booking` is on (off by default); staff book with `assets.manage`.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules.assets.domain.bookings import BOOKING_LENGTH_MAX, next_free
from app.modules.assets.domain.catalogue import AssetStateCategory, Problem
from app.modules.assets.domain.loans import Period
from app.modules.assets.events import AssetBookingChanged, BookingChange
from app.modules.assets.infra.models import (
    Asset,
    AssetBooking,
    AssetLoan,
    AssetLoanItem,
    AssetSettings,
    AssetState,
)
from app.modules.assets.service.assets import (
    MANAGE,
    VIEW,
    _refuse,
    _require,
    _tenant,
    _visible,
)
from app.modules.assets.service.loans import COMMENT_MAX, create_loan
from app.modules.assets.service.refs import ASSET_SEARCH
from app.modules.identity_access import Subject, active_user_ids
from app.modules.organization import existing_departments
from app.shared.clock import system_clock
from app.shared.events import record_event
from app.shared.history import Source
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id
from app.shared.search import ENGINE

RECORD_TYPE = "asset_booking"
LIST_MAX = 200
BOOKABLE_MAX = 50
_GONE = (AssetStateCategory.RETIRED, AssetStateCategory.DISPOSED)

Channel = Literal["console", "portal"]


async def portal_booking_on(session: AsyncSession) -> bool:
    """Whether requesters may book from the portal (the tenant's setting, off by default)."""
    settings = await session.get(AssetSettings, _tenant(session))
    return settings is not None and settings.portal_booking


async def _bookable(session: AsyncSession, row: Asset) -> None:
    state = await session.get(AssetState, row.state_id)
    if not row.loanable or state is None or state.category in _GONE:
        raise Conflict(code="asset_not_bookable", params={"asset": row.tag or row.name})


async def _locked_for_portal(session: AsyncSession, asset_id: uuid.UUID) -> Asset:
    row = await session.scalar(
        select(Asset)
        .where(Asset.id == asset_id, Asset.deleted_at.is_(None), Asset.loanable.is_(True))
        .with_for_update(of=Asset)
    )
    if row is None:
        raise NotFound(code="asset_not_found")
    return row


async def held_periods(
    session: AsyncSession, asset_id: uuid.UUID, *, other_than: uuid.UUID | None = None
) -> list[Period]:
    """What already holds the asset: its live bookings and its open loan.

    An open loan holds it until its due time, or until now while it is overdue.
    """
    now = system_clock.now()
    query = select(AssetBooking.starts_at, AssetBooking.ends_at).where(
        AssetBooking.asset_id == asset_id,
        AssetBooking.status == "booked",
        AssetBooking.deleted_at.is_(None),
        AssetBooking.ends_at > now,
    )
    if other_than is not None:
        query = query.where(AssetBooking.id != other_than)
    periods = [Period(start, end) for start, end in (await session.execute(query)).tuples()]
    loan = (
        await session.execute(
            select(AssetLoan.starts_at, AssetLoan.due_at)
            .join(AssetLoanItem, AssetLoanItem.loan_id == AssetLoan.id)
            .where(
                AssetLoanItem.asset_id == asset_id,
                AssetLoanItem.returned_at.is_(None),
                AssetLoanItem.deleted_at.is_(None),
            )
        )
    ).first()
    if loan is not None:
        periods.append(Period(loan.starts_at, max(loan.due_at, now)))
    return periods


def _problems(
    starts_at: datetime, ends_at: datetime, comment: str | None
) -> tuple[str | None, list[Problem]]:
    problems: list[Problem] = []
    if ends_at <= starts_at:
        problems.append(Problem("ends_at", "asset_booking_ends_before_start"))
    elif ends_at - starts_at > BOOKING_LENGTH_MAX:
        problems.append(
            Problem("ends_at", "asset_booking_too_long", (("days", BOOKING_LENGTH_MAX.days),))
        )
    if ends_at <= system_clock.now():
        problems.append(Problem("ends_at", "date_in_past"))
    text_ = (comment or "").strip() or None
    if text_ is not None and len(text_) > COMMENT_MAX:
        problems.append(Problem("comment", "value_too_long", (("max", COMMENT_MAX),)))
    return text_, problems


# Field codes made from (field, code) pairs here, for the label check (tests/test_error_labels).
FIELD_PROBLEMS = frozenset({"asset_booking_ends_before_start", "asset_booking_too_long"})


async def _event(session: AsyncSession, row: AssetBooking, change: BookingChange) -> None:
    await record_event(
        session,
        AssetBookingChanged(
            booking_id=row.id, asset_id=row.asset_id, borrower_id=row.borrower_id,
            change=change, loan_id=row.loan_id,
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )  # fmt: skip


async def create_booking(  # noqa: PLR0913 - which asset, for whom, when, why, from where
    session: AsyncSession,
    subject: Subject,
    *,
    asset_id: uuid.UUID,
    borrower_id: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime,
    department_id: uuid.UUID | None = None,
    comment: str | None = None,
    channel: Channel = "console",
) -> AssetBooking:
    """Book one asset for a period; refused when taken, with the next free day (AC1)."""
    if channel == "portal":
        if not await portal_booking_on(session):
            raise PermissionDenied(code="asset_portal_booking_off")
        if borrower_id != subject.user_id or department_id is not None:
            raise PermissionDenied(code="asset_book_for_yourself")
    else:
        _require(subject, MANAGE)
    text_, problems = _problems(starts_at, ends_at, comment)
    if borrower_id not in await active_user_ids(session, [borrower_id]):
        problems.append(Problem("borrower_id", "asset_holder_not_found"))
    if department_id is not None and department_id not in await existing_departments(
        session, [department_id]
    ):
        problems.append(Problem("department_id", "asset_holder_not_found"))
    _refuse(problems)
    # The asset's row first, as a loan takes it: the check below and the insert are one step.
    row = (
        await _locked_for_portal(session, asset_id)
        if channel == "portal"
        else await _visible(session, subject, asset_id, permission=MANAGE)
    )
    await _bookable(session, row)
    wanted = Period(starts_at, ends_at)
    taken = await held_periods(session, row.id)
    if any(p.starts_at < wanted.due_at and wanted.starts_at < p.due_at for p in taken):
        free = next_free(wanted, taken)
        raise Conflict(
            code="asset_booking_taken",
            params={"next_free": "" if free is None else free.isoformat()},
        )
    booking = AssetBooking(
        id=new_id(), tenant_id=row.tenant_id, created_by=subject.user_id, asset_id=row.id,
        borrower_id=borrower_id, department_id=department_id, starts_at=starts_at,
        ends_at=ends_at, comment=text_, channel=channel,
    )  # fmt: skip
    session.add(booking)
    await session.flush()
    await _event(session, booking, "created")
    return booking


async def _live(session: AsyncSession, booking_id: uuid.UUID) -> AssetBooking:
    row = await session.scalar(
        select(AssetBooking)
        .where(AssetBooking.id == booking_id, AssetBooking.deleted_at.is_(None))
        .with_for_update()
    )
    if row is None:
        raise NotFound(code="asset_booking_not_found")
    return row


async def cancel_booking(
    session: AsyncSession,
    subject: Subject,
    booking_id: uuid.UUID,
    *,
    expected_version: int,
    own_only: bool = False,
) -> AssetBooking:
    """Cancel a booking not yet handed over (If-Match). `own_only`: the portal's, one's own."""
    if not own_only:
        _require(subject, MANAGE)
    row = await _live(session, booking_id)
    if own_only and row.borrower_id != subject.user_id:
        raise NotFound(code="asset_booking_not_found")
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    if row.status != "booked":
        raise Conflict(code="asset_booking_not_open")
    row.status = "cancelled"
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await _event(session, row, "cancelled")
    return row


async def hand_over(
    session: AsyncSession,
    subject: Subject,
    booking_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> tuple[AssetBooking, AssetLoan]:
    """The booked asset is handed over: a loan with the booking's dates (AC2)."""
    _require(subject, MANAGE)
    row = await _live(session, booking_id)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    if row.status != "booked":
        raise Conflict(code="asset_booking_not_open")
    loan = await create_loan(
        session, subject, borrower_id=row.borrower_id, asset_ids=[row.asset_id],
        due_at=row.ends_at, comment=row.comment, source=source,
        department_id=row.department_id, starts_at=row.starts_at, booking_id=row.id,
    )  # fmt: skip
    row.status, row.loan_id = "handed_over", loan.id
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await _event(session, row, "handed_over")
    return row, loan


def _listing(
    *, asset_ids: Sequence[uuid.UUID] | None, start: datetime | None, end: datetime | None
) -> Select[AssetBooking]:
    query = select(AssetBooking).where(AssetBooking.deleted_at.is_(None))
    if asset_ids is not None:
        query = query.where(AssetBooking.asset_id.in_(asset_ids))
    if start is not None:
        query = query.where(AssetBooking.ends_at > start)
    if end is not None:
        query = query.where(AssetBooking.starts_at < end)
    return query


async def list_bookings(  # noqa: PLR0913 - the calendar's filters
    session: AsyncSession,
    subject: Subject,
    *,
    asset_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    include_closed: bool = False,
) -> list[AssetBooking]:
    """Bookings by asset, or by product and site (the calendar), earliest first."""
    _require(subject, VIEW)
    asset_ids: list[uuid.UUID] | None = None
    if asset_id is not None:
        asset_ids = [asset_id]
    elif product_id is not None or site_id is not None:
        assets = select(Asset.id).where(Asset.deleted_at.is_(None))
        if product_id is not None:
            assets = assets.where(Asset.product_id == product_id)
        if site_id is not None:
            assets = assets.where(Asset.site_id == site_id)
        asset_ids = list(await session.scalars(assets))
    query = _listing(asset_ids=asset_ids, start=start, end=end)
    if not include_closed:
        query = query.where(AssetBooking.status == "booked")
    return list(
        await session.scalars(
            query.order_by(AssetBooking.starts_at, AssetBooking.id).limit(LIST_MAX)
        )
    )


async def my_bookings(session: AsyncSession, subject: Subject) -> list[AssetBooking]:
    """The signed-in person's live bookings (the portal), earliest first."""
    return list(
        await session.scalars(
            select(AssetBooking)
            .where(
                AssetBooking.borrower_id == subject.user_id,
                AssetBooking.deleted_at.is_(None),
                AssetBooking.status == "booked",
                AssetBooking.ends_at > system_clock.now(),
            )
            .order_by(AssetBooking.starts_at, AssetBooking.id)
            .limit(LIST_MAX)
        )
    )


@dataclass(frozen=True, slots=True)
class Availability:
    """A bookable asset and what already holds it in the window asked about."""

    asset: Asset
    held: list[Period]


async def availability(
    session: AsyncSession,
    *,
    product_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    text_: str | None,
    limit: int = BOOKABLE_MAX,
) -> list[Availability]:
    """Loanable assets that are not retired or disposed, with their held periods (AC1's view).

    No permission check here: the routes decide who may ask (staff, or the portal when booking
    there is on), and only tags, names and periods leave this function.
    """
    query = (
        select(Asset)
        .join(AssetState, AssetState.id == Asset.state_id)
        .where(
            Asset.deleted_at.is_(None),
            Asset.loanable.is_(True),
            AssetState.category.not_in(_GONE),
        )
    )
    if product_id is not None:
        query = query.where(Asset.product_id == product_id)
    if site_id is not None:
        query = query.where(Asset.site_id == site_id)
    if text_:
        match = await ENGINE.match(session, ASSET_SEARCH, text_)
        if match is None:
            return []
        query = query.where(match.predicate).order_by(match.rank.desc(), Asset.id)
    else:
        query = query.order_by(Asset.tag, Asset.id)
    rows = list(await session.scalars(query.limit(limit)))
    return [Availability(row, await held_periods(session, row.id)) for row in rows]


async def asset_names(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Each booked asset's tag, else its name (a booker's own list needs no asset permission)."""
    if not ids:
        return {}
    rows = await session.execute(select(Asset.id, Asset.tag, Asset.name).where(Asset.id.in_(ids)))
    return {asset_id: tag or name for asset_id, tag, name in rows.tuples()}
