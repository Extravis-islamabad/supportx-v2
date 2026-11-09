"""Copying an asset, and moving many at once (WP-049a s3; REQ-AST-010, REQ-AST-001 bulk).

- **Copy (REQ-AST-010):** up to the tenant's copy limit (Appendix A: 50) at once. Each copy keeps
  the asset's product, name and ordinary fields, and gets its own tag from the pattern. The unique
  and discovered fields are not copied: serial, barcode and discovered serial. Copies start in the
  default in-stock state, and each one's history names the asset it was copied from (AC2). IT
  copies reserve their slots together, so a copy that would pass the limit is refused whole.
- **Bulk move:** up to BULK_MAX assets to one state. Each goes through the single move in its own
  savepoint, so every rule (life cycle, reason, permission, If-Match, slot) holds, and an asset
  that can't move is reported with its reason while the others go ahead.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict
from app.modules.assets.domain.assets import counts_toward_limit
from app.modules.assets.infra.models import Asset, AssetProductType, AssetSettings, AssetState
from app.modules.assets.service.assets import (
    LIMIT_CODE,
    MANAGE,
    _default_state,
    _next_tag,
    _require,
    _saved,
    _tenant,
    _visible,
)
from app.modules.assets.service.moves import move_asset
from app.modules.identity_access import Subject
from app.modules.licensing import LimitKey, hold_limit, reserve_capacity
from app.shared.history import Change, Source
from app.shared.ids import new_id

BULK_MAX = 100
DEFAULT_COPY_LIMIT = 50

# Copied as they are; everything unique, discovered or about state is left out on purpose.
_COPIED = (
    "name",
    "product_id",
    "product_type_id",
    "vendor_id",
    "site_id",
    "location",
    "purchase_order_id",
    "purchase_price",
    "purchase_tax",
    "currency",
    "acquired_on",
    "warranty_expires_on",
    "expires_on",
    "description",
    "custom",
    "custom_text",
)


async def copy_asset(
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    *,
    count: int,
    source: Source,
) -> list[Asset]:
    """`count` copies of the asset, each with a new tag, in the default in-stock state."""
    _require(subject, MANAGE)
    original = await _visible(session, subject, asset_id)
    settings = await session.get(AssetSettings, _tenant(session))
    limit = settings.copy_limit if settings is not None else DEFAULT_COPY_LIMIT
    if not 1 <= count <= limit:
        raise Conflict(code="asset_copy_limit", params={"max": limit})
    product_type = await session.get(AssetProductType, original.product_type_id)
    assert product_type is not None  # noqa: S101 - a foreign key holds it
    state = await _default_state(session)
    if counts_toward_limit(product_type.category, product_type.kind, state.category):
        await hold_limit(session, LimitKey.ASSETS)
        await reserve_capacity(session, LimitKey.ASSETS, count, code=LIMIT_CODE)
    made: list[Asset] = []
    for _ in range(count):
        row = Asset(
            id=new_id(),
            tenant_id=original.tenant_id,
            created_by=subject.user_id,
            state_id=state.id,
            tag=await _next_tag(session, product_type),
            **{name: getattr(original, name) for name in _COPIED},
        )
        session.add(row)
        await session.flush()
        changes = [
            Change("copied_from", None, str(original.id)),
            Change("state_id", None, str(state.id)),
            Change("tag", None, row.tag),
        ]
        await _saved(session, subject, row, changes, action="created", source=source)
        made.append(row)
    return made


@dataclass(frozen=True, slots=True)
class BulkMoveOutcome:
    """What happened to one asset of a bulk move."""

    asset_id: uuid.UUID
    moved: bool
    code: str | None = None
    version: int | None = None


async def bulk_move(  # noqa: PLR0913 - the assets, where to, why and the source
    session: AsyncSession,
    subject: Subject,
    items: list[tuple[uuid.UUID, int]],
    *,
    to_state_id: uuid.UUID,
    reason: str | None,
    source: Source,
) -> list[BulkMoveOutcome]:
    """Move each (asset, version read) to `to_state_id`; per asset, moved or why not."""
    _require(subject, MANAGE)
    unique = list(dict(items).items())
    if not unique:
        raise Conflict(code="asset_bulk_empty")
    if len(unique) > BULK_MAX:
        raise Conflict(code="asset_bulk_too_many", params={"max": BULK_MAX})
    if await session.scalar(select(AssetState.id).where(AssetState.id == to_state_id)) is None:
        raise Conflict(code="asset_move_not_allowed", params={"allowed": 0})
    outcomes: list[BulkMoveOutcome] = []
    for asset_id, version in unique:
        try:
            async with session.begin_nested():
                row = await move_asset(
                    session,
                    subject,
                    asset_id,
                    to_state_id=to_state_id,
                    reason=reason,
                    expected_version=version,
                    source=source,
                )
        except AppError as error:
            outcomes.append(BulkMoveOutcome(asset_id, moved=False, code=error.instance_code))
        else:
            outcomes.append(BulkMoveOutcome(asset_id, moved=True, version=row.version))
    return outcomes
