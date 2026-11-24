"""What other modules may know of CIs (WP-053 S1; the CMDB's public interface).

- `can_see(session, subject, ci_id)`: whether the person may see the CI at all;
- `can_link(session, subject, ci_id)`: before a person links a CI to a record. `can_see` plus
  the picker's rule: an end-of-life CI is refused while the tenant leaves those out of pickers,
  so a direct API call never links what the picker hides (lane A's #524 review);
- `ci_refs(session, subject, ids)`: names for a record's **stored** links in one call, keyed by
  ID (as assets' `asset_refs`). Never a search: a CI the person may not see comes back `hidden`,
  a removed one `gone`, never silently missing and never named;
- the picker (`GET /cmdb/cis/picker`, `cis.picker`) to choose one.
`cmdb.ci.updated` (with `changed_fields`) is the hint that a name or state changed.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.domain import types as domain
from app.modules.cmdb.infra.models import Ci, CiState, CiType
from app.modules.cmdb.service import aliases
from app.modules.cmdb.service.catalogue import get_settings
from app.modules.cmdb.service.cis import visible_rows
from app.modules.identity_access import Subject

REFS_MAX = 500


@dataclass(frozen=True, slots=True)
class CiRef:
    """A CI as another module shows it: never more than this (all None when gone or hidden).

    The type shows by `type_label_key` (a built-in type, `cmdb_ci_type.<code>`) or else by
    `type_names` (a tenant's own type, its name per language); the state by its category code
    (`cmdb_state_category.<code>`), so a linked-CI row labels without a second call.
    """

    id: uuid.UUID
    display_id: str | None
    name: str | None
    type_id: uuid.UUID | None
    state_id: uuid.UUID | None
    state_category: str | None = None
    type_label_key: str | None = None
    type_names: dict[str, str] = field(default_factory=dict)
    gone: bool = False
    hidden: bool = False


async def can_see(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> bool:
    """Whether the person may see this CI (its scope; a removed CI never)."""
    return await session.scalar(visible_rows(subject).where(Ci.id == ci_id)) is not None


async def visible_ci_ids(
    session: AsyncSession, subject: Subject, ids: Sequence[uuid.UUID]
) -> frozenset[uuid.UUID]:
    """The subset of `ids` the person may see now (role scope and ADR-053 rules, never removed).

    For other modules' placeholders and counts, so they never need the predicate themselves.
    """
    unique = list(dict.fromkeys(ids))
    if not unique:
        return frozenset()
    found = await session.scalars(
        visible_rows(subject).with_only_columns(Ci.id).where(Ci.id.in_(unique))
    )
    return frozenset(found.all())


async def can_link(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> bool:
    """Whether the person may link this CI to a record now (`can_see` and the picker's rule)."""
    row = await session.scalar(visible_rows(subject).where(Ci.id == ci_id))
    if row is None:
        return False
    if not (await get_settings(session)).exclude_eol_from_pickers:
        return True
    category = await session.scalar(select(CiState.category).where(CiState.id == row.state_id))
    return category == domain.CiStateCategory.ACTIVE.value


def _hidden(ci_id: uuid.UUID) -> CiRef:
    return CiRef(ci_id, None, None, None, None, hidden=True)


def _gone(ci_id: uuid.UUID) -> CiRef:
    return CiRef(ci_id, None, None, None, None, gone=True)


async def ci_refs(
    session: AsyncSession, subject: Subject, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, CiRef]:
    """One ref per stored ID, in the order asked (at most REFS_MAX): hidden or gone, never named.

    A merged CI's ID gives its survivor's ref when the reader may see the survivor (S4b), and
    otherwise reads as gone, exactly as a CI that exists nowhere (lane C (8)).
    """
    unique = list(dict.fromkeys(ids))[:REFS_MAX]
    if not unique:
        return {}
    survivors = await aliases.resolve_visible(session, subject, unique)
    wanted = list(dict.fromkeys([*unique, *survivors.values()]))
    rows = await session.scalars(visible_rows(subject).where(Ci.id.in_(wanted)))
    visible = {r.id: r for r in rows}
    live = set(
        await session.scalars(select(Ci.id).where(Ci.id.in_(wanted), Ci.deleted_at.is_(None)))
    )
    states = {
        s.id: s.category
        for s in await session.scalars(
            select(CiState).where(CiState.id.in_({r.state_id for r in visible.values()}))
        )
    }
    types = {
        t.id: t
        for t in await session.scalars(
            select(CiType).where(CiType.id.in_({r.type_id for r in visible.values()}))
        )
    }
    out: dict[uuid.UUID, CiRef] = {}
    for ci_id in unique:
        row = visible.get(survivors.get(ci_id, ci_id))
        if row is None:
            out[ci_id] = _hidden(ci_id) if ci_id in live else _gone(ci_id)
            continue
        kind = types.get(row.type_id)
        out[ci_id] = CiRef(
            row.id,
            row.display_id,
            row.name,
            row.type_id,
            row.state_id,
            state_category=states.get(row.state_id),
            type_label_key=f"cmdb_ci_type.{kind.api_name}" if kind and kind.built_in else None,
            type_names=dict(kind.names) if kind and not kind.built_in else {},
        )
    return out
