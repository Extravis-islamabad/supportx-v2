"""Loans, returns and their notices (WP-049a s5; REQ-AST-029, 030, 031, 059).

- **Loanable (029):** a flag, set in bulk. Only loanable assets in an in-stock state go on a new
  loan (AC2).
- **A loan (030):** each asset moves along its life cycle to the default in-use state and is
  given to the borrower, so the loan shows in its holding history (AC1). An asset is out on at
  most one loan at a time: checked here, and enforced by a unique partial index on its
  unreturned item, so two loans racing for it never both commit (AC3).
- **Returns (031):** item by item, back to the default in-stock state or to repair with a comment
  (AC3); the holding ends; the last return closes the loan (AC1, AC2).
- **Notices (059, Appendix A):** a loan due within a day, and overdue (once), to the borrower and
  the person who made it; a warranty ending within the tenant's notice days (30) to the asset
  managers, once per warranty date. Each notice is claimed by one UPDATE ... RETURNING, so two
  workers never send it twice.
- An asset on loan cannot be disposed of (REQ-AST-017 AC1): the disposal guard.
- **WP-049b s1 (030's leftovers):** each new loan gets its display ID (LN-1, the tenant's own
  counter); a loan can be to a department, which then holds the assets, collected by the
  borrower (who hears the notices); it can name its site; the register filters by status and
  site. A loan never overlaps a booking of the same asset (REQ-AST-032) unless it is that
  booking's handover: both lock the asset row first, so the check and the write are one step.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, cast

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import Conflict, NotFound
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.assets.domain.catalogue import AssetStateCategory, Problem
from app.modules.assets.domain.loans import Period
from app.modules.assets.events import AssetLoanChanged, LoanChange, WarrantyEnding
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
    _saved,
    _visible,
    staff_rows,
)
from app.modules.assets.service.moves import move_asset
from app.modules.assets.service.ownership import Holder, set_holder
from app.modules.assets.service.refs import ASSET_SEARCH
from app.modules.identity_access import Subject, active_user_ids
from app.modules.organization import existing_departments, existing_unit_ids
from app.shared.clock import system_clock
from app.shared.db.display_ids import next_display_id
from app.shared.events import record_event
from app.shared.history import Change, Source
from app.shared.ids import new_id
from app.shared.search import ENGINE

log = get_logger(__name__)

ITEMS_MAX = 50
COMMENT_MAX = 2000
DUE_NOTICE = timedelta(days=1)  # Appendix A: "loan due (1 day before)"


async def _default_state(session: AsyncSession, category: AssetStateCategory) -> AssetState:
    found = await session.scalar(
        select(AssetState).where(
            AssetState.category == category,
            AssetState.is_default_for_category,
            AssetState.deleted_at.is_(None),
        )
    )
    if found is None:  # seeded with the catalogue; a default state cannot be removed
        raise Conflict(code="asset_no_default_state", params={"category": category.value})
    return found


async def set_loanable(
    session: AsyncSession,
    subject: Subject,
    asset_ids: Sequence[uuid.UUID],
    *,
    loanable: bool,
    source: Source,
) -> int:
    """Mark the selected assets loanable or not (REQ-AST-029), with history; how many changed."""
    _require(subject, MANAGE)
    unique = list(dict.fromkeys(asset_ids))
    if not unique or len(unique) > ITEMS_MAX:
        raise Conflict(code="asset_bulk_too_many", params={"max": ITEMS_MAX})
    changed = 0
    for asset_id in unique:
        row = await _visible(session, subject, asset_id, permission=MANAGE)
        if row.loanable == loanable:
            continue
        row.loanable = loanable
        await _saved(
            session, subject, row, [Change("loanable", not loanable, loanable)],
            action="updated", source=source,
        )  # fmt: skip
        changed += 1
    return changed


async def _on_loan(session: AsyncSession, asset_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(AssetLoanItem.id).where(
            AssetLoanItem.asset_id == asset_id,
            AssetLoanItem.returned_at.is_(None),
            AssetLoanItem.deleted_at.is_(None),
        )
    )
    return found is not None


async def on_loan_guard(session: AsyncSession, asset_id: uuid.UUID) -> str | None:
    """The disposal guard (REQ-AST-017 AC1): an asset on loan is not disposed of."""
    return "asset_on_loan" if await _on_loan(session, asset_id) else None


async def _loan_event(session: AsyncSession, loan: AssetLoan, change: LoanChange) -> None:
    await record_event(
        session,
        AssetLoanChanged(
            loan_id=loan.id,
            borrower_id=loan.borrower_id,
            created_by=loan.created_by,
            change=change,
            department_id=loan.department_id,
            site_id=loan.site_id,
        ),
        aggregate_id=loan.id,
        aggregate_version=loan.version,
    )


LOAN_PREFIX = "LN"  # Appendix A: loans `LN`, the tenant's own counter


async def booked_over(
    session: AsyncSession,
    asset_id: uuid.UUID,
    period: Period,
    *,
    other_than: uuid.UUID | None = None,
) -> AssetBooking | None:
    """A live booking of the asset that shares a moment with `period` (REQ-AST-032)."""
    query = select(AssetBooking).where(
        AssetBooking.asset_id == asset_id,
        AssetBooking.status == "booked",
        AssetBooking.deleted_at.is_(None),
        AssetBooking.starts_at < period.due_at,
        period.starts_at < AssetBooking.ends_at,
    )
    if other_than is not None:
        query = query.where(AssetBooking.id != other_than)
    return await session.scalar(query.order_by(AssetBooking.starts_at).limit(1))


async def _loan_problems(  # noqa: PLR0913 - every part of a new loan that can be wrong
    session: AsyncSession,
    *,
    unique: Sequence[uuid.UUID],
    borrower_id: uuid.UUID,
    department_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    due_at: datetime,
    text_: str | None,
) -> list[Problem]:
    problems: list[Problem] = []
    if not unique or len(unique) > ITEMS_MAX:
        problems.append(Problem("asset_ids", "asset_bulk_too_many", (("max", ITEMS_MAX),)))
    if due_at <= system_clock.now():
        problems.append(Problem("due_at", "date_in_past"))
    if text_ is not None and len(text_) > COMMENT_MAX:
        problems.append(Problem("comment", "value_too_long", (("max", COMMENT_MAX),)))
    if borrower_id not in await active_user_ids(session, [borrower_id]):
        problems.append(Problem("borrower_id", "asset_holder_not_found"))
    if department_id is not None and department_id not in await existing_departments(
        session, [department_id]
    ):
        problems.append(Problem("department_id", "asset_holder_not_found"))
    if site_id is not None and site_id not in await existing_unit_ids(session, "site", [site_id]):
        problems.append(Problem("site_id", "site_not_found"))
    return problems


async def create_loan(  # noqa: PLR0913 - who, what, until when, why, by whom, from where
    session: AsyncSession,
    subject: Subject,
    *,
    borrower_id: uuid.UUID,
    asset_ids: Sequence[uuid.UUID],
    due_at: datetime,
    comment: str | None,
    source: Source,
    department_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    starts_at: datetime | None = None,
    booking_id: uuid.UUID | None = None,
) -> AssetLoan:
    """Loan loanable, in-stock assets to a person (or a department) until `due_at` (030).

    `starts_at` and `booking_id`: a booking handed over keeps its own dates (032 AC2).
    """
    _require(subject, MANAGE)
    now = system_clock.now()
    unique = list(dict.fromkeys(asset_ids))
    text_ = (comment or "").strip() or None
    _refuse(
        await _loan_problems(
            session, unique=unique, borrower_id=borrower_id, department_id=department_id,
            site_id=site_id, due_at=due_at, text_=text_,
        )
    )  # fmt: skip
    period = Period(starts_at or now, due_at)
    in_use = await _default_state(session, AssetStateCategory.IN_USE)
    rows: list[Asset] = []
    for asset_id in unique:
        row = await _visible(session, subject, asset_id, permission=MANAGE)
        state = await session.get(AssetState, row.state_id)
        if not row.loanable or state is None or state.category != AssetStateCategory.IN_STOCK:
            raise Conflict(code="asset_not_loanable", params={"asset": row.tag or row.name})
        if await _on_loan(session, row.id):
            raise Conflict(code="asset_on_loan", params={"asset": row.tag or row.name})
        if await booked_over(session, row.id, period, other_than=booking_id) is not None:
            raise Conflict(code="asset_booked", params={"asset": row.tag or row.name})
        rows.append(row)
    loan = AssetLoan(
        id=new_id(),
        tenant_id=rows[0].tenant_id,
        created_by=subject.user_id,
        borrower_id=borrower_id,
        department_id=department_id,
        site_id=site_id,
        booking_id=booking_id,
        display_id=await next_display_id(session, LOAN_PREFIX),
        starts_at=period.starts_at,
        due_at=due_at,
        comment=text_,
    )
    session.add(loan)
    await session.flush()
    for row in rows:
        session.add(
            AssetLoanItem(
                id=new_id(), tenant_id=row.tenant_id, created_by=subject.user_id,
                loan_id=loan.id, asset_id=row.id,
            )
        )  # fmt: skip
        try:
            await session.flush()  # the unique index: a racing loan for this asset fails here
        except IntegrityError:
            raise Conflict(code="asset_on_loan", params={"asset": row.tag or row.name}) from None
        moved = await move_asset(
            session, subject, row.id, to_state_id=in_use.id, reason=text_,
            expected_version=row.version, source=source,
        )  # fmt: skip
        holder = (
            Holder("user", borrower_id)
            if department_id is None
            else Holder("department", department_id)
        )
        await set_holder(
            session, subject, row.id, holder, expected_version=moved.version, source=source
        )
    await _loan_event(session, loan, "created")
    return loan


async def return_items(  # noqa: PLR0913 - the loan, which come back how, why, by whom, from where
    session: AsyncSession,
    subject: Subject,
    loan_id: uuid.UUID,
    asset_ids: Sequence[uuid.UUID],
    *,
    outcome: Literal["in_stock", "in_repair"],
    comment: str | None,
    source: Source,
) -> AssetLoan:
    """Some or all assets come back (REQ-AST-031); the last return closes the loan."""
    _require(subject, MANAGE)
    loan = await session.get(AssetLoan, loan_id)
    if loan is None or loan.deleted_at is not None or loan.closed_at is not None:
        raise NotFound(code="asset_loan_not_found")
    text_ = (comment or "").strip() or None
    if outcome == "in_repair" and text_ is None:
        _refuse([Problem("comment", "required")])  # the repair says what is wrong (AC3)
    target = await _default_state(
        session,
        AssetStateCategory.IN_REPAIR if outcome == "in_repair" else AssetStateCategory.IN_STOCK,
    )
    items = {
        i.asset_id: i
        for i in await session.scalars(
            select(AssetLoanItem).where(
                AssetLoanItem.loan_id == loan.id,
                AssetLoanItem.returned_at.is_(None),
                AssetLoanItem.deleted_at.is_(None),
            )
        )
    }
    now = system_clock.now()
    for asset_id in dict.fromkeys(asset_ids):
        item = items.get(asset_id)
        if item is None:
            raise Conflict(code="asset_not_on_this_loan")
        item.returned_at, item.outcome, item.return_comment = now, outcome, text_
        item.updated_by = subject.user_id
        row = await _visible(session, subject, asset_id, permission=MANAGE)
        moved = await move_asset(
            session, subject, row.id, to_state_id=target.id, reason=text_,
            expected_version=row.version, source=source,
        )  # fmt: skip
        await set_holder(
            session, subject, row.id, None, expected_version=moved.version, source=source
        )
    outstanding = len(items) - len(set(asset_ids) & set(items))
    loan.version += 1
    loan.updated_by = subject.user_id
    if outstanding == 0:
        loan.closed_at = now
    await session.flush()
    await _loan_event(session, loan, "closed" if outstanding == 0 else "returned")
    return loan


async def outstanding_count(session: AsyncSession, loan_id: uuid.UUID) -> int:
    """How many of the loan's assets are still out."""
    found = await session.scalar(
        select(func.count()).where(
            AssetLoanItem.loan_id == loan_id,
            AssetLoanItem.returned_at.is_(None),
            AssetLoanItem.deleted_at.is_(None),
        )
    )
    return int(found or 0)


