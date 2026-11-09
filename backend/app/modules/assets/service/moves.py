"""Moving an asset between states through its life cycle (WP-049a s3; REQ-AST-012, 013).

- **Which moves:** the life cycle of the asset's product type, the nearest type up the tree that
  names one, else the tenant's default life cycle. Only its listed moves are allowed; anything
  else is refused with the moves that are (409 `asset_move_not_allowed`).
- **What a move asks for:** a reason when the move or the target state requires one (REQ-AST-013
  AC1), the fields the move lists as required, and the move's permission when it names one
  (Appendix A: back to stock from retired needs `assets.reinstate`).
- **Licence (D-141):** an IT asset leaving `disposed` would take a slot again. The seeded life
  cycle has no way out of disposed, but an admin's may, so the slot is reserved race-safely.
- The move is one save of `state_id`: field history with the reason, its event on the outbox,
  If-Match on the version read. Nothing here deletes data.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, PermissionDenied
from app.modules.assets.domain.assets import counts_toward_limit
from app.modules.assets.domain.catalogue import Problem
from app.modules.assets.infra.models import (
    Asset,
    AssetLifeCycle,
    AssetLifeCycleTransition,
    AssetProductType,
    AssetState,
)
from app.modules.assets.service.assets import (
    MANAGE,
    RECORD_TYPE,
    _refuse,
    _require,
    _reserve,
    _saved,
    _visible,
)
from app.modules.identity_access import Subject
from app.shared.history import Change, Source
from app.shared.history.conflicts import stale_version

REASON_MAX = 1000


@dataclass(frozen=True, slots=True)
class MoveOption:
    """One move the asset may make now, as its screen offers it."""

    to_state: AssetState
    reason_required: bool
    required_fields: tuple[str, ...]
    permission: str | None
    allowed: bool  # False: the person lacks the move's permission (shown, not offered)


async def _life_cycle_id(session: AsyncSession, product_type_id: uuid.UUID) -> uuid.UUID | None:
    """The nearest life cycle up the type tree, else the tenant's default."""
    node = await session.get(AssetProductType, product_type_id)
    while node is not None:
        if node.life_cycle_id is not None:
            return node.life_cycle_id
        node = (
            None if node.parent_id is None else await session.get(AssetProductType, node.parent_id)
        )
    found: uuid.UUID | None = await session.scalar(
        select(AssetLifeCycle.id).where(
            AssetLifeCycle.is_default, AssetLifeCycle.deleted_at.is_(None)
        )
    )
    return found


async def _moves(session: AsyncSession, row: Asset) -> list[AssetLifeCycleTransition]:
    cycle = await _life_cycle_id(session, row.product_type_id)
    if cycle is None:
        return []
    return list(
        await session.scalars(
            select(AssetLifeCycleTransition).where(
                AssetLifeCycleTransition.life_cycle_id == cycle,
                AssetLifeCycleTransition.from_state_id == row.state_id,
            )
        )
    )


async def move_options(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID
) -> list[MoveOption]:
    """The moves the asset's life cycle lists from its state now (for its screen)."""
    row = await _visible(session, subject, asset_id)
    states = {
        s.id: s
        for s in await session.scalars(select(AssetState).where(AssetState.deleted_at.is_(None)))
    }
    options = [
        MoveOption(
            to_state=states[move.to_state_id],
            reason_required=move.reason_required or states[move.to_state_id].reason_required,
            required_fields=tuple(move.required_fields or ()),
            permission=move.permission,
            allowed=subject.holds(MANAGE)
            and (move.permission is None or subject.holds(move.permission)),
        )
        for move in await _moves(session, row)
        if move.to_state_id in states
    ]
    return sorted(options, key=lambda o: (o.to_state.sort, str(o.to_state.id)))


def _missing(row: Asset, fields: tuple[str, ...]) -> list[Problem]:
    """Required fields of the move that the asset leaves empty (a custom one: `custom.<key>`)."""
    problems: list[Problem] = []
    for name in fields:
        value: Any = (
            row.custom.get(name.removeprefix("custom."))
            if name.startswith("custom.")
            else getattr(row, name, None)
        )
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(Problem(name, "required_for_move"))
    return problems


async def move_asset(  # noqa: PLR0913 - the asset, where to, why, the If-Match and the source
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    *,
    to_state_id: uuid.UUID,
    reason: str | None,
    expected_version: int,
    source: Source,
) -> Asset:
    """Move the asset to `to_state_id` along its life cycle (with a reason where asked)."""
    _require(subject, MANAGE)
    row = await _visible(session, subject, asset_id, permission=MANAGE)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    moves = {m.to_state_id: m for m in await _moves(session, row)}
    move = moves.get(to_state_id)
    target = await session.get(AssetState, to_state_id)
    if move is None or target is None or target.deleted_at is not None:
        raise Conflict(
            code="asset_move_not_allowed",
            params={"allowed": len(moves)},  # the screen lists them (GET .../moves)
        )
    if move.permission is not None and not subject.holds(move.permission):
        raise PermissionDenied(params={"permission": move.permission})
    text = (reason or "").strip()
    problems: list[Problem] = []
    if (move.reason_required or target.reason_required) and not text:
        problems.append(Problem("reason", "required"))
    if len(text) > REASON_MAX:
        problems.append(Problem("reason", "value_too_long", (("max", REASON_MAX),)))
    problems += _missing(row, tuple(move.required_fields or ()))
    _refuse(problems)
    before = await session.get(AssetState, row.state_id)
    kind = await session.get(AssetProductType, row.product_type_id)
    assert before is not None  # noqa: S101 - a foreign key holds it
    assert kind is not None  # noqa: S101 - a foreign key holds it
    counted = counts_toward_limit(kind.category, kind.kind, before.category)
    if not counted and counts_toward_limit(kind.category, kind.kind, target.category):
        await _reserve(session)
    old = row.state_id
    row.state_id = target.id
    await _saved(
        session,
        subject,
        row,
        [Change("state_id", str(old), str(target.id))],
        action="updated",
        source=source,
        reason=text or None,
    )
    return row
