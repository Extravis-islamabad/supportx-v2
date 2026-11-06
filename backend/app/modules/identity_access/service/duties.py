"""Open duties a role change would strand (REQ-REL-024 AC2): the role editor's preview.

Removing a permission from a role, a role from a person or a role from a support group can take
a permission away from people who still hold duties that need it: the release manager of an open
release, say. Before the admin saves, the editor lists those people and their open records.

Which records count as a duty is the owning module's knowledge, so modules register a
`DutyLookup` (`register_duties`, like the files' `register_owner_access`). identity_access works
out who actually loses which permission (a permission still granted by another role, directly or
through an active group, is not lost; scope is ignored: lost means no longer granted at all) and
asks only the lookups that answer for it. Lookups are read-only and run in the caller's tenant
transaction, so RLS bounds them.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.domain.permissions import Catalogue
from app.modules.identity_access.infra.models import (
    GroupRole,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.modules.organization import active_groups, memberships, users_in_groups

# The most duties one preview lists; beyond it the answer says `truncated`.
DUTY_LIMIT = 200


@dataclass(frozen=True, slots=True)
class OpenDuty:
    """One open record on which `user_id` holds a duty needing `permission`."""

    user_id: uuid.UUID
    permission: str
    record_type: str  # e.g. "release": shown through its record-type label
    record_id: uuid.UUID
    display_id: str  # e.g. "REL-12": shown as is
    duty: str  # a stable code, shown through the label `duty.<code>`


class DutyLookup(Protocol):
    """A module's answer to "which open duties of these people need these permissions?"."""

    # The permissions it answers for; None: ask it about any permission (e.g. when which
    # permission a duty needs is tenant data, like a release role's eligibility).
    permissions: frozenset[str] | None

    async def open_duties(
        self,
        session: AsyncSession,
        user_ids: Sequence[uuid.UUID],
        permissions: frozenset[str],
        *,
        limit: int,
    ) -> Sequence[OpenDuty]:
        """At most `limit` open duties of `user_ids` that need one of `permissions`. Read-only."""
        ...


_LOOKUPS: list[DutyLookup] = []


def register_duties(lookup: DutyLookup) -> None:
    """Called once at import by the module that owns the duties."""
    if lookup not in _LOOKUPS:
        _LOOKUPS.append(lookup)


def unregister_duties(lookup: DutyLookup) -> None:
    """For tests."""
    if lookup in _LOOKUPS:
        _LOOKUPS.remove(lookup)


@dataclass(frozen=True, slots=True)
class DutyPreview:
    """Who would lose what, and their open duties (only people with at least one duty)."""

    lost: dict[uuid.UUID, frozenset[str]]
    duties: list[OpenDuty]
    truncated: bool