async def notify_due(session: AsyncSession) -> int:
    """One tenant: claim and announce loans due within a day, overdue, and warranties ending.

    Each claim is one UPDATE ... RETURNING on rows not yet noticed, so a second worker running
    at the same time finds nothing left (exactly once).
    """
    now = system_clock.now()
    due = (
        await session.execute(
            update(AssetLoan)
            .where(
                AssetLoan.closed_at.is_(None),
                AssetLoan.deleted_at.is_(None),
                AssetLoan.due_noticed_at.is_(None),
                AssetLoan.due_at <= now + DUE_NOTICE,
                AssetLoan.due_at > now,
            )
            .values(due_noticed_at=now)
            .returning(AssetLoan.id, AssetLoan.borrower_id, AssetLoan.created_by, AssetLoan.version)
        )
    ).all()
    overdue = (
        await session.execute(
            update(AssetLoan)
            .where(
                AssetLoan.closed_at.is_(None),
                AssetLoan.deleted_at.is_(None),
                AssetLoan.overdue_noticed_at.is_(None),
                AssetLoan.due_at <= now,
            )
            .values(overdue_noticed_at=now)
            .returning(AssetLoan.id, AssetLoan.borrower_id, AssetLoan.created_by, AssetLoan.version)
        )
    ).all()
    for change, rows in (("due", due), ("overdue", overdue)):
        for loan_id, borrower, by, version in rows:
            await record_event(
                session,
                AssetLoanChanged(
                    loan_id=loan_id,
                    borrower_id=borrower,
                    created_by=by,
                    change=cast("LoanChange", change),  # "due" or "overdue", from the loop above
                ),
                aggregate_id=loan_id,
                aggregate_version=version,
            )
    settings = await session.scalar(select(AssetSettings))
    days = settings.warranty_notice_days if settings is not None else 30
    horizon = (now + timedelta(days=days)).date()
    ending = (
        await session.execute(
            update(Asset)
            .where(
                Asset.deleted_at.is_(None),
                Asset.warranty_expires_on.is_not(None),
                Asset.warranty_expires_on <= horizon,
                Asset.warranty_expires_on >= now.date(),
                Asset.warranty_noticed_on.is_distinct_from(Asset.warranty_expires_on),
            )
            .values(warranty_noticed_on=Asset.warranty_expires_on)
            .returning(Asset.id, Asset.version)
            .execution_options(synchronize_session=False)
        )
    ).all()
    for asset_id, version in ending:
        await record_event(
            session,
            WarrantyEnding(asset_id=asset_id),
            aggregate_id=asset_id,
            aggregate_version=version,
        )
    return len(due) + len(overdue) + len(ending)


