"""Roles and support groups that follow a person's external groups (WP-057 S5c-1a, REQ-SEC-014).

`follow` is the **one** function directory sync uses, and S5c-1b's sign-in will use it too
(lane B's condition 6). It holds a per-person lock (condition 1), never touches vendor
support, service or break-glass accounts (condition 4), and never removes the last tenant admin
or hand-made access. Each change is audited with its source (condition 5) and refreshes compiled
access in the same transaction.

The rules live in domain/group_mappings.py; the plan is ~/Extravis/plans/wp-057-s5c-plan.md.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import access_changed
from app.core.database import SESSION_TENANT_KEY
from app.core.logging import get_logger
from app.modules.audit import WORKER, AuditActorType, record
from app.modules.identity_access.domain.group_mappings import (
    Held,
    Plan,
    SourceKind,
    Target,
    plan,
    privileged,
)
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.domain.permissions import Catalogue
from app.modules.identity_access.domain.support_grants import SUPPORT_USER_TYPE
from app.modules.identity_access.infra.models import (
    AccessSource,
    GroupRole,
    IdpGroupMapping,
    Role,
    RolePermission,
    User,
)
from app.modules.identity_access.service import roles
from app.modules.organization import SYSTEM_PATH, add_member, remove_member

if TYPE_CHECKING:
    from collections.abc import Iterable

log = get_logger("identity_access.group_mappings")

# Audit actions (audit's catalogue; lane A, rule 8): one entry per change, naming the mapping.
ROLE_MAPPED = "user.role_mapped"
MEMBER_MAPPED = "group.member_mapped"
KEPT_LAST_ADMIN = "idp_group_mapping.kept_last_admin"
NEVER_FOLLOWED = frozenset({SUPPORT_USER_TYPE, UserType.SERVICE.value})


def _tenant(session: AsyncSession) -> uuid.UUID:
    return session.info[SESSION_TENANT_KEY].tenant_id  # type: ignore[no-any-return]  # TenantContext


async def lock_person(session: AsyncSession, user_id: uuid.UUID) -> None:
    """One follow per person at a time (lane B's condition 1): sign-ins and syncs queue here."""
    key = func.hashtextextended(f"idp-groups:{_tenant(session)}:{user_id}", 0)
    await session.execute(select(func.pg_advisory_xact_lock(key)))


async def role_is_privileged(
    session: AsyncSession, catalogue: Catalogue, role_id: uuid.UUID
) -> bool:
    """Tenant admin, or a role holding a never_via_idp right (its system defaults included)."""
    role = await session.get(Role, role_id)
    if role is None:
        return False
    rights: Iterable[str]
    if role.is_system:
        rights = (p for p, _ in catalogue.system_grants(role.key, technician_scope="all"))
    else:
        rights = await session.scalars(
            select(RolePermission.permission).where(RolePermission.role_id == role_id)
        )
    return privileged(role.key, rights)


async def group_is_privileged(
    session: AsyncSession, catalogue: Catalogue, group_id: uuid.UUID
) -> bool:
    """A support group carrying a privileged role makes its members privileged (WP-042)."""
    carried = await session.scalars(select(GroupRole.role_id).where(GroupRole.group_id == group_id))
    for role_id in carried:
        if await role_is_privileged(session, catalogue, role_id):
            return True
    return False


async def _mappings(
    session: AsyncSession, source_kind: SourceKind, source_id: uuid.UUID
) -> list[IdpGroupMapping]:
    rows = await session.scalars(
        select(IdpGroupMapping).where(
            IdpGroupMapping.source_kind == source_kind.value,
            IdpGroupMapping.source_id == source_id,
            IdpGroupMapping.deleted_at.is_(None),
        )
    )
    return list(rows)


def _target(mapping: IdpGroupMapping) -> Target:
    if mapping.role_id is not None:
        return Target("role", str(mapping.role_id))
    return Target("group", str(mapping.group_id))


async def _held(
    session: AsyncSession, user_id: uuid.UUID, mapping_ids: frozenset[uuid.UUID]
) -> tuple[set[Held], set[Target]]:
    """The person's (target, mapping) pairs from these mappings, and targets other sources hold."""
    rows = await session.scalars(select(AccessSource).where(AccessSource.user_id == user_id))
    mine: set[Held] = set()
    others: set[Target] = set()
    for row in rows:
        target = Target(row.target_kind, str(row.target_id))  # type: ignore[arg-type]  # checked in SQL
        if row.mapping_id in mapping_ids:
            mine.add(Held(target, str(row.mapping_id)))
        else:
            others.add(target)
    return mine, others


async def follow(
    session: AsyncSession,
    *,
    source_kind: SourceKind,
    source_id: uuid.UUID,
    user_id: uuid.UUID,
    group_ids: frozenset[str] | None,
) -> Plan | None:
    """Make the person's mapped access from this source match `group_ids`.

    `None` means "no complete list" (missing, malformed or overage): nothing changes (lane B's
    condition 3). Returns what changed, or None when the person is never followed.
    """
    if group_ids is None:
        return None
    await lock_person(session, user_id)
    person = await session.get(User, user_id)
    if person is None or person.user_type in NEVER_FOLLOWED or person.break_glass:
        return None
    mappings = await _mappings(session, source_kind, source_id)
    wanted = {
        Held(_target(m), str(m.id))
        for m in mappings
        if m.enabled and m.external_group_id in group_ids
    }
    held, others = await _held(session, user_id, frozenset(m.id for m in mappings))
    changes = plan(wanted, held, other_sources=others)
    if changes.empty:
        return changes
    for item in changes.add_sources:
        await _gain(session, user_id, item)
    await _lose(session, user_id, changes, source_kind)
    access_changed(session)
    return changes


async def _gain(session: AsyncSession, user_id: uuid.UUID, item: Held) -> None:
    target_id = uuid.UUID(item.target.id)
    if item.target.kind == "role":
        made = await roles.assign_mapped(session, user_id, target_id)
    else:
        made = await add_member(session, "group", target_id, user_id, by=SYSTEM_PATH, managed=True)
    session.add(
        AccessSource(
            tenant_id=_tenant(session),
            user_id=user_id,
            target_kind=item.target.kind,
            target_id=target_id,
            mapping_id=uuid.UUID(item.mapping_id),
        )
    )
    await session.flush()
    if made:
        await _audit(session, item, user_id, "added")


async def _lose(
    session: AsyncSession, user_id: uuid.UUID, changes: Plan, source_kind: SourceKind
) -> None:
    for item in changes.drop_sources:
        source = await session.get(
            AccessSource,
            (_tenant(session), user_id, item.target.kind, uuid.UUID(item.target.id),
             uuid.UUID(item.mapping_id)),
        )  # fmt: skip
        if source is not None:
            await session.delete(source)
    await session.flush()
    if not changes.lose:
        return
    # The removals in a savepoint: if they'd leave the tenant without an admin (directly or
    # through a group, WP-042), they're undone and the person keeps their access (audited).
    savepoint = await session.begin_nested()
    removed: list[Target] = []
    for target in changes.lose:
        target_id = uuid.UUID(target.id)
        if target.kind == "role":
            gone = await roles.remove_mapped(session, user_id, target_id)
        else:
            gone = await remove_member(session, "group", target_id, user_id, via="mapping")
        if gone:
            removed.append(target)
    if removed and not await roles.tenant_admin_holders(session):
        await savepoint.rollback()
        await record(
            session,
            action_code=KEPT_LAST_ADMIN,
            facts=WORKER,
            object_type="user",
            object_id=user_id,
            details={"source": source_kind.value, "targets": [t.id for t in removed]},
            actor=(AuditActorType.SYSTEM, None),
        )
        log.warning("idp_group_mapping_kept_last_admin", user_id=str(user_id))
        return
    await savepoint.commit()
    by_target = {h.target: h for h in changes.drop_sources}
    for target in removed:
        await _audit(session, by_target[target], user_id, "removed")


async def _audit(session: AsyncSession, item: Held, user_id: uuid.UUID, change: str) -> None:
    await record(
        session,
        action_code=ROLE_MAPPED if item.target.kind == "role" else MEMBER_MAPPED,
        facts=WORKER,
        object_type="user",
        object_id=user_id,
        details={"change": change, "target": item.target.id, "mapping_id": item.mapping_id},
        actor=(AuditActorType.SYSTEM, None),
    )
