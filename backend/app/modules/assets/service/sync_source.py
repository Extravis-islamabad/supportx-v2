"""What the CMDB's sync rules may read of assets (REQ-CMDB-015; WP-053 S4a, lane C's condition 3).

The CMDB never reads asset tables (rule e); a sync rule asks here.

- **Syncable fields** (`SYNCABLE`): the narrowest set that fills a CI, each with the kind of
  value it holds. Never money (`assets.view_financials`, D-157/D-164), never a person (the
  holder, the department), never a custom field (one may be sealed, ADR-050, or under a field
  access rule, ADR-047). A field not listed here is refused by the rule (422).
- **The filter** is the asset list's own DSL over a few catalogue fields (`FILTER_FIELDS`): what
  a rule selects by, never by a person or money.
- **Who reads:** `subject` given, only what that person may see (a rule's preview runs as its
  author, lane C's condition 2); `subject=None` is the CMDB's sync identity, which reads every
  live asset of the tenant (its rules are made only by people who see every asset anyway,
  lane C's condition 1). Values come back for the syncable fields only.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets.infra.models import Asset
from app.modules.assets.service.assets import ASSET_FIELDS, ASSETS, VIEW
from app.modules.identity_access import Subject, scope_filter
from app.shared.api.filters import ResourceFields, compile_filter
from app.shared.clock import system_clock

PAGE_MAX = 500


class SyncFieldKind(StrEnum):
    """What a syncable field holds (the CMDB maps only like to like)."""

    TEXT = "text"
    SITE = "site"
    GROUP = "group"


SYNCABLE: Mapping[str, SyncFieldKind] = {
    "name": SyncFieldKind.TEXT,
    "description": SyncFieldKind.TEXT,
    "tag": SyncFieldKind.TEXT,
    "serial_number": SyncFieldKind.TEXT,
    "barcode": SyncFieldKind.TEXT,
    "location": SyncFieldKind.TEXT,
    "site_id": SyncFieldKind.SITE,
    "managed_by_group_id": SyncFieldKind.GROUP,
}
_FILTERABLE = (
    "product_type_id",
    "product_id",
    "state_id",
    "site_id",
    "managed_by_group_id",
    "vendor_id",
    "name",
    "tag",
)
FILTER_FIELDS = ResourceFields(
    name="asset_sync",
    fields={key: ASSET_FIELDS.fields[key] for key in _FILTERABLE},
    id_column=Asset.id,
    default_sort=("id",),
)


@dataclass(frozen=True)
class SyncedAsset:
    """One asset as a sync rule sees it: its ID, its tag and its syncable values."""

    id: uuid.UUID
    tag: str | None
    values: dict[str, Any]


def syncable_fields() -> Mapping[str, SyncFieldKind]:
    """The fields a sync rule may map, by kind."""
    return SYNCABLE


def filter_fields() -> tuple[str, ...]:
    """The asset fields a sync rule's filter may use."""
    return _FILTERABLE


def check_filter(tree: Any) -> None:  # noqa: ANN401 - a parsed JSON filter
    """422 `invalid_filter` unless the filter uses only the sync's filter fields."""
    if tree is not None:
        compile_filter(tree, FILTER_FIELDS, now=system_clock.now(), path="filter")


def _rows(subject: Subject | None, tree: Any) -> Select[Any]:  # noqa: ANN401 - parsed JSON
    reach: ColumnElement[bool] = true() if subject is None else scope_filter(subject, VIEW, ASSETS)
    matches: ColumnElement[bool] = (
        true()
        if tree is None
        else compile_filter(tree, FILTER_FIELDS, now=system_clock.now(), path="filter")
    )
    return select(Asset).where(Asset.deleted_at.is_(None), reach, matches)


def _synced(row: Asset) -> SyncedAsset:
    return SyncedAsset(row.id, row.tag, {key: getattr(row, key) for key in SYNCABLE})


async def sync_page(
    session: AsyncSession,
    subject: Subject | None,
    tree: Any,  # noqa: ANN401 - a parsed JSON filter
    *,
    after: uuid.UUID | None,
    limit: int,
) -> list[SyncedAsset]:
    """The next matching assets by ID (keyset), at most `limit` (≤ PAGE_MAX)."""
    rows = _rows(subject, tree)
    if after is not None:
        rows = rows.where(Asset.id > after)
    found = await session.scalars(rows.order_by(Asset.id).limit(max(1, min(limit, PAGE_MAX))))
    return [_synced(r) for r in found]


async def sync_count(
    session: AsyncSession,
    subject: Subject | None,
    tree: Any,  # noqa: ANN401 - a parsed JSON filter
) -> int:
    """How many live assets match."""
    rows = _rows(subject, tree).with_only_columns(func.count()).order_by(None)
    return int(await session.scalar(rows) or 0)


async def sync_assets(
    session: AsyncSession,
    tree: Any,  # noqa: ANN401 - a parsed JSON filter
    ids: Sequence[uuid.UUID],
) -> list[SyncedAsset]:
    """The sync identity re-reading changed assets: those of `ids` still live and matching."""
    if not ids:
        return []
    found = await session.scalars(
        _rows(None, tree).where(Asset.id.in_(list(dict.fromkeys(ids)))).order_by(Asset.id)
    )
    return [_synced(r) for r in found]
