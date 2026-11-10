"""Who holds an asset, and its holding history (WP-049a s4; REQ-AST-018, 019, 020 for assets).

- **One holder at a time:** a person, a department or the asset it is fitted to (a monitor on a
  workstation). Giving it to another ends the current holding and starts a new one; the
  holdings are never rewritten (AC1 of 019), and a disputed acknowledgement leaves them as they
  are. An asset is never fitted to itself or inside its own children (018 AC3).
- **Its site can follow its person** (tenant setting `site_follows_owner`, 018 AC2): assigning
  takes the person's site, and when a person's site changes (identity_access's `user.updated`
  with `site_id`), every asset they hold moves with them, with history on each. The consumer is
  idempotent by event ID (the claim in processed_events); the person's site comes through
  identity_access's public `person_placement`, never its tables.
- People and departments are checked through their modules (`active_user_ids`,
  `existing_departments`).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.modules.assets.domain.catalogue import Problem
from app.modules.assets.domain.ownership import HOLDER_KINDS, would_nest_in_itself
from app.modules.assets.events import AssetHolderChanged
from app.modules.assets.infra.models import Asset, AssetAssignment, AssetSettings
from app.modules.assets.service.acknowledgements import ask_if_needed
from app.modules.assets.service.assets import (
    MANAGE,
    RECORD_TYPE,
    _refuse,
    _require,
    _saved,
    _tenant,
    _visible,
)
from app.modules.identity_access import Subject, active_user_ids, person_placement
from app.modules.organization import existing_departments
from app.shared.clock import system_clock
from app.shared.events import ConsumerSpec, EventEnvelope, record_event
from app.shared.history import Change, Source
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id

_HOLDER_FIELD = {"user": "owner_user_id", "department": "department_id", "asset": "parent_asset_id"}


@dataclass(frozen=True, slots=True)
class Holder:
    """Who holds an asset: a person, a department or another asset."""

    kind: str
    id: uuid.UUID


def holder_of(row: Asset) -> Holder | None:
    """The asset's current holder, from its own columns."""
    for kind, field in _HOLDER_FIELD.items():
        value = getattr(row, field)
        if value is not None:
            return Holder(kind, value)
    return None


async def _holder_problems(
    session: AsyncSession, subject: Subject, row: Asset, holder: Holder
) -> list[Problem]:
    if holder.kind not in HOLDER_KINDS:
        return [Problem("holder_kind", "invalid_choice")]
    if holder.kind == "user":
        found = await active_user_ids(session, [holder.id])
        return [] if holder.id in found else [Problem("holder_id", "asset_holder_not_found")]
    if holder.kind == "department":
        found = await existing_departments(session, [holder.id])
        return [] if holder.id in found else [Problem("holder_id", "asset_holder_not_found")]
    # Fitted to another asset: one the person may see, never itself or one of its children.
    try:
        await _visible(session, subject, holder.id)
    except (NotFound, PermissionDenied):  # the same answer either way: no such asset
        return [Problem("holder_id", "asset_holder_not_found")]
    parents = dict((await session.execute(select(Asset.id, Asset.parent_asset_id))).tuples().all())
    links = {str(k): (None if v is None else str(v)) for k, v in parents.items()}
    if would_nest_in_itself(str(row.id), str(holder.id), links):
        return [Problem("holder_id", "asset_nested_in_itself")]
    return []


async def _end_current(session: AsyncSession, asset_id: uuid.UUID) -> AssetAssignment | None:
    current = await session.scalar(
        select(AssetAssignment).where(
            AssetAssignment.asset_id == asset_id,
            AssetAssignment.ended_at.is_(None),
            AssetAssignment.deleted_at.is_(None),
        )
    )
    if current is not None:
        current.ended_at = system_clock.now()
        await session.flush()
    return current


async def _follows_site(session: AsyncSession) -> bool:
    settings = await session.get(AssetSettings, _tenant(session))
    return settings is not None and settings.site_follows_owner


async def _apply_holder(session: AsyncSession, row: Asset, holder: Holder | None) -> list[Change]:
    """Set the holder columns (and the person's site, when assets follow it); the changes."""
    changes: list[Change] = []
    for kind, field in _HOLDER_FIELD.items():
        new = holder.id if holder is not None and holder.kind == kind else None
        old = getattr(row, field)
        if old != new:
            changes.append(
                Change(field, None if old is None else str(old), None if new is None else str(new))
            )
            setattr(row, field, new)
    if holder is not None and holder.kind == "user" and await _follows_site(session):
        site = (await person_placement(session, holder.id)).site_id
        if site is not None and site != row.site_id:
            changes.append(
                Change("site_id", None if row.site_id is None else str(row.site_id), str(site))
            )
            row.site_id = site
    return changes


