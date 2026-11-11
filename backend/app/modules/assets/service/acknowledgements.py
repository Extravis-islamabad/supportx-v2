"""People acknowledge the assets they are given, and see their own (WP-049a s4; REQ-AST-023, 024).

- Giving a person an asset whose product type asks for acknowledgement creates a pending one
  for that holding (AC1). Only that person answers it: accept, or dispute with a comment
  (AC2, AC3), recorded with when and through which channel. A dispute never touches the holding
  or its history; the assigning technician hears of it (the `asset.ack_disputed` notification).
- It works without mail: the person answers in the portal (AC4).
- "My assets" (024): what the person holds, and their department's when the tenant allows it
  (`portal_own_assets_only` off), each with its acknowledgement. A person needs no asset
  permission to see what they hold.
"""

import uuid
from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules.assets.domain.catalogue import Problem
from app.modules.assets.events import AcknowledgementChanged
from app.modules.assets.infra.models import (
    Asset,
    AssetAcknowledgement,
    AssetAssignment,
    AssetProductType,
    AssetSettings,
)
from app.modules.assets.service.assets import _refuse, _tenant
from app.modules.identity_access import Subject, person_placement
from app.shared.clock import system_clock
from app.shared.events import record_event
from app.shared.ids import new_id

COMMENT_MAX = 2000
CHANNELS = ("portal", "console", "mail")


@dataclass(frozen=True, slots=True)
class MyAsset:
    """An asset the person holds (or their department does), with its acknowledgement."""

    asset: Asset
    acknowledgement: AssetAcknowledgement | None
    through_department: bool


async def _changed(session: AsyncSession, ack: AssetAcknowledgement) -> None:
    await record_event(
        session,
        AcknowledgementChanged(
            acknowledgement_id=ack.id,
            asset_id=ack.asset_id,
            user_id=ack.user_id,
            # The column's check holds it to these three.
            status=cast("Literal['pending', 'accepted', 'disputed']", ack.status),
        ),
        aggregate_id=ack.id,
        aggregate_version=ack.version,
    )


async def ask_if_needed(
    session: AsyncSession, row: Asset, holding: AssetAssignment, by: uuid.UUID | None
) -> AssetAcknowledgement | None:
    """A pending acknowledgement for a person's new holding, when its type asks for one."""
    if holding.holder_kind != "user":
        return None
    kind = await session.get(AssetProductType, row.product_type_id)
    if kind is None or not kind.ack_required:
        return None
    ack = AssetAcknowledgement(
        id=new_id(),
        tenant_id=row.tenant_id,
        created_by=by,
        asset_id=row.id,
        assignment_id=holding.id,
        user_id=holding.holder_id,
    )
    session.add(ack)
    await session.flush()
    await _changed(session, ack)
    return ack


async def answer(  # noqa: PLR0913 - which, who, the answer, why and where from
    session: AsyncSession,
    subject: Subject,
    ack_id: uuid.UUID,
    *,
    accept: bool,
    comment: str | None,
    channel: str,
) -> AssetAcknowledgement:
    """The person accepts or disputes their own pending acknowledgement (AC2, AC3)."""
    ack = await session.get(AssetAcknowledgement, ack_id)
    if ack is None or ack.deleted_at is not None or ack.user_id != subject.user_id:
        raise NotFound(code="asset_acknowledgement_not_found")  # someone else's: not here
    if ack.status != "pending":
        raise Conflict(code="asset_acknowledgement_answered", params={"status": ack.status})
    text = (comment or "").strip() or None
    problems: list[Problem] = []
    if not accept and text is None:
        problems.append(Problem("comment", "required"))  # a dispute says what is wrong
    if text is not None and len(text) > COMMENT_MAX:
        problems.append(Problem("comment", "value_too_long", (("max", COMMENT_MAX),)))
    if channel not in CHANNELS:
        problems.append(Problem("channel", "invalid_choice"))
    _refuse(problems)
    ack.status = "accepted" if accept else "disputed"
    ack.comment = text
    ack.channel = channel
    ack.answered_at = system_clock.now()
    ack.updated_by = subject.user_id
    ack.version += 1
    await session.flush()
    await _changed(session, ack)
    return ack


async def mine(session: AsyncSession, subject: Subject) -> list[MyAsset]:
    """What the person holds, and their department's when the tenant shows it (REQ-AST-024)."""
    settings = await session.get(AssetSettings, _tenant(session))
    own_only = settings is None or settings.portal_own_assets_only
    department = (
        None if own_only else (await person_placement(session, subject.user_id)).department_id
    )
    holders = [Asset.owner_user_id == subject.user_id]
    if department is not None:
        holders.append(Asset.department_id == department)
    rows = list(
        await session.scalars(
            select(Asset)
            .where(Asset.deleted_at.is_(None), or_(*holders))
            .order_by(Asset.name, Asset.id)
        )
    )
    acks = {
        a.asset_id: a
        for a in await session.scalars(
            select(AssetAcknowledgement)
            .where(
                AssetAcknowledgement.user_id == subject.user_id,
                AssetAcknowledgement.deleted_at.is_(None),
            )
            .order_by(AssetAcknowledgement.created_at)
        )
    }
    return [
        MyAsset(row, acks.get(row.id), through_department=row.owner_user_id != subject.user_id)
        for row in rows
    ]
