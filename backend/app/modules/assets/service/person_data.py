"""Assets' slice of a person's erasure (ADR-052 §4; D-171; the coordinator, 2026-11-16).

What a person holds is a fact about things, not about them, so it is not erased away:
- **Open assignments and open loans stay open**, pointing at the anonymised person
  (`owner_user_id` is the asset's current holder, the same fact as its open assignment). Ending
  them would invent a return that did not happen. The approver sees how many before approving
  (`holdings`, counts only), and the asset team is told once which assets to recover
  (`assets.erased_holder.items`, a required notice), so they close them through the normal
  flow.
- **What only ever pointed forward goes:** they come off open audits' auditor lists, and their
  future bookings are cancelled. Pending acknowledgements stay as they are (the module has no
  cancelled state; an unanswered one names the anonymised person only).
- Finished loans, past bookings, answered acknowledgements and the `*_by` audit columns keep the
  person's ID, which points at the anonymised row (ADR-052 step 5).

Two ports, so references go before owned rows (the bands): `assets.references` (160) and
`assets.owned` (545, the notice). Each call is one bounded batch; a second full run counts zero
and sends no second notice. Counts by kind only, never data.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.assets.domain.audits import AuditState
from app.modules.assets.events import ErasedHolderItems
from app.modules.assets.infra.models import (
    Asset,
    AssetAssignment,
    AssetAudit,
    AssetAuditAuditor,
    AssetBooking,
    AssetLoan,
    AssetLoanItem,
)
from app.modules.assets.service.bookings import _event as booking_event
from app.modules.identity_access import (
    ERASE_BATCH,
    ErasureBatch,
    register_holdings,
    register_person_data,
)
from app.shared.events import record_event
from app.shared.events.outbox import ProcessedEvent

HELD_LIST = 200  # assets listed in the asset team's notice (the counts are always whole)
# The notice is sent once per person: its claim in `processed_events` (the consumers' own
# idempotency table), keyed by the person, so a resumed or repeated run never sends it twice.
NOTICE_CLAIM = "assets__erased_holder_notice"
_USER = "user"


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


async def _open_assignment_assets(session: AsyncSession, person_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.scalars(
        select(AssetAssignment.asset_id)
        .join(Asset, Asset.id == AssetAssignment.asset_id)
        .where(
            AssetAssignment.holder_kind == _USER,
            AssetAssignment.holder_id == person_id,
            AssetAssignment.ended_at.is_(None),
            AssetAssignment.deleted_at.is_(None),
            Asset.deleted_at.is_(None),
        )
        .order_by(AssetAssignment.asset_id)
    )
    return list(rows.all())


async def _open_loan_assets(session: AsyncSession, person_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.scalars(
        select(AssetLoanItem.asset_id)
        .join(AssetLoan, AssetLoan.id == AssetLoanItem.loan_id)
        .where(
            AssetLoan.borrower_id == person_id,
            AssetLoan.closed_at.is_(None),
            AssetLoan.deleted_at.is_(None),
            AssetLoanItem.returned_at.is_(None),
        )
        .order_by(AssetLoanItem.asset_id)
    )
    return list(rows.all())


async def holdings(session: AsyncSession, person_id: uuid.UUID) -> Mapping[str, int]:
    """What the person still holds, counted (the approver sees it before approving)."""
    loans = await session.scalar(
        select(func.count())
        .select_from(AssetLoan)
        .where(
            AssetLoan.borrower_id == person_id,
            AssetLoan.closed_at.is_(None),
            AssetLoan.deleted_at.is_(None),
        )
    )
    counts = {
        "asset_assignments_open": len(await _open_assignment_assets(session, person_id)),
        "asset_loans_open": int(loans or 0),
    }
    return {kind: count for kind, count in counts.items() if count}


class References:
    """`assets.references`: off open audits; future bookings cancelled (band 100-199)."""

    module: ClassVar[str] = "assets.references"
    order: ClassVar[int] = 160
    kinds: ClassVar[frozenset[str]] = frozenset({"audit_seats_removed", "bookings_cancelled"})

    async def erase_person(  # noqa: PLR0913 - the port contract
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """Their auditor seats on audits not closed, then a batch of their future bookings."""
        del successor_id, keep_files, cursor  # cancelled bookings no longer match: no cursor
        counts: dict[str, int] = {}
        open_audits = select(AssetAudit.id).where(AssetAudit.state != AuditState.CLOSED.value)
        seats = await session.execute(
            delete(AssetAuditAuditor).where(
                AssetAuditAuditor.user_id == person_id,
                AssetAuditAuditor.audit_id.in_(open_audits),
            )
        )
        if removed := int(getattr(seats, "rowcount", 0) or 0):
            counts["audit_seats_removed"] = removed
        bookings = list(
            await session.scalars(
                select(AssetBooking)
                .where(
                    AssetBooking.borrower_id == person_id,
                    AssetBooking.status == "booked",
                    AssetBooking.starts_at > now,
                    AssetBooking.deleted_at.is_(None),
                )
                .order_by(AssetBooking.id)
                .limit(ERASE_BATCH)
                .with_for_update()
            )
        )
        for booking in bookings:
            booking.status = "cancelled"  # the module's own cancel (bookings.cancel_booking)
            booking.version += 1
        await session.flush()
        for booking in bookings:
            await booking_event(session, booking, "cancelled")
        if bookings:
            counts["bookings_cancelled"] = len(bookings)
        more = len(bookings) == ERASE_BATCH  # cancelled ones no longer match: just call again
        return ErasureBatch(counts, "more" if more else None)


class Owned:
    """`assets.owned`: the asset team told once what the person still holds (band 500-599)."""

    module: ClassVar[str] = "assets.owned"
    order: ClassVar[int] = 545
    kinds: ClassVar[frozenset[str]] = frozenset({"holder_notices_sent"})

    async def erase_person(  # noqa: PLR0913 - the port contract
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """One notice, the first time only, when they still hold or have on loan any asset."""
        del successor_id, keep_files, now, cursor
        assigned = await _open_assignment_assets(session, person_id)
        loaned = await _open_loan_assets(session, person_id)
        if not assigned and not loaned:
            return ErasureBatch({})
        claimed = await session.execute(
            insert(ProcessedEvent)
            .values(tenant_id=_tenant(session), consumer=NOTICE_CLAIM, event_id=person_id)
            .on_conflict_do_nothing()
        )
        if not getattr(claimed, "rowcount", 0):
            return ErasureBatch({})  # told already (a resumed or repeated run)
        loans = await holdings(session, person_id)
        await record_event(
            session,
            ErasedHolderItems(
                person_id=person_id,
                asset_ids=list(dict.fromkeys([*assigned, *loaned]))[:HELD_LIST],
                assignments_open=len(assigned),
                loans_open=int(loans.get("asset_loans_open", 0)),
            ),
            aggregate_id=person_id,
        )
        return ErasureBatch({"holder_notices_sent": 1})


REFERENCES = References()
OWNED = Owned()


def register() -> None:
    """Both ports and the holdings count, at import (the job refuses while one is missing)."""
    register_person_data(REFERENCES)
    register_person_data(OWNED)
    register_holdings("assets", holdings)


__all__ = ["OWNED", "REFERENCES", "Owned", "References", "holdings", "register"]
