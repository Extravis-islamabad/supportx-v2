"""Disposing of an asset with a record (WP-049a s3; REQ-AST-017).

- **One step:** the record (date, reason, method, cost, approver) and the move to the tenant's
  default disposed state go together, in one transaction, through the life cycle's own move: a
  life cycle with no way into disposed from the asset's state refuses (409), and the move's
  reason is the disposal's reason. One record per asset.
- **Clean-up first (AC1, AC2):** other modules register a guard that names what still holds the
  asset (an open loan, allocated licences). Loans (session 5) and licences (WP-052) register
  theirs; until then nothing holds an asset.
- **Read-only after (AC3):** a disposed asset is changed only with `assets.edit_disposed`, and
  every such change asks for a reason (service/assets.py, update_asset).
- **The certificate** of data wiping or destruction is a file linked to the record (owner type
  `asset_disposal`), through the shared files API; whoever may see the asset sees it.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules.assets.domain.catalogue import AssetStateCategory, Problem
from app.modules.assets.domain.disposal import disposal_problems
from app.modules.assets.infra.models import Asset, AssetDisposal, AssetState
from app.modules.assets.service.assets import MANAGE, _refuse, _require, _visible
from app.modules.assets.service.moves import move_asset
from app.modules.identity_access import Subject, active_user_ids
from app.shared.clock import system_clock
from app.shared.history import Source
from app.shared.ids import new_id

if TYPE_CHECKING:
    from datetime import date

# Names what still holds an asset (a refusal code such as `asset_on_loan`), or None.
DisposalGuard = Callable[[AsyncSession, uuid.UUID], Awaitable[str | None]]
_GUARDS: list[DisposalGuard] = []


def register_disposal_guard(guard: DisposalGuard) -> None:
    """At start-up: a check run before an asset is disposed of."""
    if guard not in _GUARDS:
        _GUARDS.append(guard)


def unregister_disposal_guard(guard: DisposalGuard) -> None:
    """At shutdown."""
    if guard in _GUARDS:
        _GUARDS.remove(guard)


async def _disposed_state(session: AsyncSession) -> AssetState:
    found = await session.scalar(
        select(AssetState).where(
            AssetState.category == AssetStateCategory.DISPOSED,
            AssetState.is_default_for_category,
            AssetState.deleted_at.is_(None),
        )
    )
    if found is None:  # seeded with the catalogue; a default state cannot be removed
        raise Conflict(code="asset_no_disposed_state")
    return found


async def _approver_problems(session: AsyncSession, approver: uuid.UUID | None) -> list[Problem]:
    if approver is None:
        return []
    active = await active_user_ids(session, [approver])
    return [] if approver in active else [Problem("approved_by", "approver_not_active")]


async def get_disposal(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID
) -> AssetDisposal:
    """The asset's disposal record, for whoever may see the asset."""
    await _visible(session, subject, asset_id)
    found = await session.scalar(select(AssetDisposal).where(AssetDisposal.asset_id == asset_id))
    if found is None:
        raise NotFound(code="asset_disposal_not_found")
    return found


async def dispose_asset(  # noqa: PLR0913 - the asset, the record, the If-Match and the source
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> tuple[Asset, AssetDisposal]:
    """Record the disposal and move the asset to the disposed state, in one step."""
    _require(subject, MANAGE)
    row = await _visible(session, subject, asset_id, permission=MANAGE)
    if await session.scalar(select(AssetDisposal.id).where(AssetDisposal.asset_id == row.id)):
        raise Conflict(code="asset_already_disposed")
    disposed_on: date | None = values.get("disposed_on")
    approver: uuid.UUID | None = values.get("approved_by")
    currency: str | None = values.get("currency")
    problems = disposal_problems(
        disposed_on=disposed_on,
        today=system_clock.now().date(),
        method=values.get("method"),
        reason=values.get("reason"),
        cost=values.get("cost"),
        currency=currency,
    )
    problems += await _approver_problems(session, approver)
    _refuse(problems)
    for guard in _GUARDS:
        code = await guard(session, row.id)
        if code is not None:
            raise Conflict(code=code)
    reason = str(values["reason"]).strip()
    target = await _disposed_state(session)
    moved = await move_asset(
        session,
        subject,
        row.id,
        to_state_id=target.id,
        reason=reason,
        expected_version=expected_version,
        source=source,
    )
    cost = values.get("cost")
    record = AssetDisposal(
        id=new_id(),
        tenant_id=row.tenant_id,
        created_by=subject.user_id,
        asset_id=row.id,
        disposed_on=disposed_on,
        method=values["method"],
        reason=reason,
        cost=None if cost is None else Decimal(str(cost)),
        currency=currency,
        approved_by=approver,
    )
    session.add(record)
    await session.flush()
    return moved, record
