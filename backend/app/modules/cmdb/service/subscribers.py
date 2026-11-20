"""A business service's subscribers: the departments, sites and groups it serves (0185, D-172 (3)).

- Only a business service CI (the `business_service` type or one below it) has subscribers.
- Read with the CI (`cmdb.view`, 404 for a CI the reader may not see); each ref named for the
  reader as the record names its references (ref_names: restricted without the unit's view
  right), and marked `removed` when the unit no longer exists, never its ID as text.
- Set as a whole list with the CI's If-Match (the CI's edit right): a new CI version, a history
  line, a snapshot and `cmdb.ci.updated` naming `subscribers`, through the CI's own save.
- At most `SUBSCRIBERS_MAX` refs; every ref must be a live unit when it is added.
- Who they reach is organization's audience: each active person once (`audience_of`).
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.domain import relationships as rel
from app.modules.cmdb.domain.types import Problem
from app.modules.cmdb.infra.models import Ci, CiType, ServiceSubscriber
from app.modules.cmdb.service import cis, ref_names
from app.modules.cmdb.service.catalogue import EDIT, ensure_defaults, invalid
from app.modules.identity_access import Subject
from app.modules.organization import (
    Audience,
    AudienceKind,
    existing_departments,
    existing_unit_ids,
)
from app.shared.history import Change, Source
from app.shared.ids import new_id

SUBSCRIBERS_MAX = 100
BUSINESS_SERVICE = "business_service"  # the built-in CI type (domain/types.py BUILT_IN_TYPES)
NOT_A_SERVICE = "cmdb_not_business_service"  # a field code: only business services subscribe


@dataclass(frozen=True)
class Subscriber:
    """One ref as the reader may know it."""

    kind: AudienceKind
    ref_id: uuid.UUID
    name: ref_names.RefName
    removed: bool


async def service_type_ids(session: AsyncSession) -> frozenset[uuid.UUID]:
    """The business service type and every type below it."""
    await ensure_defaults(session)
    rows = (
        await session.execute(
            select(CiType.id, CiType.parent_id, CiType.api_name, CiType.built_in).where(
                CiType.deleted_at.is_(None)
            )
        )
    ).all()
    parents = {str(i): (str(p) if p else None) for i, p, _, _ in rows}
    roots = {str(i) for i, _, name, built_in in rows if built_in and name == BUSINESS_SERVICE}
    return frozenset(uuid.UUID(t) for t in parents if roots & set(rel.lineage(t, parents)))


async def _rows(session: AsyncSession, ci_id: uuid.UUID) -> list[ServiceSubscriber]:
    return list(
        await session.scalars(
            select(ServiceSubscriber)
            .where(ServiceSubscriber.ci_id == ci_id, ServiceSubscriber.deleted_at.is_(None))
            .order_by(ServiceSubscriber.kind, ServiceSubscriber.ref_id)
        )
    )


async def _live(
    session: AsyncSession, refs: Iterable[tuple[AudienceKind, uuid.UUID]]
) -> frozenset[tuple[AudienceKind, uuid.UUID]]:
    """Which refs name a unit that exists now."""
    by: dict[AudienceKind, list[uuid.UUID]] = {kind: [] for kind in AudienceKind}
    for kind, ref_id in refs:
        by[kind].append(ref_id)
    live = {
        AudienceKind.DEPARTMENT: await existing_departments(session, by[AudienceKind.DEPARTMENT]),
        AudienceKind.SITE: await existing_unit_ids(session, "site", by[AudienceKind.SITE]),
        AudienceKind.GROUP: await existing_unit_ids(session, "group", by[AudienceKind.GROUP]),
    }
    return frozenset((kind, i) for kind, ids in by.items() for i in ids if i in live[kind])


async def _named(
    session: AsyncSession, subject: Subject, rows: Sequence[ServiceSubscriber]
) -> list[Subscriber]:
    refs = ref_names.Refs()
    for row in rows:
        target = {
            AudienceKind.DEPARTMENT: refs.departments,
            AudienceKind.SITE: refs.sites,
            AudienceKind.GROUP: refs.groups,
        }[AudienceKind(row.kind)]
        target.add(str(row.ref_id))
    names = await ref_names.resolve(session, subject, refs)
    live = await _live(session, ((AudienceKind(r.kind), r.ref_id) for r in rows))
    return [
        Subscriber(
            kind=AudienceKind(row.kind),
            ref_id=row.ref_id,
            name=names.get(str(row.ref_id), ref_names.RefName(restricted=True)),
            removed=(AudienceKind(row.kind), row.ref_id) not in live,
        )
        for row in rows
    ]


async def subscribers(
    session: AsyncSession, subject: Subject, ci_id: uuid.UUID
) -> list[Subscriber]:
    """A CI's subscribers as the reader may know them (404 for a CI they may not see)."""
    await cis.get_ci(session, subject, ci_id)  # the CI's own read check
    return await _named(session, subject, await _rows(session, ci_id))


