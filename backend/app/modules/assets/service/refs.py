"""What other modules may know of assets (REQ-AST-025; agreed with lane A, 2026-11-06).

Work items keep their own link table and never read asset tables; they ask here:
- `can_see(session, subject, asset_id)`: before a person links an asset to a record;
- `asset_refs(session, subject, ids)`: names for a record's linked assets in one call. A removed
  asset, or one the person may not see, comes back marked (`gone` / `hidden`), never silently
  missing and never named;
- `assets_of(session, user_id)`: what a person holds, for an emailed incident (lane A attaches
  it when there is exactly one).
`assets.asset.changed` (with `changed_fields`) is the hint that a name or state changed.

The picker (`GET /assets/picker`) lists the person's own assets first, then their department's
when the tenant allows it, then a search by tag, serial or name within what the caller may see.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.modules.assets.infra.models import Asset, AssetSettings
from app.modules.assets.service.assets import VIEW, _tenant, _visible, staff_rows
from app.modules.identity_access import Subject, person_placement
from app.shared.search import ENGINE, SearchDocument

PICKER_MAX = 50
# The asset list's own search document (api/records.py's TEXT), over the generated columns.
ASSET_SEARCH = SearchDocument(
    vector=Asset.__table__.c.search_vector, short_text=Asset.__table__.c.search_text
)


@dataclass(frozen=True, slots=True)
class AssetRef:
    """An asset as another module shows it: never more than this."""

    id: uuid.UUID
    tag: str | None
    name: str | None  # None when gone or hidden
    state_id: uuid.UUID | None
    gone: bool = False
    hidden: bool = False
    mine: bool = False


def _ref(row: Asset, *, mine: bool = False) -> AssetRef:
    return AssetRef(row.id, row.tag, row.name, row.state_id, mine=mine)


async def can_see(session: AsyncSession, subject: Subject, asset_id: uuid.UUID) -> bool:
    """Whether the person may see (and so link) this asset."""
    try:
        await _visible(session, subject, asset_id)
    except (NotFound, PermissionDenied):
        held = await session.scalar(
            select(Asset.id).where(
                Asset.id == asset_id,
                Asset.deleted_at.is_(None),
                Asset.owner_user_id == subject.user_id,
            )
        )
        return held is not None  # a requester may always link what they hold
    return True


async def asset_refs(
    session: AsyncSession, subject: Subject, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, AssetRef]:
    """One call for a record's linked assets; gone or hidden ones marked, never named."""
    unique = list(dict.fromkeys(ids))
    if not unique:
        return {}
    rows = {r.id: r for r in await session.scalars(select(Asset).where(Asset.id.in_(unique)))}
    found: dict[uuid.UUID, AssetRef] = {}
    for asset_id in unique:
        row = rows.get(asset_id)
        if row is None or row.deleted_at is not None:
            found[asset_id] = AssetRef(asset_id, None, None, None, gone=True)
        elif await can_see(session, subject, asset_id):
            found[asset_id] = _ref(row, mine=row.owner_user_id == subject.user_id)
        else:
            found[asset_id] = AssetRef(asset_id, None, None, None, hidden=True)
    return found


async def assets_of(session: AsyncSession, user_id: uuid.UUID) -> list[AssetRef]:
    """What a person holds now, by name (for an emailed incident, REQ-AST-025 AC2)."""
    rows = await session.scalars(
        select(Asset)
        .where(Asset.owner_user_id == user_id, Asset.deleted_at.is_(None))
        .order_by(Asset.name, Asset.id)
    )
    return [_ref(r, mine=True) for r in rows]


async def picker(
    session: AsyncSession,
    subject: Subject,
    *,
    for_user: uuid.UUID | None,
    text: str | None,
    limit: int = PICKER_MAX,
) -> list[AssetRef]:
    """The asset picker on a record: the person's own first, then a search (REQ-AST-025)."""
    person = for_user or subject.user_id
    settings = await session.get(AssetSettings, _tenant(session))
    own_only = settings is None or settings.portal_own_assets_only
    placement = None if own_only else await person_placement(session, person)
    holders = [Asset.owner_user_id == person]
    if placement is not None and placement.department_id is not None:
        holders.append(Asset.department_id == placement.department_id)
    staff = subject.holds(VIEW)
    for_someone_else = for_user is not None and for_user != subject.user_id
    if for_someone_else and not staff:
        return []  # only staff pick for someone else
    # Your own assets are yours to see; someone else's only within your own asset scope, so
    # naming a person never shows assets outside your sites or groups (lane A's #307 review).
    base = (
        staff_rows(subject) if for_someone_else else select(Asset).where(Asset.deleted_at.is_(None))
    )
    theirs = base.where(or_(*holders))
    found: list[AssetRef] = [
        _ref(r, mine=True) for r in await session.scalars(theirs.order_by(Asset.name).limit(limit))
    ]
    if staff and text and len(found) < limit:
        match = await ENGINE.match(session, ASSET_SEARCH, text)
        if match is not None:
            seen = {r.id for r in found}
            more = await session.scalars(
                staff_rows(subject)
                .where(match.predicate)
                .order_by(match.rank.desc(), Asset.id)
                .limit(limit)
            )
            found += [_ref(r) for r in more if r.id not in seen][: limit - len(found)]
    return found
