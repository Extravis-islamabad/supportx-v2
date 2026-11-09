"""Sites and support groups and their members (WP-016, basic level).

Both have the same shape (a named unit with members), so one implementation serves both.
Every change writes its event in the same transaction (CLAUDE.md rule b); renames use optimistic
concurrency (rule g). Permission checks happen in the routes (require_permission); this layer
owns validation and the transaction.
"""

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import access_changed
from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.organization.events import (
    MembershipChanged,
    SiteChanged,
    SupportGroupChanged,
    UnitKind,
)
from app.modules.organization.infra.models import GroupMember, Site, SiteMember, SupportGroup
from app.shared.db.repository import Repository
from app.shared.events import record_event

Kind = Literal["site", "group"]


class SiteRepository(Repository[Site]):
    """Sites of the session's tenant."""

    model = Site


class GroupRepository(Repository[SupportGroup]):
    """Support groups of the session's tenant."""

    model = SupportGroup


@dataclass(frozen=True)
class _Unit:
    # Any: Site/SupportGroup (and their member tables) share columns but no common typed base
    # mypy could see through the union; the two concrete pairs are fixed in UNITS below.
    model: Any
    repository: type[SiteRepository] | type[GroupRepository]
    member: Any
    member_unit_column: str


UNITS: dict[Kind, _Unit] = {
    "site": _Unit(Site, SiteRepository, SiteMember, "site_id"),
    "group": _Unit(SupportGroup, GroupRepository, GroupMember, "group_id"),
}


@dataclass(frozen=True)
class UnitView:
    """A site or group with its member IDs."""

    id: uuid.UUID
    name: str
    version: int
    member_ids: list[uuid.UUID]


@dataclass(frozen=True)
class Memberships:
    """Which sites and groups a user belongs to (the basis of `site` / `group` scopes)."""

    site_ids: frozenset[uuid.UUID]
    group_ids: frozenset[uuid.UUID]


def _name(value: str) -> str:
    name = value.strip()
    if not 1 <= len(name) <= 200:  # noqa: PLR2004 - same bound as the CHECK constraint
        raise ValidationFailed(params={"field": "name"})
    return name


def _changed_event(
    kind: Kind, unit_id: uuid.UUID, fields: list[str]
) -> SiteChanged | SupportGroupChanged:
    if kind == "site":
        return SiteChanged(site_id=unit_id, changed_fields=fields)
    return SupportGroupChanged(group_id=unit_id, changed_fields=fields)


async def list_units(session: AsyncSession, kind: Kind) -> list[UnitView]:
    """All sites (or groups) of the tenant with their members, by name."""
    unit = UNITS[kind]
    rows = (
        await session.scalars(
            select(unit.model).where(unit.model.deleted_at.is_(None)).order_by(unit.model.name)
        )
    ).all()
    column = getattr(unit.member, unit.member_unit_column)
    members: dict[uuid.UUID, list[uuid.UUID]] = {}
    for unit_id, user_id in (await session.execute(select(column, unit.member.user_id))).all():
        members.setdefault(unit_id, []).append(user_id)
    return [UnitView(r.id, r.name, r.version, sorted(members.get(r.id, []))) for r in rows]


async def create_unit(session: AsyncSession, kind: Kind, name: str) -> UnitView:
    """A new site or group (409 `name_taken` if the tenant already has one with this name)."""
    unit = UNITS[kind]
    try:
        row = await unit.repository(session).add(unit.model(name=_name(name)))
    except IntegrityError as exc:
        raise Conflict(code="name_taken") from exc
    await record_event(
        session, _changed_event(kind, row.id, ["name"]), aggregate_id=row.id, aggregate_version=1
    )
    return UnitView(row.id, row.name, row.version, [])


async def rename_unit(
    session: AsyncSession, kind: Kind, unit_id: uuid.UUID, name: str, expected_version: int
) -> UnitView:
    """Rename (If-Match)."""
    unit = UNITS[kind]
    repository = unit.repository(session)
    try:
        row = await repository.update(
            unit_id, expected_version=expected_version, changes={"name": _name(name)}
        )
    except IntegrityError as exc:
        raise Conflict(code="name_taken") from exc
    await record_event(
        session,
        _changed_event(kind, unit_id, ["name"]),
        aggregate_id=unit_id,
        aggregate_version=row.version,
    )
    members = [m.user_id for m in await _members(session, kind, unit_id)]
    return UnitView(row.id, row.name, row.version, sorted(members))


async def _members(
    session: AsyncSession, kind: Kind, unit_id: uuid.UUID
) -> Sequence[SiteMember | GroupMember]:
    unit = UNITS[kind]
    column = getattr(unit.member, unit.member_unit_column)
    return (await session.scalars(select(unit.member).where(column == unit_id))).all()


async def _require_unit(session: AsyncSession, kind: Kind, unit_id: uuid.UUID) -> None:
    model = UNITS[kind].model
    found = await session.scalar(
        select(model.id).where(model.id == unit_id, model.deleted_at.is_(None))
    )
    if found is None:
        raise NotFound(code="site_not_found" if kind == "site" else "group_not_found")


# Checks a person adding a member to a group (WP-042): identity_access registers one so that a
# group carrying roles hands them out only to someone who could assign those roles directly.
# (session, the person adding, the group, the member being added).
MemberGuard = Callable[[AsyncSession, object, uuid.UUID, uuid.UUID], Awaitable[None]]
_MEMBER_GUARDS: list[MemberGuard] = []


