"""An asset's financials: cost lines, totals, depreciation and book value (WP-049b s2).

Parity 07 §9 (REQ-AST-036, 037, 038):
- **Who:** everything here needs `assets.view_financials` on top of seeing the asset (the asset
  manager's and the administrators' by default); changing cost lines also needs `assets.manage`
  on the asset. Without it the API refuses (403) and the console shows no money.
- **Cost lines** are in the tenant's base currency (organization's settings); the purchase is
  the asset's own price and tax, the disposal record's cost counts as disposal. Totals are
  exact decimals (`domain/financials.py`).
- **Depreciation** is set on the asset through its usual save (`assets.update_asset`, which asks
  for this permission when depreciation settings are sent) or inherited from its product.
- Every change keeps history on the asset (a part added, changed or removed: the line's ID only,
  never its amount, since the asset's history is read by everyone who may see the asset) and on
  the line itself, writes its event to the outbox and refreshes the asset's valuation, all in
  the same transaction.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.modules.assets.domain.financials import CostKind, cost_line_problems
from app.modules.assets.events import AssetCostChanged, PartAction
from app.modules.assets.infra.models import Asset, AssetCost
from app.modules.assets.service import valuations
from app.modules.assets.service.assets import (
    MANAGE,
    RECORD_TYPE,
    VIEW,
    VIEW_FINANCIALS,
    _refuse,
    _visible,
)
from app.modules.assets.service.valuations import Figures
from app.modules.identity_access import Subject
from app.modules.organization import base_currency
from app.shared.events import record_event
from app.shared.history import Change, ChangeKind, Source, record_changes
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id

COST_RECORD_TYPE = "asset_cost"
# A line's own save, and what it is on the asset's history (a part of it, ADR-026).
OWN_KIND: Mapping[PartAction, ChangeKind] = {
    "created": "created",
    "updated": "updated",
    "deleted": "deleted",
}
PART_KIND: Mapping[PartAction, ChangeKind] = {
    "created": "child_added",
    "updated": "child_changed",
    "deleted": "child_removed",
}
LINES_MAX = 2000  # per asset: far more than any asset has; the page lists them all


def _require(subject: Subject, *permissions: str) -> None:
    for permission in permissions:
        if not subject.holds(permission):
            raise PermissionDenied(params={"permission": permission})


async def _asset(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID, *, manage: bool = False
) -> Asset:
    _require(subject, VIEW, VIEW_FINANCIALS, *((MANAGE,) if manage else ()))
    return await _visible(session, subject, asset_id, permission=MANAGE if manage else VIEW)


@dataclass(frozen=True, slots=True)
class AssetFinancials:
    """The Financials tab: the base currency, the figures and the cost lines."""

    asset: Asset
    currency: str
    figures: Figures
    lines: list[AssetCost]


async def financials(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID, *, on: date | None = None
) -> AssetFinancials:
    """The asset's money as it is on `on` (today): totals, depreciation, book value, lines."""
    row = await _asset(session, subject, asset_id)
    lines = (await valuations.lines_of(session, row.id))[:LINES_MAX]
    return AssetFinancials(
        asset=row,
        currency=await base_currency(session),
        figures=await valuations.figures(session, row, on=on, lines=lines),
        lines=lines,
    )


def _clean(values: Mapping[str, Any], *, creating: bool) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    if "kind" in values or creating:
        cleaned["kind"] = str(CostKind(values["kind"]))  # the API checked the code
    if "incurred_on" in values or creating:
        cleaned["incurred_on"] = values["incurred_on"]
    if "amount" in values or creating:
        amount = values.get("amount")
        cleaned["amount"] = None if amount is None else Decimal(str(amount))
    if "description" in values:
        text = " ".join(str(values["description"] or "").split())
        cleaned["description"] = text or None
    # A change that leaves the amount alone keeps the one it has (always valid).
    amount = cleaned["amount"] if "amount" in cleaned else Decimal(0)
    _refuse(cost_line_problems(amount, cleaned.get("description")))
    return cleaned


async def _saved(  # noqa: PLR0913 - one save of a line: who, what, how, where from
    session: AsyncSession,
    subject: Subject,
    asset: Asset,
    line: AssetCost,
    changes: list[Change],
    *,
    action: PartAction,
    source: Source,
) -> None:
    """History on the line and on the asset (ID only), the event, the valuation."""
    if action != "created":
        line.version += 1
    line.updated_by = subject.user_id
    await session.flush()
    await session.refresh(line)
    await record_changes(
        session,
        record_type=COST_RECORD_TYPE,
        record_id=line.id,
        version=line.version,
        kind=OWN_KIND[action],
        changes=changes,
        source=source,
    )
    part = str(line.id)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=asset.id,
        version=asset.version,
        kind=PART_KIND[action],
        changes=[Change("cost", None if action == "created" else part, part)],
        source=source,
    )
    await record_event(
        session,
        AssetCostChanged(asset_id=asset.id, cost_id=line.id, action=action),
        aggregate_id=line.id,
        aggregate_version=line.version,
    )
    await valuations.refresh(session, asset)


def _json(value: object) -> Any:  # noqa: ANN401 - history stores JSON values
    return str(value) if isinstance(value, Decimal | date | uuid.UUID) else value


async def add_cost(
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    source: Source,
) -> AssetCost:
    """A new cost line (base currency) on an asset the subject manages."""
    asset = await _asset(session, subject, asset_id, manage=True)
    cleaned = _clean(values, creating=True)
    line = AssetCost(
        id=new_id(),
        tenant_id=asset.tenant_id,
        asset_id=asset.id,
        created_by=subject.user_id,
        **cleaned,
    )
    session.add(line)
    await session.flush()
    changes = [Change(k, None, _json(v)) for k, v in cleaned.items() if v is not None]
    await _saved(session, subject, asset, line, changes, action="created", source=source)
    return line


async def _line(session: AsyncSession, asset: Asset, cost_id: uuid.UUID) -> AssetCost:
    line = await session.scalar(
        select(AssetCost)
        .where(
            AssetCost.id == cost_id,
            AssetCost.asset_id == asset.id,
            AssetCost.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if line is None:
        raise NotFound(code="asset_cost_not_found")
    return line


async def update_cost(  # noqa: PLR0913 - the line, its version, the change and its source
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    cost_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> AssetCost:
    """Change the line's fields sent (If-Match)."""
    asset = await _asset(session, subject, asset_id, manage=True)
    line = await _line(session, asset, cost_id)
    if line.version != expected_version:
        raise await stale_version(
            session, line, expected_version=expected_version, record_type=COST_RECORD_TYPE,
            record_id=line.id,
        )  # fmt: skip
    cleaned = _clean(values, creating=False)
    changes: list[Change] = []
    for name, value in cleaned.items():
        if getattr(line, name) != value:
            changes.append(Change(name, _json(getattr(line, name)), _json(value)))
            setattr(line, name, value)
    if changes:
        await _saved(session, subject, asset, line, changes, action="updated", source=source)
    return line


async def delete_cost(  # noqa: PLR0913 - the line, its version and the source
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    cost_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a line (kept, marked removed: history keeps what it was)."""
    asset = await _asset(session, subject, asset_id, manage=True)
    line = await _line(session, asset, cost_id)
    if line.version != expected_version:
        raise await stale_version(
            session, line, expected_version=expected_version, record_type=COST_RECORD_TYPE,
            record_id=line.id,
        )  # fmt: skip
    line.deleted_at = datetime.now(UTC)
    removed = [Change("deleted", old=False, new=True)]
    await _saved(session, subject, asset, line, removed, action="deleted", source=source)