async def loan_sweep(database: Database, settings: Settings) -> None:
    """Every minute, in every tenant with app.tenant_id set (RLS): the notices above."""
    del settings
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            count = await notify_due(session)
        if count:
            log.info("asset_notices_claimed", tenant_id=str(tenant), notices=count)


async def outstanding_assets(session: AsyncSession, loan_id: uuid.UUID) -> list[uuid.UUID]:
    """The loan's assets still out."""
    return list(
        await session.scalars(
            select(AssetLoanItem.asset_id).where(
                AssetLoanItem.loan_id == loan_id,
                AssetLoanItem.returned_at.is_(None),
                AssetLoanItem.deleted_at.is_(None),
            )
        )
    )


async def open_loans(
    session: AsyncSession,
    subject: Subject,
    *,
    status: Literal["open", "overdue", "closed"] | None = None,
    site_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[AssetLoan]:
    """The register (REQ-AST-030): open and overdue loans by due time, or one status.

    Overdue ones lead; closed ones come most recently closed first. `site_id`: that site's only.
    """
    _require(subject, VIEW)
    now = system_clock.now()
    query = select(AssetLoan).where(AssetLoan.deleted_at.is_(None))
    if status == "closed":
        query = query.where(AssetLoan.closed_at.is_not(None)).order_by(
            AssetLoan.closed_at.desc(), AssetLoan.id
        )
    else:
        query = query.where(AssetLoan.closed_at.is_(None)).order_by(AssetLoan.due_at, AssetLoan.id)
        if status == "open":
            query = query.where(AssetLoan.due_at > now)
        elif status == "overdue":
            query = query.where(AssetLoan.due_at <= now)
    if site_id is not None:
        query = query.where(AssetLoan.site_id == site_id)
    return list(await session.scalars(query.limit(limit)))


@dataclass(frozen=True, slots=True)
class LoanAsset:
    """An asset of a loan as the loan register shows it: what, and how it came back."""

    id: uuid.UUID
    tag: str | None
    name: str
    returned_at: datetime | None
    outcome: str | None


async def loan_assets(
    session: AsyncSession, loan_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[LoanAsset]]:
    """Each loan's assets in one query, by tag (the register's rows)."""
    found: dict[uuid.UUID, list[LoanAsset]] = {loan_id: [] for loan_id in loan_ids}
    if not loan_ids:
        return found
    rows = await session.execute(
        select(AssetLoanItem.loan_id, Asset.id, Asset.tag, Asset.name, AssetLoanItem.returned_at,
               AssetLoanItem.outcome)
        .join(Asset, Asset.id == AssetLoanItem.asset_id)
        .where(AssetLoanItem.loan_id.in_(loan_ids), AssetLoanItem.deleted_at.is_(None))
        .order_by(AssetLoanItem.loan_id, Asset.tag, Asset.id)
    )  # fmt: skip
    for loan_id, asset_id, tag, name, returned_at, outcome in rows:
        found[loan_id].append(LoanAsset(asset_id, tag, name, returned_at, outcome))
    return found


async def due_dates(
    session: AsyncSession, asset_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    """When each asset still out on a loan is due back (the borrower's own list)."""
    if not asset_ids:
        return {}
    rows = await session.execute(
        select(AssetLoanItem.asset_id, AssetLoan.due_at)
        .join(AssetLoan, AssetLoan.id == AssetLoanItem.loan_id)
        .where(
            AssetLoanItem.asset_id.in_(asset_ids),
            AssetLoanItem.returned_at.is_(None),
            AssetLoanItem.deleted_at.is_(None),
        )
    )
    return dict(rows.tuples().all())


AVAILABLE_MAX = 50


async def available(
    session: AsyncSession, subject: Subject, *, text_: str | None, limit: int = AVAILABLE_MAX
) -> list[Asset]:
    """What can go on a new loan now: loanable, in an in-stock state, not out (REQ-AST-029 AC2).

    The same three checks `create_loan` makes, so the new-loan picker offers nothing it refuses;
    searched by tag, serial or name like the asset list.
    """
    _require(subject, MANAGE)
    out = select(AssetLoanItem.id).where(
        AssetLoanItem.asset_id == Asset.id,
        AssetLoanItem.returned_at.is_(None),
        AssetLoanItem.deleted_at.is_(None),
    )
    query = (
        staff_rows(subject)
        .join(AssetState, AssetState.id == Asset.state_id)
        .where(
            Asset.loanable.is_(True),
            AssetState.category == AssetStateCategory.IN_STOCK,
            ~out.exists(),
        )
    )
    if text_:
        match = await ENGINE.match(session, ASSET_SEARCH, text_)
        if match is None:
            return []
        query = query.where(match.predicate).order_by(match.rank.desc(), Asset.id)
    else:
        query = query.order_by(Asset.tag, Asset.id)
    return list(await session.scalars(query.limit(limit)))
