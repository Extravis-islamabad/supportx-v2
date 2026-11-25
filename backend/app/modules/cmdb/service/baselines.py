"""CI baselines: a CI's attributes under a name, compared later (WP-053 S7b; REQ-CMDB-033).

- **Saving one** needs `cmdb.manage` on the CI (in scope; 404 if they may not see it, 403 if they
  may see but not manage it). The baseline takes its own copy of the CI as it is now, the same
  shape as a version's snapshot (fields, custom values, relationships), so it never depends on
  versions being kept. Kept until deleted (D-172 (6)).
- **Reading and comparing** need `cmdb.view` and the CI visible now. A baseline is compared with
  the CI now or with another baseline of the same CI, through the reader's CURRENT rights, as
  versions are (service/versions.py): a field their ADR-047 rules hide is absent from both sides;
  a masked one is never shown, only whether it changed; a related CI they may not see is a
  placeholder.
- **Deleting one** (soft) needs `cmdb.manage` on the CI and its If-Match version.
- Each save and delete writes history (`ci_baseline`) and raises `cmdb.baseline.changed` (IDs and
  the action only) through the outbox in the same transaction; the CI page follows it live.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.cmdb.domain import types as domain
from app.modules.cmdb.events import BaselineChanged
from app.modules.cmdb.infra.models import Ci, CiBaseline
from app.modules.cmdb.service import versions
from app.modules.cmdb.service.catalogue import invalid
from app.modules.cmdb.service.cis import manageable, snapshot, visible_rows
from app.modules.cmdb.service.snapshots import LINKS, links_of
from app.modules.identity_access import Subject, user_names
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.api.listing import ListQuery, PageResult, paginate
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

RECORD_TYPE = "ci_baseline"
NAME_MAX = 200

BASELINE_FIELDS = ResourceFields(
    name="ci_baselines",
    fields={
        "id": FilterField(CiBaseline.id, FieldType.UUID),
        "name": FilterField(CiBaseline.name, FieldType.STRING, sortable=True),
        "created_at": FilterField(CiBaseline.created_at, FieldType.DATETIME, sortable=True),
    },
    id_column=CiBaseline.id,
    default_sort=("-created_at",),
)


class BaselineRepository(Repository[CiBaseline]):
    """Baselines of the session's tenant."""

    model = CiBaseline


@dataclass(frozen=True)
class BaselineItem:
    """One baseline as a list shows it."""

    record: CiBaseline
    created_by_name: str | None


@dataclass(frozen=True)
class _Side:
    """One side of a compare: a baseline's copy, or the CI as it is now (`versions.Saved`)."""

    version: int
    saved_at: datetime
    saved_by: uuid.UUID | None
    snapshot: dict[str, Any]


def _copy(row: CiBaseline) -> _Side:
    return _Side(row.from_version, row.created_at, row.created_by, row.snapshot)


async def _visible_ci(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> Ci:
    row: Ci | None = await session.scalar(visible_rows(subject).where(Ci.id == ci_id))
    if row is None:
        raise NotFound(code="cmdb_ci_not_found")
    return row


def _of_ci(ci_id: uuid.UUID) -> Select[Any]:
    return select(CiBaseline).where(CiBaseline.ci_id == ci_id, CiBaseline.deleted_at.is_(None))


async def _baseline(session: AsyncSession, ci_id: uuid.UUID, baseline_id: uuid.UUID) -> CiBaseline:
    row: CiBaseline | None = await session.scalar(_of_ci(ci_id).where(CiBaseline.id == baseline_id))
    if row is None:
        raise NotFound(code="cmdb_ci_baseline_not_found")
    return row


def _name(values: Mapping[str, Any]) -> str:
    name = values.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > NAME_MAX:
        raise invalid([domain.Problem("name", "invalid_value")])
    return name.strip()


async def _items(session: AsyncSession, rows: list[CiBaseline]) -> list[BaselineItem]:
    names = await user_names(session, sorted({str(r.created_by) for r in rows if r.created_by}))
    return [BaselineItem(r, names.get(str(r.created_by)) if r.created_by else None) for r in rows]


async def list_baselines(
    session: AsyncSession, subject: Subject, ci_id: uuid.UUID, query: ListQuery
) -> tuple[list[BaselineItem], PageResult[CiBaseline]]:
    """One page of the CI's baselines (the CI must be one the reader may see now)."""
    await _visible_ci(session, subject, ci_id)
    page = await paginate(session, _of_ci(ci_id), query)
    return await _items(session, list(page.rows)), page


async def save(
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    values: Mapping[str, Any],
    source: Source,
) -> BaselineItem:
    """Save the CI as it is now under a name (`cmdb.manage` on the CI)."""
    ci = await manageable(session, subject, ci_id)
    name = _name(values)
    row = CiBaseline(
        ci_id=ci.id,
        name=name,
        from_version=ci.version,
        snapshot={**snapshot(ci), LINKS: await links_of(session, ci.id)},
    )
    await BaselineRepository(session).add(row)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="created",
        changes=[Change("name", None, name)],
        source=source,
    )
    await _event(session, row, "created")
    (item,) = await _items(session, [row])
    return item


async def remove(  # noqa: PLR0913 - the CI, the baseline, the version and the source
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    baseline_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Delete one (soft; `cmdb.manage` on the CI, If-Match)."""
    await manageable(session, subject, ci_id)
    row = await _baseline(session, ci_id, baseline_id)
    deleted = await BaselineRepository(session).soft_delete(
        row.id, expected_version=expected_version
    )
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await _event(session, deleted, "deleted")


async def compare(
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    baseline_id: uuid.UUID,
    *,
    against: uuid.UUID | None,
) -> versions.Comparison:
    """The baseline (before) against another baseline of the CI, or the CI now (after)."""
    ci = await _visible_ci(session, subject, ci_id)
    old = _copy(await _baseline(session, ci_id, baseline_id))
    new: versions.Saved
    if against is None:
        new = _Side(
            ci.version,
            ci.updated_at,
            ci.updated_by,
            {**snapshot(ci), LINKS: await links_of(session, ci.id)},
        )
    else:
        new = _copy(await _baseline(session, ci_id, against))
    return await versions.compare_saved(session, subject, old, new)


async def _event(session: AsyncSession, row: CiBaseline, action: str) -> None:
    await record_event(
        session,
        BaselineChanged(baseline_id=row.id, ci_id=row.ci_id, action=action),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
