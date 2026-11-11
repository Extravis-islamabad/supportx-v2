"""Typed links between two assets (WP-049a s4; REQ-AST-027).

A link is stored once, from one asset to the other, and shown from both ends ("connected to" on
one, "connected from" on the other). Adding or removing one writes history on both assets (AC1)
and their events, so both pages refresh live. Removing keeps the row (soft delete). The person
must be able to manage the asset they add it from and see the other one.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules.assets.domain.catalogue import Problem
from app.modules.assets.domain.ownership import RELATIONSHIP_KINDS
from app.modules.assets.infra.models import Asset, AssetRelationship
from app.modules.assets.service.assets import MANAGE, _refuse, _require, _saved, _visible
from app.modules.identity_access import Subject
from app.shared.clock import system_clock
from app.shared.history import Change, Source
from app.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class Link:
    """A link as one asset sees it: which way it points, and the asset at the other end."""

    relationship: AssetRelationship
    outgoing: bool  # True: from this asset; False: to it
    other: Asset


async def _note_on_both(  # noqa: PLR0913 - both assets, the link, who and where from
    session: AsyncSession,
    subject: Subject,
    one: Asset,
    other: Asset,
    link: AssetRelationship,
    *,
    added: bool,
    source: Source,
) -> None:
    """History on each asset, naming the kind and the asset at the other end (AC1)."""
    for row, far in ((one, other), (other, one)):
        shown = f"{link.kind}:{far.id}"
        change = (
            Change("relationship", None, shown) if added else Change("relationship", shown, None)
        )
        await _saved(session, subject, row, [change], action="updated", source=source)


async def add_link(  # noqa: PLR0913 - from, to, which kind, who and where from
    session: AsyncSession,
    subject: Subject,
    from_id: uuid.UUID,
    to_id: uuid.UUID,
    kind: str,
    *,
    source: Source,
) -> AssetRelationship:
    """Link two assets; the same link twice is refused (409 asset_link_exists)."""
    _require(subject, MANAGE)
    problems: list[Problem] = []
    if kind not in RELATIONSHIP_KINDS:
        problems.append(Problem("kind", "invalid_choice"))
    if from_id == to_id:
        problems.append(Problem("to_asset_id", "asset_link_to_itself"))
    _refuse(problems)
    one = await _visible(session, subject, from_id, permission=MANAGE)
    try:
        other = await _visible(session, subject, to_id)
    except (NotFound, PermissionDenied):
        other = None
    if other is None:
        _refuse([Problem("to_asset_id", "asset_holder_not_found")])
        raise NotFound(code="asset_not_found")  # _refuse always raises; this satisfies mypy
    exists = await session.scalar(
        select(AssetRelationship.id).where(
            AssetRelationship.from_asset_id == from_id,
            AssetRelationship.to_asset_id == to_id,
            AssetRelationship.kind == kind,
            AssetRelationship.deleted_at.is_(None),
        )
    )
    if exists is not None:
        raise Conflict(code="asset_link_exists")
    link = AssetRelationship(
        id=new_id(),
        tenant_id=one.tenant_id,
        created_by=subject.user_id,
        from_asset_id=from_id,
        to_asset_id=to_id,
        kind=kind,
    )
    session.add(link)
    await session.flush()
    await _note_on_both(session, subject, one, other, link, added=True, source=source)
    return link


async def remove_link(
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    link_id: uuid.UUID,
    *,
    source: Source,
) -> None:
    """Remove one of the asset's links (kept, marked removed), with history on both assets."""
    _require(subject, MANAGE)
    link = await session.get(AssetRelationship, link_id)
    if (
        link is None
        or link.deleted_at is not None
        or asset_id not in (link.from_asset_id, link.to_asset_id)
    ):
        raise NotFound(code="asset_link_not_found")
    one = await _visible(session, subject, link.from_asset_id, permission=MANAGE)
    other = await _visible(session, subject, link.to_asset_id)
    link.deleted_at = system_clock.now()
    link.updated_by = subject.user_id
    await session.flush()
    await _note_on_both(session, subject, one, other, link, added=False, source=source)


async def links_of(session: AsyncSession, subject: Subject, asset_id: uuid.UUID) -> list[Link]:
    """The asset's live links from both ends, those to assets the person may see."""
    await _visible(session, subject, asset_id)
    rows = await session.scalars(
        select(AssetRelationship)
        .where(
            or_(
                AssetRelationship.from_asset_id == asset_id,
                AssetRelationship.to_asset_id == asset_id,
            ),
            AssetRelationship.deleted_at.is_(None),
        )
        .order_by(AssetRelationship.kind, AssetRelationship.created_at)
    )
    found: list[Link] = []
    for link in rows:
        outgoing = link.from_asset_id == asset_id
        try:
            other = await _visible(
                session, subject, link.to_asset_id if outgoing else link.from_asset_id
            )
        except (NotFound, PermissionDenied):  # hidden: left out, never named
            continue
        found.append(Link(link, outgoing, other))
    return found
