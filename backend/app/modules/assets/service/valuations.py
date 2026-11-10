"""An asset's figures: cost totals, depreciation settings in effect, book value (WP-049b s2).

`figures` works them out afresh from the asset, its product, its cost lines and its disposal,
with the rules of `domain/financials.py`. The record page always reads them this way.

`refresh` keeps `asset_valuations` (what reports group by cost centre, REQ-AST-038 AC2) in step:
called in the transaction of every save that changes an asset's money, and from a daily sweep,
since book values move with time and a product's depreciation defaults reach its assets there.
No person edits a valuation; it carries no version and no history (it is derived).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.assets.domain.financials import (
    CostSummary,
    ResolvedTerms,
    ScheduleYear,
    Terms,
    book_value,
    resolve,
    schedule,
    summarize,
)
from app.modules.assets.infra.models import (
    Asset,
    AssetCost,
    AssetDisposal,
    AssetProduct,
    AssetSettings,
    AssetValuation,
)
from app.shared.clock import system_clock

log = get_logger(__name__)

# The asset fields whose change moves its figures (a save of one refreshes its valuation).
VALUED_FIELDS = frozenset(
    {
        "purchase_price",
        "purchase_tax",
        "acquired_on",
        "product_id",
        "depreciation_method",
        "useful_life_years",
        "salvage_value",
        "deleted",
    }
)
SWEEP_BATCH = 500


def today() -> date:
    """The day figures are worked out for (UTC)."""
    return system_clock.now().astimezone(UTC).date()


@dataclass(frozen=True, slots=True)
class Figures:
    """Everything the Financials tab shows, worked out now."""

    summary: CostSummary
    purchase_known: bool
    terms: ResolvedTerms
    starts_on: date | None
    book_value: Decimal | None  # None while no purchase cost is known
    schedule: list[ScheduleYear]
    on: date


async def _purchase(session: AsyncSession, row: Asset) -> Decimal | None:
    """Price plus tax, or the price alone where the tenant's cost excludes tax (D-141)."""
    if row.purchase_price is None and row.purchase_tax is None:
        return None
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    settings = await session.get(AssetSettings, tenant)
    with_tax = settings is None or settings.cost_includes_tax
    tax = (row.purchase_tax or Decimal(0)) if with_tax else Decimal(0)
    return (row.purchase_price or Decimal(0)) + tax


async def lines_of(session: AsyncSession, asset_id: uuid.UUID) -> list[AssetCost]:
    """The asset's live cost lines, oldest first."""
    return list(
        await session.scalars(
            select(AssetCost)
            .where(AssetCost.asset_id == asset_id, AssetCost.deleted_at.is_(None))
            .order_by(AssetCost.incurred_on, AssetCost.id)
        )
    )


async def figures(
    session: AsyncSession,
    row: Asset,
    *,
    on: date | None = None,
    lines: list[AssetCost] | None = None,
) -> Figures:
    """The asset's totals, depreciation in effect and book value on `on` (today)."""
    on = on or today()
    lines = await lines_of(session, row.id) if lines is None else lines
    purchase = await _purchase(session, row)
    disposal = await session.scalar(
        select(AssetDisposal.cost).where(
            AssetDisposal.asset_id == row.id, AssetDisposal.deleted_at.is_(None)
        )
    )
    summary = summarize(purchase, [(line.kind, line.amount) for line in lines])
    if disposal is not None:  # the disposal record's own cost (REQ-AST-017) counts as disposal
        summary = CostSummary(summary.purchase, summary.operational, summary.disposal + disposal)
    product = await session.get(AssetProduct, row.product_id)
    terms = resolve(
        asset_method=row.depreciation_method,
        asset_life=row.useful_life_years,
        asset_salvage=row.salvage_value,
        product_method=None if product is None else product.depreciation_method,
        product_life=None if product is None else product.useful_life_years,
        product_salvage=None if product is None else product.salvage_value,
    )
    applied = Terms(
        method=terms.method,
        cost=purchase or Decimal(0),
        starts_on=row.acquired_on,
        life_years=terms.life_years,
        salvage=terms.salvage or Decimal(0),
    )
    return Figures(
        summary=summary,
        purchase_known=purchase is not None,
        terms=terms,
        starts_on=row.acquired_on,
        book_value=None if purchase is None else book_value(applied, on),
        schedule=schedule(applied) if purchase is not None else [],
        on=on,
    )


async def refresh(session: AsyncSession, row: Asset, *, on: date | None = None) -> None:
    """Write the asset's valuation as it is now (in the caller's transaction)."""
    found = await figures(session, row, on=on)
    values = {
        "book_value": found.book_value,
        "total_cost": found.summary.total,
        "valued_on": found.on,
    }
    statement = insert(AssetValuation).values(tenant_id=row.tenant_id, asset_id=row.id, **values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[AssetValuation.tenant_id, AssetValuation.asset_id],
            set_={**values, "updated_at": func.now()},
        )
    )


async def refresh_stale(session: AsyncSession, *, on: date | None = None) -> int:
    """Value up to SWEEP_BATCH live assets not valued on `on` yet; how many were."""
    on = on or today()
    stale = (
        select(Asset)
        .outerjoin(AssetValuation, AssetValuation.asset_id == Asset.id)
        .where(
            Asset.deleted_at.is_(None),
            or_(AssetValuation.asset_id.is_(None), AssetValuation.valued_on < on),
        )
        .order_by(Asset.id)
        .limit(SWEEP_BATCH)
    )
    rows = list(await session.scalars(stale))
    for row in rows:
        await refresh(session, row, on=on)
    return len(rows)


async def valuation_sweep(database: Database, settings: Settings) -> None:
    """Each tenant's assets valued once a day (RLS: app.tenant_id set), in batches."""
    del settings
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    started = datetime.now(UTC)
    for tenant in tenants:
        total = 0
        while True:
            async with database.tenant_session(TenantContext(tenant)) as session:
                count = await refresh_stale(session)
            total += count
            if count < SWEEP_BATCH:
                break
        if total:
            log.info("asset_valuations_refreshed", tenant_id=str(tenant), assets=total)
    log.debug("asset_valuation_sweep_done", seconds=(datetime.now(UTC) - started).seconds)
