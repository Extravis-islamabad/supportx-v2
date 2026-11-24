"""Configuration items linked to work items (WP-053 S5, lane A; REQ-CMDB-019; lane B's shapes).

A record lists the CIs it is about: the server an incident took down, the service a change
touches. Work items keep their own link table and never read CMDB tables (CLAUDE.md rule e):
`cmdb.can_link` before a person links one, `cmdb.ci_refs` to name them, so a CI that was removed
or that the reader may not see comes back marked, never named.

- Linking needs the record's edit right and the `cmdb` feature; at most `MAX_LINKS` per record.
- A record raised with `ci_ids` links them as it is made (`at_creation`), even when its template
  has no CI field (REQ-SR-019 AC1, the CI's "Raise" menu).
- Each link and unlink is a history line holding the CI's ID only, named when read through the
  CMDB's visibility (lane B's condition: a restricted CI's name never lands in a work item's
  history), and an outbox event with IDs only (`work_items.ci_link.changed`), from which the CMDB
  keeps the CI's Associations counters live.
- `repoint_ci_links` is the CMDB's merge port (`cmdb.register_ci_links`, lane B's links.py
  contract).
"""

import uuid
from collections.abc import Sequence
from typing import Literal, cast, get_args

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound
from app.modules import cmdb, licensing
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import WorkItemType, WorkItemTypeCode
from app.modules.work_items.events import WorkItemCiLinkChanged
from app.modules.work_items.infra.models import WorkItem, WorkItemCi
from app.modules.work_items.service import work_items as items
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

FEATURE = "cmdb"
MAX_LINKS = 50  # per record: an outage names its CIs, never a whole estate
RECORD_TYPE = "work_item"
FIELD = items.CI_FIELD  # the history line's field; its value is the CI's ID, named when read
# The types a CI's Associations count (cmdb.LINKED_TYPES): these link CIs (lane B, 019).
LINKED_TYPES = frozenset(
    {
        WorkItemTypeCode.INCIDENT,
        WorkItemTypeCode.SERVICE_REQUEST,
        WorkItemTypeCode.PROBLEM,
        WorkItemTypeCode.CHANGE,
        WorkItemTypeCode.RELEASE,
    }
)


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


class CiLinkRepository(Repository[WorkItemCi]):
    """CI links of the session's tenant."""

    model = WorkItemCi


def links_cis(wtype: WorkItemType) -> bool:
    """Whether records of this type link CIs."""
    return wtype.code in LINKED_TYPES


async def _live(session: AsyncSession, record_id: uuid.UUID) -> list[WorkItemCi]:
    rows = await session.scalars(
        select(WorkItemCi)
        .where(WorkItemCi.work_item_id == record_id, WorkItemCi.deleted_at.is_(None))
        .order_by(WorkItemCi.created_at, WorkItemCi.id)
    )
    return list(rows)


async def ci_ids_of(session: AsyncSession, record_id: uuid.UUID) -> list[uuid.UUID]:
    """A record's live CI links, oldest first (what an approver kind or a report reads)."""
    return [r.ci_id for r in await _live(session, record_id)]