async def set_holder(  # noqa: PLR0913 - the asset, the holder, the If-Match and the source
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    holder: Holder | None,
    *,
    expected_version: int,
    source: Source,
) -> Asset:
    """Give the asset to `holder` (None: back to no one), with history and one holding row."""
    _require(subject, MANAGE)
    row = await _visible(session, subject, asset_id, permission=MANAGE)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    if holder is not None:
        _refuse(await _holder_problems(session, subject, row, holder))
    previous = holder_of(row)
    if previous == holder:
        return row  # already held so: nothing to record
    changes = await _apply_holder(session, row, holder)
    await _end_current(session, row.id)
    holding: AssetAssignment | None = None
    if holder is not None:
        holding = AssetAssignment(
            id=new_id(),
            tenant_id=row.tenant_id,
            created_by=subject.user_id,
            asset_id=row.id,
            holder_kind=holder.kind,
            holder_id=holder.id,
            started_at=system_clock.now(),
            source=source,  # where the change came from, as its history says
        )
        session.add(holding)
    await _saved(session, subject, row, changes, action="updated", source=source)
    if holding is not None:
        await session.flush()
        await ask_if_needed(session, row, holding, subject.user_id)
    # "My assets" of the people before and after refresh live (REQ-AST-024 AC3): IDs only.
    people = sorted({h.id for h in (previous, holder) if h is not None and h.kind == "user"})
    if people:
        await record_event(
            session,
            AssetHolderChanged(asset_id=row.id, people=people),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
    return row


async def holdings(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID
) -> list[AssetAssignment]:
    """Every holding of the asset, newest first (REQ-AST-019 AC1)."""
    await _visible(session, subject, asset_id)
    rows = await session.scalars(
        select(AssetAssignment)
        .where(AssetAssignment.asset_id == asset_id, AssetAssignment.deleted_at.is_(None))
        .order_by(AssetAssignment.started_at.desc(), AssetAssignment.id.desc())
    )
    return list(rows)


async def held_by(
    session: AsyncSession, subject: Subject, holder: Holder
) -> list[tuple[Asset, AssetAssignment]]:
    """Every asset the person or department holds or held, newest first (019 AC2, 020).

    Only the assets the person asking may see (the list's own scope rule).
    """
    rows = (
        (
            await session.execute(
                select(AssetAssignment)
                .where(
                    AssetAssignment.holder_kind == holder.kind,
                    AssetAssignment.holder_id == holder.id,
                    AssetAssignment.deleted_at.is_(None),
                )
                .order_by(AssetAssignment.started_at.desc(), AssetAssignment.id.desc())
            )
        )
        .scalars()
        .all()
    )
    found: list[tuple[Asset, AssetAssignment]] = []
    for holding in rows:
        try:
            found.append((await _visible(session, subject, holding.asset_id), holding))
        except (NotFound, PermissionDenied):  # hidden or removed: left out, never named
            continue
    return found


async def move_with_owner(session: AsyncSession, user_id: uuid.UUID) -> int:
    """The person's site changed: their assets follow, with history; how many moved (018 AC2)."""
    if not await _follows_site(session):
        return 0
    site = (await person_placement(session, user_id)).site_id
    if site is None:
        return 0
    rows = list(
        await session.scalars(
            select(Asset).where(
                Asset.owner_user_id == user_id,
                Asset.deleted_at.is_(None),
                Asset.site_id.is_distinct_from(site),
            )
        )
    )
    for row in rows:
        old = row.site_id
        row.site_id = site
        await _saved(
            session, None, row,
            [Change("site_id", None if old is None else str(old), str(site))],
            action="updated", source="system",
        )  # fmt: skip
    return len(rows)


async def _on_user_updated(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    assert session is not None  # noqa: S101 - transactional consumer
    if "site_id" not in (envelope.payload.get("changed_fields") or []):
        return
    await move_with_owner(session, uuid.UUID(str(envelope.payload["user_id"])))


OWNER_SITE_CHANGED = ConsumerSpec(
    name="assets__owner_site_changed",
    event_types=("identity_access.user.updated",),
    handler=_on_user_updated,
)
