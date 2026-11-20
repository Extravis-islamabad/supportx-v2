"""A CI's versions: the list, "as of" a time, and compare (WP-053 S2; REQ-CMDB-024's view side).

Read from the snapshots only (service/snapshots.py), through the reader's CURRENT rights (lane
C's condition 3):

- the CI itself must be one they may see now (404 otherwise, never 403);
- attributes are the CI's saved fields (`cis.SNAPSHOT`) and its custom values as `custom.<key>`
  (0175 part 2), through the reader's ADR-047 rules as on the record: hidden and masked values
  are left out (masked ones named in `masked_fields`), and only fields that still exist show. CI
  custom fields are never sensitive (lane A's condition a), so no sealed form exists here;
- a related CI the reader may not see now is a placeholder with a per-response key (`r1`, …),
  and the link's ID is left out.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules import metadata
from app.modules.cmdb.domain import field_access as field_rules
from app.modules.cmdb.domain import relationships as rel
from app.modules.cmdb.infra.models import Ci, CiVersion
from app.modules.cmdb.service import ref_names
from app.modules.cmdb.service.cis import RECORD_TYPE, SNAPSHOT, visible_rows
from app.modules.cmdb.service.relationships import NodeInfo, node_infos
from app.modules.cmdb.service.snapshots import LINKS
from app.modules.identity_access import Subject, user_names


@dataclass(frozen=True)
class VersionItem:
    """One saved version: its number, when and by whom."""

    version: int
    saved_at: datetime
    saved_by: uuid.UUID | None
    saved_by_name: str | None


@dataclass(frozen=True)
class LinkView:
    """A relationship as a version holds it, from this CI's side."""

    id: uuid.UUID | None  # left out when the other CI is a placeholder
    type_id: uuid.UUID
    direction: rel.RelationshipDirection
    key: str  # the other CI's ID, or `r<n>`
    other: NodeInfo


@dataclass(frozen=True)
class VersionView:
    """A CI as one version saved it."""

    version: int
    saved_at: datetime
    saved_by: uuid.UUID | None
    saved_by_name: str | None
    fields: dict[str, Any]
    relationships: list[LinkView]
    masked_fields: list[str] = field(default_factory=list)  # `custom.<key>` held but masked
    # References named for the reader (CMDB polish): one map for the whole response, so both
    # sides of a compare carry the same names.
    names: dict[str, ref_names.RefName] = field(default_factory=dict)


@dataclass(frozen=True)
class Comparison:
    """What changed from one version to another."""

    from_version: VersionView
    to_version: VersionView
    attributes: list[rel.AttributeChange]
    added: list[LinkView]
    removed: list[LinkView]


