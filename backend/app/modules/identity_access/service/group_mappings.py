"""Roles and support groups that follow a person's external groups (WP-057 S5c-1a, REQ-SEC-014).

`follow` is the **one** function directory sync uses, and S5c-1b's sign-in will use it too
(lane B's condition 6). It holds a per-person lock (condition 1), never touches vendor
support, service or break-glass accounts (condition 4), and never removes the last tenant admin
or hand-made access. Each change is audited with its source (condition 5) and refreshes compiled
access in the same transaction.

The rules live in domain/group_mappings.py; the plan is ~/Extravis/plans/wp-057-s5c-plan.md.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import access_changed
from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.modules.audit import WORKER, AuditActorType, record
from app.modules.identity_access.domain.group_mappings import (
    MAX_GROUP_ID,
    SSO_GROUP_MAPPINGS_READY,
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
    AccessSettings,
    AccessSource,
    GroupRole,
    IdpGroupMapping,
    Role,
    RolePermission,
    SsoProvider,
    User,
)
from app.modules.identity_access.service import roles
from app.modules.organization import SYSTEM_PATH, add_member, remove_member, unmanage_member
from app.shared.clock import system_clock

if TYPE_CHECKING:
    from collections.abc import Iterable

log = get_logger("identity_access.group_mappings")

# Audit actions (audit's catalogue; lane A, rule 8): one entry per change, naming the mapping.
ROLE_MAPPED = "user.role_mapped"
MEMBER_MAPPED = "group.member_mapped"
KEPT_LAST_ADMIN = "idp_group_mapping.kept_last_admin"
CREATED = "idp_group_mapping.created"
REMOVED = "idp_group_mapping.removed"
OPT_IN_CHANGED = "idp_group_mapping.privileged_opt_in_changed"
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
        try:
            made = await add_member(
                session, "group", target_id, user_id, by=SYSTEM_PATH, managed=True
            )
        except NotFound:
            # The support group was removed: nothing to give (lane A; the old sync's REFUSED).
            log.info("idp_group_mapping_target_gone", group_id=str(target_id))
            return
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
    session: AsyncSession,
    user_id: uuid.UUID,
    changes: Plan,
    source_kind: SourceKind,
) -> bool:
    """Drop this source's rows and remove what no source gives any more, as one savepoint.

    Returns True when it kept the last admin (nothing of this call changed).

    If that would take the tenant's last admin away from this person (they were an admin, are
    not after, and nobody else is: directly or through a group, WP-042), the whole savepoint is
    undone, source rows included, so the access stays managed **and** sourced, and a later
    follow removes it once another admin exists (lane B's #620 review). Audited.
    """
    if not changes.drop_sources and not changes.lose:
        return False
    before = await roles.tenant_admin_holders(session) if changes.lose else set()
    savepoint = await session.begin_nested()
    for item in changes.drop_sources:
        source = await session.get(
            AccessSource,
            (_tenant(session), user_id, item.target.kind, uuid.UUID(item.target.id),
             uuid.UUID(item.mapping_id)),
        )  # fmt: skip
        if source is not None:
            await session.delete(source)
    await session.flush()
    removed: list[Target] = []
    for target in changes.lose:
        target_id = uuid.UUID(target.id)
        if target.kind == "role":
            gone = await roles.remove_mapped(session, user_id, target_id)
        else:
            gone = await remove_member(session, "group", target_id, user_id, via="mapping")
        if gone:
            removed.append(target)
    if removed and user_id in before:
        after = await roles.tenant_admin_holders(session)
        if user_id not in after and not after:
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
            return True
    await savepoint.commit()
    by_target = {h.target: h for h in changes.drop_sources}
    for target in removed:
        await _audit(session, by_target.get(target) or Held(target, ""), user_id, "removed")
    return False


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


# --- the mappings themselves (admins; directory connectors' screen today) ----------------------

PRIVILEGED_CODE = "mapping_grants_privileged_access"
COMING_SOON_CODE = "idp_group_mappings_coming_soon"
CHOICE_REQUIRED_CODE = "mapping_in_use_choice_required"
HOLDS_LAST_ADMIN_CODE = "mapping_holds_last_admin"
OnHeld = Literal["keep", "remove"]


# Which modules own a mapping's sources (rule e: identity_access never reads their tables).
# integrations registers "directory"; this module's own SSO set-ups are checked here.
SourceCheck = Callable[[AsyncSession, uuid.UUID], Awaitable[bool]]
_SOURCES: dict[SourceKind, SourceCheck] = {}


def register_group_source(kind: SourceKind, check: SourceCheck) -> None:
    """A module says how to tell that one of its sources exists (at its import)."""
    _SOURCES[kind] = check


async def require_source(session: AsyncSession, kind: SourceKind, source_id: uuid.UUID) -> None:
    """404 `mapping_source_not_found` unless the source exists in this tenant."""
    if kind is SourceKind.SSO:
        found = await session.scalar(select(SsoProvider.id).where(SsoProvider.id == source_id))
        exists = found is not None
    else:
        check = _SOURCES.get(kind)
        exists = check is not None and await check(session, source_id)
    if not exists:
        raise NotFound(code="mapping_source_not_found")


# How fresh a source's groups are (rule e): integrations registers the directory's last
# successful sync. A directory that hasn't synced for STALE_AFTER keeps its managed access, and
# the security overview counts it (the coordinator, 2026-11-24: visible, never fail closed).
STALE_AFTER = timedelta(hours=24)
Freshness = Callable[[AsyncSession, uuid.UUID], Awaitable["datetime | None"]]
_FRESHNESS: dict[SourceKind, Freshness] = {}


def register_source_freshness(kind: SourceKind, last_success: Freshness) -> None:
    """A module says when one of its sources last brought its groups in successfully."""
    _FRESHNESS[kind] = last_success


async def stale_sources(session: AsyncSession, now: "datetime") -> int:
    """Directory sources holding managed access whose last successful sync is over a day old."""
    last_success = _FRESHNESS.get(SourceKind.DIRECTORY)
    if last_success is None:
        return 0
    sources = await session.scalars(
        select(IdpGroupMapping.source_id)
        .where(
            IdpGroupMapping.source_kind == SourceKind.DIRECTORY.value,
            IdpGroupMapping.deleted_at.is_(None),
            IdpGroupMapping.id.in_(select(AccessSource.mapping_id)),
        )
        .distinct()
    )
    stale = 0
    for source in sources:
        last = await last_success(session, source)
        if last is None or now - last > STALE_AFTER:
            stale += 1
    return stale


async def mapped_external_groups(
    session: AsyncSession, source_kind: SourceKind, source_id: uuid.UUID
) -> frozenset[str]:
    """The external group IDs this source's enabled mappings name (what a sync must fetch)."""
    return frozenset(
        m.external_group_id for m in await _mappings(session, source_kind, source_id) if m.enabled
    )


async def list_mappings(
    session: AsyncSession, source_kind: SourceKind, source_id: uuid.UUID
) -> list[IdpGroupMapping]:
    """A source's live mappings, oldest first."""
    rows = await _mappings(session, source_kind, source_id)
    return sorted(rows, key=lambda m: (m.created_at, str(m.id)))


async def create_mapping(  # noqa: PLR0913 - the source, the group and its one target, explicit
    session: AsyncSession,
    *,
    source_kind: SourceKind,
    source_id: uuid.UUID,
    external_group_id: str,
    external_name: str | None,
    role_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
) -> IdpGroupMapping:
    """A new mapping, after the guards: SSO waits for S5c-1b; privileged access is refused."""
    if source_kind is SourceKind.SSO and not SSO_GROUP_MAPPINGS_READY:
        raise ValidationFailed(errors=[_error("source_kind", COMING_SOON_CODE)])
    await require_source(session, source_kind, source_id)
    if (role_id is None) == (group_id is None):
        raise ValidationFailed(errors=[_error("target", "one_target_required")])
    external = external_group_id.strip()
    if not 1 <= len(external) <= MAX_GROUP_ID:
        raise ValidationFailed(errors=[_error("external_group_id", "invalid_value")])
    if not await privileged_allowed(session):
        catalogue = roles.running_catalogue()
        if role_id is not None and await role_is_privileged(session, catalogue, role_id):
            raise Conflict(code=PRIVILEGED_CODE)
        if group_id is not None and await group_is_privileged(session, catalogue, group_id):
            raise Conflict(code=PRIVILEGED_CODE)
    mapping = IdpGroupMapping(
        tenant_id=_tenant(session),
        source_kind=source_kind.value,
        source_id=source_id,
        external_group_id=external,
        external_name=(external_name or "").strip()[:MAX_GROUP_ID] or None,
        role_id=role_id,
        group_id=group_id,
    )
    session.add(mapping)
    try:
        await session.flush()
    except IntegrityError as exc:  # the role is not this tenant's, or the same mapping exists
        raise Conflict(code="mapping_exists") from exc
    return mapping


async def privileged_allowed(session: AsyncSession) -> bool:
    """Whether this tenant lets a mapping give tenant admin or a never_via_idp right (opt-in)."""
    found = await session.scalar(select(AccessSettings.mappings_may_grant_privileged))
    return bool(found)


async def set_privileged_allowed(session: AsyncSession, *, allowed: bool) -> bool:
    """Turn the opt-in on or off (the route asks for a recent sign-in). True if it changed.

    Turning it off removes nothing: existing mappings keep working, and new privileged ones are
    refused again. Audited either way, with who and when kept on the settings row.
    """
    context = session.info[SESSION_TENANT_KEY]
    before = await privileged_allowed(session)
    if before == allowed:
        return False
    now = system_clock.now()
    values = {
        "mappings_may_grant_privileged": allowed,
        "mappings_privileged_set_at": now,
        "mappings_privileged_set_by": context.user_id,
        "updated_at": now,
        "updated_by": context.user_id,
    }
    await session.execute(
        insert(AccessSettings)
        .values(tenant_id=context.tenant_id, created_by=context.user_id, version=1, **values)
        .on_conflict_do_update(
            index_elements=[AccessSettings.tenant_id],
            set_={**values, "version": AccessSettings.version + 1},
        )
    )
    return True


async def guard_group_role(
    session: AsyncSession, catalogue: Catalogue, group_id: uuid.UUID, role_id: uuid.UUID
) -> None:
    """409 when a privileged role goes onto a group a live mapping targets, without the opt-in."""
    targeted = await session.scalar(
        select(func.count()).where(
            IdpGroupMapping.group_id == group_id, IdpGroupMapping.deleted_at.is_(None)
        )
    )
    if not targeted or await privileged_allowed(session):
        return
    if await role_is_privileged(session, catalogue, role_id):
        raise Conflict(code=PRIVILEGED_CODE)


async def rename_mapping(session: AsyncSession, mapping_id: uuid.UUID, name: str | None) -> None:
    """A mapping's display name (the source's group name); its ID and target never change."""
    mapping = await session.get(IdpGroupMapping, mapping_id)
    if mapping is None or mapping.deleted_at is not None:
        raise NotFound(code="mapping_not_found")
    mapping.external_name = (name or "").strip()[:MAX_GROUP_ID] or None


async def guard_role_rights(
    session: AsyncSession, role_id: uuid.UUID, role_key: str, rights: set[str]
) -> None:
    """409 when a role a live mapping gives would become privileged, without the opt-in.

    Directly, or through a group carrying the role (lane B's #620 review).
    """
    if not privileged(role_key, rights) or await privileged_allowed(session):
        return
    direct = await session.scalar(
        select(func.count()).where(
            IdpGroupMapping.role_id == role_id, IdpGroupMapping.deleted_at.is_(None)
        )
    )
    carrying = select(GroupRole.group_id).where(GroupRole.role_id == role_id)
    through = await session.scalar(
        select(func.count()).where(
            IdpGroupMapping.group_id.in_(carrying), IdpGroupMapping.deleted_at.is_(None)
        )
    )
    if direct or through:
        raise Conflict(code=PRIVILEGED_CODE)


async def holders(session: AsyncSession, mapping_id: uuid.UUID) -> int:
    """How many people hold access through this mapping (the remove dialog's count)."""
    count = await session.scalar(
        select(func.count(func.distinct(AccessSource.user_id))).where(
            AccessSource.mapping_id == mapping_id
        )
    )
    return int(count or 0)


async def remove_mapping(
    session: AsyncSession, mapping_id: uuid.UUID, *, on_held: OnHeld | None
) -> None:
    """Delete a mapping; what it gave stays as hand-made ("keep") or goes at once ("remove").

    The coordinator's Q2: never silent. With anyone holding access through it, `on_held` is
    required (422 otherwise); "remove" is the route's to protect with RecentAuth.
    """
    mapping = await session.get(IdpGroupMapping, mapping_id)
    if mapping is None or mapping.deleted_at is not None:
        raise NotFound(code="mapping_not_found")
    held = list(
        await session.scalars(select(AccessSource).where(AccessSource.mapping_id == mapping_id))
    )
    if held and on_held is None:
        raise ValidationFailed(errors=[_error("on_held", CHOICE_REQUIRED_CODE)])
    # In one order (person, then target), so two removals can't deadlock (lane B's review).
    whole = await session.begin_nested()
    held.sort(key=lambda r: (str(r.user_id), r.target_kind, str(r.target_id)))
    for row in held:
        await lock_person(session, row.user_id)
        target = Target(row.target_kind, str(row.target_id))  # type: ignore[arg-type]  # checked in SQL
        others = await session.scalar(
            select(func.count()).where(
                AccessSource.user_id == row.user_id,
                AccessSource.target_kind == row.target_kind,
                AccessSource.target_id == row.target_id,
                AccessSource.mapping_id != mapping_id,
            )
        )
        if others or on_held == "keep":
            await session.delete(row)
            await session.flush()
            if not others:
                await _make_hand_made(session, row)
            continue  # another mapping still gives it, or it stays as hand-made
        # "remove": the source row goes in the same savepoint as the access (kept last admin
        # keeps both, lane B's review).
        kept = await _lose(
            session,
            row.user_id,
            Plan(
                add_sources=(),
                drop_sources=(Held(target, str(mapping_id)),),
                gain=(),
                lose=(target,),
            ),
            SourceKind(mapping.source_kind),
        )
        if kept:
            # Removing it would take the tenant's last admin away: refused, nothing changed
            # (lane B's #620 review). "keep" still works, or another admin first.
            await whole.rollback()
            raise Conflict(code=HOLDS_LAST_ADMIN_CODE)
    await whole.commit()
    mapping.deleted_at = system_clock.now()
    access_changed(session)


async def _make_hand_made(session: AsyncSession, row: AccessSource) -> None:
    if row.target_kind == "role":
        await roles.unmanage(session, row.user_id, row.target_id)
    else:
        await unmanage_member(session, "group", row.target_id, row.user_id)


def _error(field: str, code: str) -> FieldError:
    return FieldError(field=f"body.{field}", code=code, message_key=f"errors.{code}")
