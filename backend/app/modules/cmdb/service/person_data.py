"""The CMDB's slice of a person's erasure (ADR-052 §4; band 500, owned rows).

CIs the person owns move to the successor (D4); nothing the CMDB holds is the person's own to
delete. Batched and idempotent (a second run moves nothing), counts only. Each moved CI gets its
version, history line (`source` system), snapshot and ordinary `updated` event, so open screens
follow (rule c). Snapshots and history keep the old owner's ID only: the person's own row is
what the erasure anonymises (identity_access).

Business views (S2, 0180) the person owns move to the successor too, after the CIs, each with
its version, history line and `cmdb.business_view.changed` event. A view's `created_by` is an
audit column only (ADR-052 step 5).
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.events import BusinessViewChanged, CiUpdated
from app.modules.cmdb.infra.models import BusinessView, Ci
from app.modules.cmdb.service.business_views import RECORD_TYPE as VIEW_RECORD_TYPE
from app.modules.cmdb.service.cis import RECORD_TYPE, snapshot
from app.modules.cmdb.service.snapshots import save_version
from app.modules.identity_access import ERASE_BATCH, ErasureBatch, register_person_data
from app.shared.events import record_event
from app.shared.history import Change, record_changes

MOVED = "cmdb_cis_moved"
VIEWS_MOVED = "cmdb_views_moved"


class CmdbData:
    """cmdb: owned CIs, then owned business views, moved to the successor (band 500)."""

    module: ClassVar[str] = "cmdb"
    order: ClassVar[int] = 575
    kinds: ClassVar[frozenset[str]] = frozenset({MOVED, VIEWS_MOVED})

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
        if len(rows) >= ERASE_BATCH:
            return ErasureBatch({MOVED: len(rows), VIEWS_MOVED: 0}, cursor="owned")
        views = await _move_views(session, person_id, successor_id, now)
        return ErasureBatch(
            {MOVED: len(rows), VIEWS_MOVED: views},
            cursor="views" if views >= ERASE_BATCH else None,
        )


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


PORT = CmdbData()


def register() -> None:
    """Make the erasure job erase the CMDB's slice (at module import)."""
    register_person_data(PORT)
