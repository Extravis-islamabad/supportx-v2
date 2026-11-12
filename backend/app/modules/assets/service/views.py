"""The asset list's views and product type tree (WP-049b s4a; REQ-AST-047).

- Built-in views (`AssetView`) are conditions on the list the caller may see anyway: they never
  widen what `staff_rows` allows.
- The tree: choosing a product type lists that type and every type below it (AC1); the counts
  are per type, within the view and the caller's scope, so the screen sums a branch itself.
- Saved views and favourites are kept per person in the shared list-settings store
  (app/shared/list_settings), registered here as the `assets` list.
"""

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import ColumnElement, Select, and_, exists, func, literal, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.assets.domain.catalogue import AssetStateCategory, descendants
from app.modules.assets.domain.scans import ScanResult
from app.modules.assets.domain.views import (
    CONSUMABLES_LIST_KEY,
    LIST_KEY,
    RECENT_DAYS,
    VIEW_CODES,
    AssetView,
)
from app.modules.assets.infra.models import (
    Asset,
    AssetConsumable,
    AssetProductType,
    AssetScan,
    AssetSettings,
    AssetState,
)
from app.modules.assets.service.assets import ASSET_FIELDS, ENTITY, VIEW, _tenant, staff_rows
from app.modules.identity_access import Subject
from app.shared.api.filters import FilterField, ResourceFields
from app.shared.clock import system_clock
from app.shared.list_settings import ListSpec

if TYPE_CHECKING:
    from collections.abc import Callable


async def custom_filters(session: AsyncSession) -> dict[str, FilterField]:
    """The tenant's custom asset fields, as `custom.<key>` filters (WP-026)."""
    return await metadata.filter_fields(session, ENTITY, "assets")


LIST_SPEC = ListSpec(
    key=LIST_KEY,
    permission=VIEW,
    views=VIEW_CODES,
    fields=ASSET_FIELDS,
    fields_for=custom_filters,
    feature="assets",
)
# The consumables list keeps each person's column widths too (#367's widths, now kept).
CONSUMABLES_LIST_SPEC = ListSpec(
    key=CONSUMABLES_LIST_KEY,
    permission=VIEW,
    views=(),
    fields=ResourceFields(name=CONSUMABLES_LIST_KEY, fields={}, id_column=AssetConsumable.id),
    feature="assets",
)
LIST_SPECS = (LIST_SPEC, CONSUMABLES_LIST_SPEC)


def _scan_failed() -> ColumnElement[bool]:
    # Its newest scan failed: a failed scan after the last good one (REQ-AST-054).
    return exists().where(
        AssetScan.asset_id == Asset.id,
        AssetScan.result == ScanResult.FAILED,
        or_(Asset.last_scanned_at.is_(None), AssetScan.scanned_at > Asset.last_scanned_at),
    )


def _recently_discovered() -> ColumnElement[bool]:
    since = system_clock.now() - timedelta(days=RECENT_DAYS)
    return and_(Asset.discovered_serial.is_not(None), Asset.created_at >= since)


def _in_stock() -> ColumnElement[bool]:
    return Asset.state_id.in_(
        select(AssetState.id).where(AssetState.category == AssetStateCategory.IN_STOCK)
    )


async def view_condition(
    session: AsyncSession, subject: Subject, view: AssetView
) -> ColumnElement[bool]:
    """The view's condition on `assets` (on top of the caller's own scope)."""
    if view is AssetView.WARRANTY_EXPIRING:
        settings = await session.get(AssetSettings, _tenant(session))
        days = settings.warranty_notice_days if settings is not None else 30
        today = system_clock.now().date()
        return Asset.warranty_expires_on.between(today, today + timedelta(days=days))
    if view is AssetView.MINE:
        return Asset.owner_user_id == subject.user_id
    conditions: dict[AssetView, Callable[[], ColumnElement[bool]]] = {
        AssetView.ALL: true,
        AssetView.LOANABLE: lambda: Asset.loanable.is_(True),
        AssetView.IN_STOCK: _in_stock,
        AssetView.SCAN_FAILURES: _scan_failed,
        AssetView.RECENTLY_DISCOVERED: _recently_discovered,
    }
    return conditions[view]()


async def subtree(session: AsyncSession, type_id: uuid.UUID) -> list[uuid.UUID]:
    """The product type and every type below it (AC1).

    Worked out here from the tenant's (small) type table, so the asset query carries a plain
    list the planner can weigh against the column's statistics: a rare type then walks
    `ix_assets_type_updated`, a large branch the default sort's index (the EXPLAIN test).
    """
    parents = {
        str(row.id): None if row.parent_id is None else str(row.parent_id)
        for row in await session.execute(select(AssetProductType.id, AssetProductType.parent_id))
    }
    if str(type_id) not in parents:
        return [type_id]  # unknown or another tenant's: matches nothing it may not
    return [type_id, *(uuid.UUID(t) for t in sorted(descendants(str(type_id), parents)))]


async def rows(
    session: AsyncSession,
    subject: Subject,
    *,
    view: AssetView | None,
    product_type: uuid.UUID | None,
    trash: bool,
) -> Select[Any]:
    """The asset list's statement: the caller's scope, the view, the tree node."""
    statement = staff_rows(subject, trash=trash)
    if view is not None and not trash:
        statement = statement.where(await view_condition(session, subject, view))
    if product_type is not None:
        statement = statement.where(Asset.product_type_id.in_(await subtree(session, product_type)))
    return statement


async def type_counts(
    session: AsyncSession, subject: Subject, *, view: AssetView | None
) -> dict[uuid.UUID, int]:
    """Live assets per product type, within the view and what the caller may see."""
    base = await rows(session, subject, view=view, product_type=None, trash=False)
    counted = (
        base.with_only_columns(Asset.product_type_id, func.count(literal(1)))
        .group_by(Asset.product_type_id)
        .order_by(None)
    )
    return {type_id: int(n) for type_id, n in (await session.execute(counted)).all()}