async def linked(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[tuple[WorkItemCi, cmdb.CiRef]]:
    """The record's linked CIs, each as the reader may see it (gone and hidden marked)."""
    if not links_cis(wtype):
        raise NotFound(code="work_item_not_found")
    await items.visible_record(session, subject, wtype, record_id)
    rows = await _live(session, record_id)
    refs = await cmdb.ci_refs(session, subject, [r.ci_id for r in rows])
    return [(row, refs[row.ci_id]) for row in rows]


async def _event(
    session: AsyncSession,
    record: WorkItem,
    ci_id: uuid.UUID,
    change: Literal["added", "removed"],
    *,
    at_creation: bool = False,
) -> None:
    await record_event(
        session,
        WorkItemCiLinkChanged(
            work_item_id=record.id,
            type=record.type,
            ci_id=ci_id,
            change=change,
            at_creation=at_creation,
            version=record.version,
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )


async def _write(
    session: AsyncSession,
    record: WorkItem,
    ci_id: uuid.UUID,
    *,
    source: Source,
    at_creation: bool = False,
) -> WorkItemCi:
    row = await CiLinkRepository(session).add(
        WorkItemCi(work_item_id=record.id, ci_id=ci_id, source=source, at_creation=at_creation)
    )
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_added",
        changes=[Change(FIELD, None, str(ci_id))],
        source=source,
    )
    await _event(session, record, ci_id, "added", at_creation=at_creation)
    return row


async def link(  # noqa: PLR0913 - the record, the CIs and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    ci_ids: Sequence[uuid.UUID],
    *,
    source: Source,
) -> list[WorkItemCi]:
    """Link CIs the person may link; ones already linked are left as they are."""
    if not links_cis(wtype):
        raise NotFound(code="work_item_not_found")
    await licensing.require_feature(_tenant(session), FEATURE)
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    return await attach(session, subject, record, ci_ids, source=source)


async def link_new(
    session: AsyncSession,
    subject: Subject,
    record: WorkItem,
    ci_ids: Sequence[uuid.UUID],
    *,
    source: Source,
) -> list[WorkItemCi]:
    """Link CIs to a record just created (its create body's `ci_ids`; REQ-SR-019 AC1)."""
    if not ci_ids:
        return []
    await licensing.require_feature(_tenant(session), FEATURE)
    return await attach(session, subject, record, ci_ids, source=source, at_creation=True)


async def attach(  # noqa: PLR0913 - the record, the CIs and how they came, explicit
    session: AsyncSession,
    subject: Subject,
    record: WorkItem,
    ci_ids: Sequence[uuid.UUID],
    *,
    source: Source,
    at_creation: bool = False,
) -> list[WorkItemCi]:
    """Link CIs to a record already checked (its create, or `link`): `can_link` and the cap."""
    wanted = list(dict.fromkeys(ci_ids))
    if not wanted:
        return []
    have = {r.ci_id for r in await _live(session, record.id)}
    new = [c for c in wanted if c not in have]
    if len(have) + len(new) > MAX_LINKS:
        raise items.field_errors([("ci_ids", "too_many_cis")], ci_ids={"max": MAX_LINKS})
    for ci_id in new:
        if not await cmdb.can_link(session, subject, ci_id):
            raise items.field_errors([("ci_ids", "ci_not_linkable")])
    return [await _write(session, record, c, source=source, at_creation=at_creation) for c in new]


async def unlink(  # noqa: PLR0913 - the record, the link, its version and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    link_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Unlink one CI (If-Match on the link)."""
    if not links_cis(wtype):
        raise NotFound(code="work_item_not_found")
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    row = await session.scalar(
        select(WorkItemCi).where(
            WorkItemCi.id == link_id,
            WorkItemCi.work_item_id == record_id,
            WorkItemCi.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFound(code="work_item_ci_not_found")
    if row.version != expected_version:
        raise Conflict(code="version_conflict", params={"current_version": row.version})
    await CiLinkRepository(session).soft_delete(row.id, expected_version=expected_version)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_removed",
        changes=[Change(FIELD, str(row.ci_id), None)],
        source=source,
    )
    await _event(session, record, row.ci_id, "removed")


async def repoint_ci_links(
    session: AsyncSession,
    from_ci_id: uuid.UUID,
    to_ci_id: uuid.UUID,
    *,
    source: str = "system",
) -> int:
    """Move every live link of one CI to another (a CMDB merge; cmdb/service/links.py contract).

    A no-op when the two are the same; in the caller's transaction; a record already linking the
    target keeps one link (the moved one is unlinked). Each touched record gets a history line
    with the two CI IDs and the removed and added events. No permission checks of its own: the
    CMDB checks before calling, and audits the merge. The records touched.
    """
    if from_ci_id == to_ci_id:
        return 0
    said: Source = cast("Source", source) if source in get_args(Source) else "system"
    rows = list(
        await session.scalars(
            select(WorkItemCi).where(
                WorkItemCi.ci_id == from_ci_id, WorkItemCi.deleted_at.is_(None)
            )
        )
    )
    if not rows:
        return 0
    already = set(
        await session.scalars(
            select(WorkItemCi.work_item_id).where(
                WorkItemCi.ci_id == to_ci_id,
                WorkItemCi.work_item_id.in_([r.work_item_id for r in rows]),
                WorkItemCi.deleted_at.is_(None),
            )
        )
    )
    repository = CiLinkRepository(session)
    for row in rows:
        record = await session.get(WorkItem, row.work_item_id)
        if record is None:  # pragma: no cover - the foreign key keeps the record
            continue
        await repository.soft_delete(row.id, expected_version=row.version)
        if row.work_item_id not in already:
            await repository.add(
                WorkItemCi(
                    work_item_id=row.work_item_id,
                    ci_id=to_ci_id,
                    source=said,
                    at_creation=row.at_creation,
                )
            )
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=record.id,
            version=record.version,
            kind="child_changed",
            changes=[Change(FIELD, str(from_ci_id), str(to_ci_id))],
            source=said,
        )
        await _event(session, record, from_ci_id, "removed")
        if row.work_item_id not in already:
            await _event(session, record, to_ci_id, "added")
    return len(rows)


__all__ = [
    "FEATURE",
    "FIELD",
    "LINKED_TYPES",
    "MAX_LINKS",
    "attach",
    "ci_ids_of",
    "link",
    "link_new",
    "linked",
    "links_cis",
    "repoint_ci_links",
    "unlink",
]
