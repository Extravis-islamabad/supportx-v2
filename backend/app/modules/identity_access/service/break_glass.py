"""Break-glass admins and the single sign-on policy (REQ-SEC-009, REQ-SEC-026; WP-057 S1b).

The coordinator's rules (2026-11-12), with lane B's condition 5:
- Only a tenant admin marks someone break-glass, or exempts them from the IP allow-lists; the
  route audits every change (`identity.break_glass_changed`).
- A break-glass account is a tenant admin with MFA enrolled (refused otherwise); an IP-exempt
  one still needs MFA (the sign-in checks it again: domain/sign_in_policy.py).
- Turning "single sign-on required" on needs at least one active break-glass admin, and the
  last one cannot be removed (or switched off) while it is on.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules.identity_access.domain.permissions import TENANT_ADMIN
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.domain.sign_in_policy import SsoRequired, change_refusal
from app.modules.identity_access.events import IdentitySettingsChanged, UserUpdated
from app.modules.identity_access.infra.models import IdentitySettings, Role, User, UserRole
from app.shared.events import record_event
from app.shared.history import stale_version


async def sso_rule(session: AsyncSession) -> SsoRequired:
    """The tenant's rule (off when never saved)."""
    found = await session.scalar(select(IdentitySettings.sso_required))
    return SsoRequired(found) if found else SsoRequired.OFF


async def active_break_glass(session: AsyncSession, *, except_user: uuid.UUID | None = None) -> int:
    """Active, live break-glass admins of the tenant (optionally leaving one out)."""
    statement = (
        select(func.count())
        .select_from(User)
        .where(User.break_glass.is_(True), User.status == "active", User.deleted_at.is_(None))
    )
    if except_user is not None:
        statement = statement.where(User.id != except_user)
    return int(await session.scalar(statement) or 0)


async def _is_tenant_admin(session: AsyncSession, user_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(Role.id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, Role.key == TENANT_ADMIN, Role.deleted_at.is_(None))
        .limit(1)
    )
    return found is not None


@dataclass(frozen=True)
class BreakGlassState:
    """A person's break-glass marks and the record's version."""

    user_id: uuid.UUID
    break_glass: bool
    ip_exempt: bool
    version: int


async def _check_change(
    session: AsyncSession, person: User, *, break_glass: bool, ip_exempt: bool
) -> None:
    """Refuse a change the rules forbid (Conflict with the reason)."""
    user_id = person.id
    if ip_exempt and not break_glass:
        raise Conflict(code="break_glass_ip_exempt_needs_break_glass")
    if break_glass:
        if not await _is_tenant_admin(session, user_id):
            raise Conflict(code="break_glass_needs_admin")
        if person.mfa_enrolled_at is None:
            raise Conflict(code="break_glass_needs_mfa")
    elif person.break_glass:
        remaining = await active_break_glass(session, except_user=user_id)
        refusal = change_refusal(await sso_rule(session), remaining, removing_admin=True)
        if refusal is not None:
            raise Conflict(code=refusal)


async def set_break_glass(  # noqa: PLR0913 - the change and who makes it, keyword-only
    session: AsyncSession,
    subject: Subject,
    user_id: uuid.UUID,
    *,
    break_glass: bool,
    ip_exempt: bool,
    expected_version: int,
) -> tuple[BreakGlassState, dict[str, object]]:
    """Mark or unmark `user_id`; the new state and the audit details (before and after)."""
    if not subject.is_tenant_admin:
        raise PermissionDenied(code="break_glass_admin_only")
    person = await session.get(User, user_id)
    if person is None or person.deleted_at is not None:
        raise NotFound(code="user_not_found")
    if person.version != expected_version:
        raise await stale_version(session, person, expected_version=expected_version)
    await _check_change(session, person, break_glass=break_glass, ip_exempt=ip_exempt)
    before = {
        "break_glass": person.break_glass,
        "break_glass_ip_exempt": person.break_glass_ip_exempt,
    }
    after = {"break_glass": break_glass, "break_glass_ip_exempt": ip_exempt}
    changed = [name for name in before if before[name] != after[name]]
    if changed:
        person.break_glass = break_glass
        person.break_glass_ip_exempt = ip_exempt
        person.version += 1
        await session.flush()
        await record_event(
            session,
            UserUpdated(user_id=user_id, changed_fields=changed),
            aggregate_id=user_id,
            aggregate_version=person.version,
        )
    details: dict[str, object] = (
        {"changed_fields": changed, "before": before, "after": after} if changed else {}
    )
    return BreakGlassState(user_id, break_glass, ip_exempt, person.version), details


@dataclass(frozen=True)
class SsoPolicy:
    """The tenant's single sign-on policy and the settings row's version."""

    required: SsoRequired
    also_require_mfa: bool
    version: int


async def get_sso_policy(session: AsyncSession) -> SsoPolicy:
    """The policy (off, provider MFA trusted, version 0 when never saved)."""
    row = await session.scalar(select(IdentitySettings))
    if row is None:
        return SsoPolicy(SsoRequired.OFF, also_require_mfa=False, version=0)
    return SsoPolicy(SsoRequired(row.sso_required), row.sso_also_require_mfa, row.version)


async def save_sso_policy(
    session: AsyncSession,
    *,
    required: SsoRequired,
    also_require_mfa: bool,
    expected_version: int,
) -> tuple[SsoPolicy, dict[str, object]]:
    """Save the policy if the row is at `expected_version`; the audit details too.

    Turning the requirement on is refused without an active break-glass admin (AC2).
    """
    refusal = change_refusal(required, await active_break_glass(session), removing_admin=False)
    if refusal is not None:
        raise Conflict(code=refusal)
    current = await get_sso_policy(session)
    if current.version != expected_version:
        row = await session.scalar(select(IdentitySettings))
        if row is not None:
            raise await stale_version(session, row, expected_version=expected_version)
        raise Conflict(code="version_conflict", params={"expected_version": expected_version})
    columns = {"sso_required": required.value, "sso_also_require_mfa": also_require_mfa}
    before = {
        "sso_required": current.required.value,
        "sso_also_require_mfa": current.also_require_mfa,
    }
    changed = [name for name in columns if columns[name] != before[name]]
    if not changed:
        return current, {}
    context = session.info[SESSION_TENANT_KEY]
    statement = (
        insert(IdentitySettings)
        .values(
            tenant_id=context.tenant_id,
            created_by=context.user_id,
            updated_by=context.user_id,
            version=1,
            **columns,
        )
        .on_conflict_do_update(
            index_elements=[IdentitySettings.tenant_id],
            set_={
                **columns,
                "updated_at": datetime.now(UTC),
                "updated_by": context.user_id,
                "version": IdentitySettings.version + 1,
            },
            where=IdentitySettings.version == expected_version,
        )
        .returning(IdentitySettings.version)
    )
    version = await session.scalar(statement)
    if version is None:  # changed by someone else between the read and the write
        raise Conflict(code="version_conflict", params={"expected_version": expected_version})
    await record_event(
        session,
        IdentitySettingsChanged(changed_fields=changed),
        aggregate_id=context.tenant_id,
        aggregate_version=version,
    )
    details: dict[str, object] = {"changed_fields": changed, "before": before, "after": columns}
    return SsoPolicy(required, also_require_mfa, version), details