def _wanted(refs: Sequence[tuple[AudienceKind, uuid.UUID]]) -> list[tuple[AudienceKind, uuid.UUID]]:
    unique = list(dict.fromkeys(refs))
    if len(unique) > SUBSCRIBERS_MAX:
        raise invalid([Problem("subscribers", "too_many")])
    return unique


async def set_subscribers(  # noqa: PLR0913 - the CI, its version, the list and the source
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    refs: Sequence[tuple[AudienceKind, uuid.UUID]],
    *,
    expected_version: int,
    source: Source,
) -> list[Subscriber]:
    """Replace a business service's subscribers (If-Match on the CI; the CI's edit right)."""
    if cis.writer(subject, EDIT) is None:
        raise cis._denied(EDIT)  # noqa: SLF001 - the CI service's own refusal, one module
    record: Ci = await cis._writable(session, subject, EDIT, ci_id)  # noqa: SLF001
    if record.type_id not in await service_type_ids(session):
        raise invalid([Problem("subscribers", NOT_A_SERVICE)])
    wanted = _wanted(refs)
    current = await _rows(session, ci_id)
    have = {(AudienceKind(r.kind), r.ref_id): r for r in current}
    added = [ref for ref in wanted if ref not in have]
    live = await _live(session, added)
    missing = [ref for ref in added if ref not in live]
    if missing:
        raise invalid([Problem("subscribers", "not_found")])
    gone = [row for key, row in have.items() if key not in set(wanted)]
    if not added and not gone:
        await cis._save(  # noqa: SLF001 - checks the version, changes nothing
            session, subject, record, expected_version=expected_version, columns={}, source=source
        )
        return await _named(session, subject, current)
    # The CI's own save: its version moves, its history names the change, its event goes out.
    await cis._save(  # noqa: SLF001 - the CI's one save path
        session,
        subject,
        record,
        expected_version=expected_version,
        # An unchanged field: the CI's version moves (and its updater), its history shows only
        # the line below (managed columns are the repository's own).
        columns={"name": record.name},
        source=source,
        # How many, never the refs: a history line shows no ID (rule d); who is in the list
        # reads from the list itself, named for each reader.
        extra=[Change("subscribers", len(have), len(wanted))],
    )
    if gone:
        await session.execute(
            update(ServiceSubscriber)
            .where(ServiceSubscriber.id.in_([row.id for row in gone]))
            .values(deleted_at=cis._now(), updated_by=subject.user_id)  # noqa: SLF001
        )
    for kind, ref_id in added:
        session.add(
            ServiceSubscriber(
                id=new_id(),
                tenant_id=record.tenant_id,
                ci_id=ci_id,
                kind=kind.value,
                ref_id=ref_id,
                created_by=subject.user_id,
                updated_by=subject.user_id,
            )
        )
    await session.flush()
    return await _named(session, subject, await _rows(session, ci_id))


async def audience_of(session: AsyncSession, ci_ids: Iterable[uuid.UUID]) -> Audience:
    """The live refs of these business services, as one audience (impact's affected users)."""
    ids = list(dict.fromkeys(ci_ids))
    if not ids:
        return Audience()
    rows = await session.execute(
        select(ServiceSubscriber.kind, ServiceSubscriber.ref_id).where(
            ServiceSubscriber.ci_id.in_(ids), ServiceSubscriber.deleted_at.is_(None)
        )
    )
    refs = [(AudienceKind(kind), ref_id) for kind, ref_id in rows]
    # A removed unit counts nobody, even where people still name it (a deleted department).
    return Audience.of(await _live(session, refs))