async def _visible(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> None:
    if await session.scalar(visible_rows(subject).where(Ci.id == ci_id)) is None:
        raise NotFound(code="cmdb_ci_not_found")


async def list_versions(
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    before_version: int | None,
    limit: int,
) -> tuple[list[VersionItem], int | None]:
    """Versions newest first, a page at a time (`before_version` is the cursor)."""
    await _visible(session, subject, ci_id)
    query = select(CiVersion.version, CiVersion.saved_at, CiVersion.saved_by).where(
        CiVersion.ci_id == ci_id
    )
    if before_version is not None:
        query = query.where(CiVersion.version < before_version)
    rows = (await session.execute(query.order_by(CiVersion.version.desc()).limit(limit + 1))).all()
    page = rows[:limit]
    names = await user_names(session, sorted({str(r[2]) for r in page if r[2]}))
    items = [VersionItem(v, at, by, names.get(str(by)) if by else None) for v, at, by in page]
    return items, (page[-1][0] if len(rows) > limit and page else None)


@dataclass(frozen=True)
class _Reader:
    """What one reader gets of custom values: the live fields, less what their rules withhold."""

    live: frozenset[str]
    unseen: field_rules.Unseen

    def custom(self, snapshot: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
        held = snapshot.get("custom")
        if not isinstance(held, Mapping):
            return {}, []
        withheld = self.unseen.custom_keys()
        shown = {
            f"{field_rules.CUSTOM}{k}": v
            for k, v in held.items()
            if k in self.live and k not in withheld
        }
        masked = sorted(
            f"{field_rules.CUSTOM}{k}"
            for k in held
            if k in self.live and f"{field_rules.CUSTOM}{k}" in self.unseen.masked
        )
        return shown, masked


async def _reader(session: AsyncSession, subject: Subject) -> _Reader:
    live = frozenset(
        f.key
        for f in await metadata.field_marks(session, metadata.CustomFieldEntity.CI, retired=True)
    )
    return _Reader(live, field_rules.unseen(subject.field_access, RECORD_TYPE))


def _fields(snapshot: Mapping[str, Any], reader: _Reader) -> tuple[dict[str, Any], list[str]]:
    base = {name: snapshot.get(name) for name in SNAPSHOT}
    custom, masked = reader.custom(snapshot)
    return {**base, **dict(sorted(custom.items()))}, masked


def _links(snapshot: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    links = snapshot.get(LINKS)
    return [link for link in links if isinstance(link, Mapping)] if isinstance(links, list) else []


def _ci_id(link: Mapping[str, Any]) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(link.get("ci_id")))
    except ValueError:
        return None


class _Placeholders:
    """One response's placeholder keys: the same hidden CI gets the same key throughout."""

    def __init__(self) -> None:
        self._keys: dict[uuid.UUID, str] = {}

    def key(self, info: NodeInfo) -> str:
        if info.visible:
            return str(info.id)
        return self._keys.setdefault(info.id, f"r{len(self._keys) + 1}")


def _link_views(
    links: Sequence[Mapping[str, Any]],
    infos: Mapping[uuid.UUID, NodeInfo],
    keys: _Placeholders,
) -> list[LinkView]:
    out: list[LinkView] = []
    for link in links:
        other = _ci_id(link)
        if other is None:
            continue
        info = infos.get(other, NodeInfo(id=other, visible=False))
        try:
            rid = uuid.UUID(str(link.get("relationship_id"))) if info.visible else None
            type_id = uuid.UUID(str(link.get("type_id")))
            direction = rel.RelationshipDirection(str(link.get("direction")))
        except ValueError:
            continue
        out.append(LinkView(rid, type_id, direction, keys.key(info), info))
    return out


async def _version(session: AsyncSession, ci_id: uuid.UUID, version: int) -> CiVersion:
    row = await session.scalar(
        select(CiVersion)
        .where(CiVersion.ci_id == ci_id, CiVersion.version == version)
        .order_by(CiVersion.saved_at.desc())
        .limit(1)
    )
    if row is None:
        raise NotFound(code="cmdb_ci_version_not_found")
    return row


async def _views(
    session: AsyncSession, subject: Subject, rows: Sequence[CiVersion], keys: _Placeholders
) -> list[VersionView]:
    others = [i for row in rows for link in _links(row.snapshot) if (i := _ci_id(link))]
    infos = await node_infos(session, subject, others)
    names = await user_names(session, sorted({str(r.saved_by) for r in rows if r.saved_by}))
    reader = await _reader(session, subject)
    shown = [_fields(row.snapshot, reader) for row in rows]
    # Only what the reader may read now is named (hidden and masked values are left out above).
    referred = await ref_names.names_for(session, subject, [fields for fields, _ in shown])
    views: list[VersionView] = []
    for row, (fields, masked) in zip(rows, shown, strict=True):
        views.append(
            VersionView(
                version=row.version,
                saved_at=row.saved_at,
                saved_by=row.saved_by,
                saved_by_name=names.get(str(row.saved_by)) if row.saved_by else None,
                fields=fields,
                relationships=_link_views(_links(row.snapshot), infos, keys),
                masked_fields=masked,
                names=referred,
            )
        )
    return views


async def as_of(
    session: AsyncSession, subject: Subject, ci_id: uuid.UUID, at: datetime
) -> VersionView:
    """The CI as its last version saved at or before `at` (404 when it did not exist then)."""
    await _visible(session, subject, ci_id)
    row = await session.scalar(
        select(CiVersion)
        .where(CiVersion.ci_id == ci_id, CiVersion.saved_at <= at)
        .order_by(CiVersion.saved_at.desc(), CiVersion.version.desc())
        .limit(1)
    )
    if row is None:
        raise NotFound(code="cmdb_ci_version_not_found")
    (view,) = await _views(session, subject, [row], _Placeholders())
    return view


def _compared(before: VersionView, after: VersionView) -> list[str]:
    """The built-in fields in their order, then every custom key either version shows."""
    custom = sorted(
        {k for k in (*before.fields, *after.fields) if k.startswith(field_rules.CUSTOM)}
    )
    return [*SNAPSHOT, *custom]


async def compare(
    session: AsyncSession, subject: Subject, ci_id: uuid.UUID, *, from_version: int, to_version: int
) -> Comparison:
    """Attributes added, removed and changed, and relationships added and removed."""
    await _visible(session, subject, ci_id)
    old = await _version(session, ci_id, from_version)
    new = await _version(session, ci_id, to_version)
    keys = _Placeholders()
    before, after = await _views(session, subject, [old, new], keys)
    added_raw, removed_raw = rel.compare_links(_links(old.snapshot), _links(new.snapshot))
    infos = await node_infos(
        session, subject, [i for link in (*added_raw, *removed_raw) if (i := _ci_id(link))]
    )
    return Comparison(
        from_version=before,
        to_version=after,
        attributes=rel.compare_attributes(before.fields, after.fields, _compared(before, after)),
        added=_link_views(added_raw, infos, keys),
        removed=_link_views(removed_raw, infos, keys),
    )