async def _active(session: AsyncSession, user_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not user_ids:
        return set()
    found = await session.scalars(
        select(User.id).where(
            User.id.in_(user_ids), User.status == "active", User.deleted_at.is_(None)
        )
    )
    return set(found)


async def _holders(session: AsyncSession, role_id: uuid.UUID) -> set[uuid.UUID]:
    """Active people holding `role_id`, directly or through an active group."""
    direct = set(await session.scalars(select(UserRole.user_id).where(UserRole.role_id == role_id)))
    carrying = frozenset(
        await session.scalars(select(GroupRole.group_id).where(GroupRole.role_id == role_id))
    )
    groups = await active_groups(session, carrying)
    through = set(await session.scalars(users_in_groups(groups))) if groups else set()
    return await _active(session, direct | through)


async def _roles_of(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[set[uuid.UUID], dict[uuid.UUID, set[uuid.UUID]]]:
    """The person's own roles, and {role: groups it comes through} for their active groups."""
    direct = set(await session.scalars(select(UserRole.role_id).where(UserRole.user_id == user_id)))
    groups = await active_groups(session, (await memberships(session, user_id)).group_ids)
    through: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    if groups:
        for row in await session.execute(
            select(GroupRole.role_id, GroupRole.group_id).where(GroupRole.group_id.in_(groups))
        ):
            through[row.role_id].add(row.group_id)
    return direct, through


async def _permissions(
    session: AsyncSession, catalogue: Catalogue, role_ids: set[uuid.UUID]
) -> set[str]:
    """Every permission the roles grant: system roles' from the catalogue, custom ones stored."""
    if not role_ids:
        return set()
    found: set[str] = set()
    custom: set[uuid.UUID] = set()
    for row in await session.execute(
        select(Role.id, Role.key, Role.is_system).where(
            Role.id.in_(role_ids), Role.deleted_at.is_(None)
        )
    ):
        if row.is_system:
            found |= {permission for permission, _ in catalogue.system_grants(row.key)}
        else:
            custom.add(row.id)
    if custom:
        found |= set(
            await session.scalars(
                select(RolePermission.permission).where(RolePermission.role_id.in_(custom))
            )
        )
    return found


async def lost_by_role_change(
    session: AsyncSession,
    catalogue: Catalogue,
    role_id: uuid.UUID,
    *,
    remove_permissions: frozenset[str] = frozenset(),
    remove_groups: frozenset[uuid.UUID] = frozenset(),
) -> dict[uuid.UUID, frozenset[str]]:
    """{person: permissions they would no longer hold} after a role change.

    The change: the role loses `remove_permissions` and/or `remove_groups` stop carrying it.
    """
    granted = await _permissions(session, catalogue, {role_id})
    lost: dict[uuid.UUID, frozenset[str]] = {}
    for user_id in await _holders(session, role_id):
        direct, through = await _roles_of(session, user_id)
        keeps_role = role_id in direct or bool(through.get(role_id, set()) - remove_groups)
        # What this role still gives them after the change.
        from_role = (granted - remove_permissions) if keeps_role else set()
        others = (direct | set(through)) - {role_id}
        kept = from_role | await _permissions(session, catalogue, others)
        gone = frozenset(granted - kept)
        if gone:
            lost[user_id] = gone
    return lost


async def lost_by_user_roles(
    session: AsyncSession,
    catalogue: Catalogue,
    user_id: uuid.UUID,
    remove_roles: frozenset[uuid.UUID],
) -> dict[uuid.UUID, frozenset[str]]:
    """{person: permissions lost} if their own `remove_roles` were taken away.

    A role they also hold through a group stays.
    """
    if not await _active(session, {user_id}):
        return {}
    direct, through = await _roles_of(session, user_id)
    held = direct | set(through)
    remaining = (direct - remove_roles) | set(through)
    gone = frozenset(
        await _permissions(session, catalogue, held)
        - await _permissions(session, catalogue, remaining)
    )
    return {user_id: gone} if gone else {}


async def open_duties(
    session: AsyncSession,
    lost: dict[uuid.UUID, frozenset[str]],
    *,
    limit: int = DUTY_LIMIT,
) -> DutyPreview:
    """The registered lookups' open duties for what each person loses, at most `limit`."""
    by_loss: dict[frozenset[str], list[uuid.UUID]] = defaultdict(list)
    for user_id, permissions in sorted(lost.items()):
        by_loss[permissions].append(user_id)
    duties: list[OpenDuty] = []
    truncated = False
    for permissions, user_ids in by_loss.items():
        for lookup in _LOOKUPS:
            asked = permissions if lookup.permissions is None else permissions & lookup.permissions
            if not asked:
                continue
            left = limit - len(duties)
            if left <= 0:
                truncated = True
                break
            # One more than fits tells "exactly full" from "more beyond".
            found = await lookup.open_duties(session, user_ids, asked, limit=left + 1)
            # Only what the person really loses, whatever a lookup returns.
            kept = [d for d in found if d.user_id in lost and d.permission in lost[d.user_id]]
            if len(kept) > left:
                truncated = True
            duties.extend(kept[:left])
    affected = {d.user_id for d in duties}
    return DutyPreview(
        lost={user: lost[user] for user in sorted(affected)}, duties=duties, truncated=truncated
    )
