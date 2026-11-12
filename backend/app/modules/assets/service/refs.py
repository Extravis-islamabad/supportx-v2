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
The paged picker (`GET /assets/picker/search`, WP-049b s4a, REQ-AST-046) filters by product type
(and the types below it) and site, finds part of a name, tag, barcode, serial or discovered
serial, and pages by cursor; staff search what their own asset scope reaches, anyone else only
what they hold (AC2).
"""

import base64
import binascii
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest, NotFound, PermissionDenied
from app.modules.assets.infra.models import Asset, AssetSettings
from app.modules.assets.service.assets import VIEW, _tenant, _visible, staff_rows
from app.modules.assets.service.views import subtree
from app.modules.identity_access import Subject, person_placement
from app.shared.search import ENGINE, SearchDocument

PICKER_MAX = 50
PAGED_MAX = 100
PAGED_DEFAULT = 25
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


async def email_includes_assets(session: AsyncSession) -> bool:
    """Whether an e-mailed incident gets its requester's assets (the tenant's setting, AC2)."""
    settings = await session.get(AssetSettings, _tenant(session))
    return settings is not None and settings.email_include_assets


async def assets_of(session: AsyncSession, user_id: uuid.UUID) -> list[AssetRef]:
    """What a person holds now, by name (for an emailed incident, REQ-AST-025 AC2)."""
    rows = await session.scalars(
        select(Asset)
        .where(Asset.owner_user_id == user_id, Asset.deleted_at.is_(None))
        .order_by(Asset.name, Asset.id)
    )
    return [_ref(r, mine=True) for r in rows]


async def picker(  # noqa: PLR0913 - the picker's options, explicit
    session: AsyncSession,
    subject: Subject,
    *,
    for_user: uuid.UUID | None,
    text: str | None,
    limit: int = PICKER_MAX,
    product_type: uuid.UUID | None = None,
    site: uuid.UUID | None = None,
) -> list[AssetRef]:
    """The asset picker on a record: the person's own first, then a search (REQ-AST-025).

    `product_type` (with the types below it) and `site` narrow both parts (REQ-AST-046).
    """
    narrow = await _narrowing(session, product_type, site)
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
    theirs = base.where(or_(*holders), *narrow)
    found: list[AssetRef] = [
        _ref(r, mine=True) for r in await session.scalars(theirs.order_by(Asset.name).limit(limit))
    ]
    if staff and text and len(found) < limit:
        match = await ENGINE.match(session, ASSET_SEARCH, text)
        if match is not None:
            seen = {r.id for r in found}
            more = await session.scalars(
                staff_rows(subject)
                .where(or_(match.predicate, _part_of(text)), *narrow)
                .order_by(match.rank.desc(), Asset.id)
                .limit(limit)
            )
            found += [_ref(r) for r in more if r.id not in seen][: limit - len(found)]
    return found


# --- the paged picker (WP-049b s4a, REQ-AST-046) ---------------------------------------------


async def _narrowing(
    session: AsyncSession, product_type: uuid.UUID | None, site: uuid.UUID | None
) -> list[ColumnElement[bool]]:
    found: list[ColumnElement[bool]] = []
    if product_type is not None:
        found.append(Asset.product_type_id.in_(await subtree(session, product_type)))
    if site is not None:
        found.append(Asset.site_id == site)
    return found


def _part_of(text: str) -> ColumnElement[bool]:
    """Part of a name or identifier, anywhere in it ("4F7Q" finds "SN-224F7Q9", AC1).

    Over the generated search text (name, tag, serials, barcode), normalised as stored, so the
    trigram index serves it; LIKE's own characters are escaped.
    """
    escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = literal("%") + func.sx_search_normalize(literal(escaped)) + literal("%")
    return ASSET_SEARCH.short_text.like(pattern, escape="\\")


@dataclass(frozen=True, slots=True)
class PickerPage:
    """One page of the paged picker; `next_cursor` None on the last page."""

    items: list[AssetRef]
    next_cursor: str | None


def _encode(name: str, asset_id: uuid.UUID) -> str:
    raw = json.dumps([name, str(asset_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cursor: str) -> tuple[str, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        name, asset_id = json.loads(raw)
        return str(name), uuid.UUID(str(asset_id))
    except (ValueError, TypeError, binascii.Error) as exc:
        raise BadRequest(code="invalid_cursor") from exc


async def picker_page(  # noqa: PLR0913 - the picker's filters, explicit
    session: AsyncSession,
    subject: Subject,
    *,
    text: str | None,
    product_type: uuid.UUID | None,
    site: uuid.UUID | None,
    cursor: str | None,
    limit: int = PAGED_DEFAULT,
) -> PickerPage:
    """Assets to pick, by name, a page at a time (REQ-AST-046).

    Staff (`assets.view`) search within their own asset scope; anyone else sees only the assets
    they hold. Never more than the caller may see (AC2, REQ-CMDB-029).
    """
    limit = max(1, min(limit, PAGED_MAX))
    statement: Select[Asset] = (
        staff_rows(subject)
        if subject.holds(VIEW)
        else select(Asset).where(Asset.deleted_at.is_(None), Asset.owner_user_id == subject.user_id)
    )
    statement = statement.where(*await _narrowing(session, product_type, site))
    if text and text.strip():
        match = await ENGINE.match(session, ASSET_SEARCH, text)
        statement = statement.where(
            _part_of(text) if match is None else or_(match.predicate, _part_of(text))
        )
    if cursor is not None:
        name, after = _decode(cursor)
        statement = statement.where(
            tuple_(Asset.name, Asset.id) > tuple_(literal(name), literal(after))
        )
    rows = list(await session.scalars(statement.order_by(Asset.name, Asset.id).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return PickerPage(
        items=[_ref(r, mine=r.owner_user_id == subject.user_id) for r in rows],
        next_cursor=_encode(rows[-1].name, rows[-1].id) if more and rows else None,
    )