def register_member_guard(guard: MemberGuard) -> None:
    """At start-up: a check run before a person adds anyone to a group."""
    if guard not in _MEMBER_GUARDS:
        _MEMBER_GUARDS.append(guard)


def unregister_member_guard(guard: MemberGuard) -> None:
    """At shutdown."""
    if guard in _MEMBER_GUARDS:
        _MEMBER_GUARDS.remove(guard)


# Marks a membership change no person makes (directory sync): its group mappings were checked
# when an admin made them (identity_access.check_group_grantable). Fail closed: callers must say.
SYSTEM_PATH = object()


async def add_member(
    session: AsyncSession,
    kind: Kind,
    unit_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    by: object,
) -> bool:
    """Add a user (idempotent: False if already a member). 404 for an unknown user or unit.

    `by`: the person adding (their subject), checked by the registered guards for groups, or
    `SYSTEM_PATH` for directory sync, whose group mappings were checked when made.
    """
    await _require_unit(session, kind, unit_id)
    if kind == "group" and by is not SYSTEM_PATH:
        for guard in _MEMBER_GUARDS:
            await guard(session, by, unit_id, user_id)
    unit = UNITS[kind]
    context = session.info[SESSION_TENANT_KEY]
    statement = (
        insert(unit.member)
        .values(
            tenant_id=context.tenant_id,
            user_id=user_id,
            created_by=context.user_id,
            **{unit.member_unit_column: unit_id},
        )
        .on_conflict_do_nothing()
    )
    try:
        result = await session.execute(statement.returning(unit.member.user_id))
    except IntegrityError as exc:  # the composite FK: no such user in this tenant
        raise NotFound(code="user_not_found") from exc
    added = result.first() is not None
    if added:
        await _membership_event(session, kind, unit_id, user_id, "added")
        access_changed(session)  # site/group scopes widen for this user
    return added


async def remove_member(
    session: AsyncSession, kind: Kind, unit_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """Remove a user (idempotent: False if they were not a member)."""
    await _require_unit(session, kind, unit_id)
    unit = UNITS[kind]
    column = getattr(unit.member, unit.member_unit_column)
    result = await session.execute(
        delete(unit.member)
        .where(column == unit_id, unit.member.user_id == user_id)
        .returning(unit.member.user_id)
    )
    removed = result.first() is not None
    if removed:
        await _membership_event(session, kind, unit_id, user_id, "removed")
        access_changed(session)
    return removed


async def _membership_event(
    session: AsyncSession,
    kind: UnitKind,
    unit_id: uuid.UUID,
    user_id: uuid.UUID,
    change: Literal["added", "removed"],
) -> None:
    await record_event(
        session,
        MembershipChanged(kind=kind, unit_id=unit_id, user_id=user_id, change=change),
        aggregate_id=unit_id,
    )


async def memberships(session: AsyncSession, user_id: uuid.UUID) -> Memberships:
    """The sites and groups `user_id` belongs to (in the session's tenant)."""
    sites = await session.scalars(
        select(SiteMember.site_id)
        .join(Site, Site.id == SiteMember.site_id)
        .where(SiteMember.user_id == user_id, Site.deleted_at.is_(None))
    )
    groups = await session.scalars(
        select(GroupMember.group_id)
        .join(SupportGroup, SupportGroup.id == GroupMember.group_id)
        .where(GroupMember.user_id == user_id, SupportGroup.deleted_at.is_(None))
    )
    return Memberships(frozenset(sites.all()), frozenset(groups.all()))


async def active_groups(
    session: AsyncSession, group_ids: frozenset[uuid.UUID]
) -> frozenset[uuid.UUID]:
    """Those of `group_ids` that are neither disabled nor deleted (roles through groups, WP-042)."""
    if not group_ids:
        return frozenset()
    found = await session.scalars(
        select(SupportGroup.id).where(
            SupportGroup.id.in_(group_ids),
            SupportGroup.deleted_at.is_(None),
            SupportGroup.disabled_at.is_(None),
        )
    )
    return frozenset(found.all())


def users_in_sites(site_ids: frozenset[uuid.UUID]) -> Select[uuid.UUID]:
    """Subquery of user IDs that belong to any of `site_ids` (for `site`-scoped user lists)."""
    return select(SiteMember.user_id).where(SiteMember.site_id.in_(site_ids))


def users_in_groups(group_ids: frozenset[uuid.UUID]) -> Select[uuid.UUID]:
    """Subquery of user IDs that belong to any of `group_ids`."""
    return select(GroupMember.user_id).where(GroupMember.group_id.in_(group_ids))


async def count_units(session: AsyncSession, kind: Kind) -> int:
    """How many sites/groups exist (tests, admin summary)."""
    model = UNITS[kind].model
    return int(
        await session.scalar(
            select(func.count()).select_from(model).where(model.deleted_at.is_(None))
        )
        or 0
    )


async def existing_unit_ids(
    session: AsyncSession, kind: Kind, ids: Sequence[uuid.UUID]
) -> frozenset[uuid.UUID]:
    """Which of `ids` are live sites / groups of the session's tenant (for other modules)."""
    if not ids:
        return frozenset()
    model = UNITS[kind].model
    found = await session.scalars(
        select(model.id).where(model.id.in_(list(ids)), model.deleted_at.is_(None))
    )
    return frozenset(found)
