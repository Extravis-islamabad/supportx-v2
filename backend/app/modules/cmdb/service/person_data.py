"""The CMDB's slice of a person's erasure (ADR-052 §4; band 500, owned rows).

CIs the person owns move to the successor (D4); nothing the CMDB holds is the person's own to
delete. Batched and idempotent (a second run moves nothing), counts only. Each moved CI gets its
version, history line (`source` system), snapshot and ordinary `updated` event, so open screens
follow (rule c). Snapshots and history keep the old owner's ID only: the person's own row is
what the erasure anonymises (identity_access).

Business views (S2, 0180) the person owns move to the successor too, after the CIs, each with
its version, history line and `cmdb.business_view.changed` event. A view's `created_by` is an
audit column only (ADR-052 step 5).

Person-type custom values (0175 part 2) that point at the person move to the successor last, as
an ordinary save of the CI (version, history line per key, snapshot, `CiUpdated`), counted per
value moved. Snapshots keep the old ID, as they do for the owner.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.cmdb.domain.field_access import CUSTOM
from app.modules.cmdb.events import BusinessViewChanged, CiUpdated
from app.modules.cmdb.infra.models import BusinessView, Ci
from app.modules.cmdb.service.business_views import RECORD_TYPE as VIEW_RECORD_TYPE
from app.modules.cmdb.service.catalogue import VIEW
from app.modules.cmdb.service.cis import CIS, RECORD_TYPE, snapshot
from app.modules.cmdb.service.snapshots import save_version
from app.modules.identity_access import (
    ERASE_BATCH,
    ErasureBatch,
    Subject,
    register_holdings,
    register_outside_view,
    register_person_data,
    scope_filter,
)
from app.shared.events import record_event
from app.shared.history import Change, record_changes

MOVED = "cmdb_cis_moved"
VIEWS_MOVED = "cmdb_views_moved"
PERSON_FIELDS_MOVED = "cmdb_ci_person_fields_moved"


class CmdbData:
    """cmdb: owned CIs, owned business views, then person-type custom values, to the successor."""

    module: ClassVar[str] = "cmdb"
    order: ClassVar[int] = 575
    kinds: ClassVar[frozenset[str]] = frozenset({MOVED, VIEWS_MOVED, PERSON_FIELDS_MOVED})

    async def erase_person(  # noqa: PLR0913 - the port contract (ADR-052 §4)
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """One batch of owned CIs per call (removed ones too: they can be restored)."""
        del keep_files, cursor
        rows = list(
            await session.scalars(
                select(Ci)
                .where(Ci.owner_user_id == person_id)
                .order_by(Ci.id)
                .limit(ERASE_BATCH)
                .with_for_update()
            )
        )
        for row in rows:
            row.owner_user_id, row.version, row.updated_at = successor_id, row.version + 1, now
        await session.flush()
        for row in rows:
            await record_changes(
                session,
                record_type=RECORD_TYPE,
                record_id=row.id,
                version=row.version,
                kind="updated",
                changes=[Change("owner_user_id", str(person_id), str(successor_id))],
                source="system",
            )
            await save_version(session, row, snapshot(row), None)
            await record_event(
                session,
                CiUpdated(ci_id=row.id, type_id=row.type_id, changed_fields=["owner_user_id"]),
                aggregate_id=row.id,
                aggregate_version=row.version,
            )
        counts = {MOVED: len(rows), VIEWS_MOVED: 0, PERSON_FIELDS_MOVED: 0}
        if len(rows) >= ERASE_BATCH:
            return ErasureBatch(counts, cursor="owned")
        counts[VIEWS_MOVED] = await _move_views(session, person_id, successor_id, now)
        if counts[VIEWS_MOVED] >= ERASE_BATCH:
            return ErasureBatch(counts, cursor="views")
        moved, full = await _move_person_fields(session, person_id, successor_id, now)
        counts[PERSON_FIELDS_MOVED] = moved
        return ErasureBatch(counts, cursor="fields" if full else None)


async def _move_views(
    session: AsyncSession, person_id: uuid.UUID, successor_id: uuid.UUID, now: datetime
) -> int:
    """One batch of the person's views (removed ones too: they can be restored)."""
    rows = list(
        await session.scalars(
            select(BusinessView)
            .where(BusinessView.owner_id == person_id)
            .order_by(BusinessView.id)
            .limit(ERASE_BATCH)
            .with_for_update()
        )
    )
    for row in rows:
        row.owner_id, row.version, row.updated_at = successor_id, row.version + 1, now
    await session.flush()
    for row in rows:
        await record_changes(
            session,
            record_type=VIEW_RECORD_TYPE,
            record_id=row.id,
            version=row.version,
            kind="updated",
            changes=[Change("owner_id", str(person_id), str(successor_id))],
            source="system",
        )
        await record_event(
            session,
            BusinessViewChanged(
                view_id=row.id,
                base_ci_id=row.base_ci_id,
                action="updated",
                changed_fields=["owner_id"],
            ),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
    return len(rows)


async def _move_person_fields(
    session: AsyncSession, person_id: uuid.UUID, successor_id: uuid.UUID, now: datetime
) -> tuple[int, bool]:
    """One batch of CIs whose person-type custom values name the person (removed CIs too).

    Returns the values moved and whether the batch was full (more may be left).
    """
    keys = sorted(
        key
        for key, definition in (
            await metadata.definitions(session, metadata.CustomFieldEntity.CI)
        ).items()
        if definition.type == metadata.FieldType.PERSON
    )
    if not keys:
        return 0, False
    who, heir = str(person_id), str(successor_id)
    rows = list(
        await session.scalars(
            select(Ci)
            .where(or_(*(Ci.custom[key].astext == who for key in keys)))
            .order_by(Ci.id)
            .limit(ERASE_BATCH)
            .with_for_update()
        )
    )
    moved = 0
    changed: dict[uuid.UUID, list[str]] = {}
    for row in rows:
        custom = dict(row.custom or {})
        hits = [key for key in keys if custom.get(key) == who]
        for key in hits:
            custom[key] = heir
        row.custom = custom
        row.version, row.updated_at = row.version + 1, now
        changed[row.id] = hits
        moved += len(hits)
    await session.flush()
    for row in rows:
        fields = [f"{CUSTOM}{key}" for key in changed[row.id]]
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=row.id,
            version=row.version,
            kind="updated",
            changes=[Change(field, who, heir) for field in fields],
            source="system",
        )
        await save_version(session, row, snapshot(row), None)
        await record_event(
            session,
            CiUpdated(ci_id=row.id, type_id=row.type_id, changed_fields=fields),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
    return moved, len(rows) >= ERASE_BATCH


PORT = CmdbData()

OWNED = "cmdb_cis_owned"
OWNED_OUTSIDE = "cmdb_cis_owned_outside_view"


async def holdings(session: AsyncSession, person_id: uuid.UUID) -> Mapping[str, int]:
    """The CIs the person owns, removed ones too (the job moves them all): the true total."""
    found = await session.scalar(
        select(func.count()).select_from(Ci).where(Ci.owner_user_id == person_id)
    )
    return {OWNED: int(found or 0)}


async def outside_view(
    session: AsyncSession, person_id: uuid.UUID, subject: Subject
) -> Mapping[str, int]:
    """Of those CIs, how many the eraser may not see (ADR-053; counts only, never IDs)."""
    total = await session.scalar(
        select(func.count()).select_from(Ci).where(Ci.owner_user_id == person_id)
    )
    seen = await session.scalar(
        select(func.count())
        .select_from(Ci)
        .where(Ci.owner_user_id == person_id, scope_filter(subject, VIEW, CIS))
    )
    return {OWNED_OUTSIDE: int(total or 0) - int(seen or 0)}


def register() -> None:
    """Make the erasure job erase the CMDB's slice, and count its holdings (at module import)."""
    register_person_data(PORT)
    register_holdings("cmdb", holdings)
    register_outside_view("cmdb", outside_view)
