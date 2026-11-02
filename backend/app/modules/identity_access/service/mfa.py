"""MFA policy and status (WP-039 session 3; REQ-SEC-022, 024, 025; domain/mfa.py).

Who must enrol is SupportX's; the authenticator and recovery codes are Keycloak's.

- **Policy:** a mode per role (Admin > Sign-in and security, `identity.manage`); no row means the
  Appendix A default. Saving one role's mode re-checks everyone holding that role.
- **People:** `users.mfa_required_since` starts the grace period when MFA becomes required for
  a person here (a role change, a policy change) and is cleared when it no longer is.
  `users.mfa_enrolled_at` mirrors whether Keycloak holds their authenticator; it is refreshed at
  every sign-in, after the person sets MFA up from My account, and by an admin reset.
- **Enforcement:** past the grace period without an authenticator, Keycloak's own required
  actions (code generator, then recovery codes) are added to the person's account: at their
  next sign-in they enrol before anything else (AC2). The sign-in itself checks it too, so the
  hour between schedule runs never lets anyone in. Required actions are only ever added, never
  removed: another tenant of the same person may require MFA (the strictest tenant wins).
- **Reset** (REQ-SEC-025 AC2, 3): an admin, never for themselves, removes the person's
  authenticator and recovery codes; they must enrol again at their next sign-in. Audited by the
  route; the person is told by e-mail.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from markupsafe import Markup
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain import mfa as rules
from app.modules.identity_access.domain.permissions import SYSTEM_ROLES
from app.modules.identity_access.events import MfaChanged
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminNotConfigured,
    IdentityAdminUnavailable,
    KeycloakAdmin,
)
from app.modules.identity_access.infra.models import (
    IdentitySettings,
    MfaPolicy,
    Role,
    User,
    UserRole,
)
from app.modules.identity_access.service.policy import UNMAPPED_DEFAULT
from app.modules.identity_access.service.roles import ensure_system_roles
from app.modules.organization import email_branding, get_current_tenant
from app.shared.events import ConsumerSpec, EventEnvelope, record_event
from app.shared.history import stale_version
from app.shared.ids import new_id
from app.shared.labels import LANGUAGES, html_label, plain_label
from app.shared.mail import Language, OutgoingMail, mail_configured, queue_mail, wrap_html

log = get_logger(__name__)


@dataclass(frozen=True)
class RolePolicy:
    """One role's MFA mode and how many of its holders have enrolled (REQ-SEC-024 AC3)."""

    role_id: uuid.UUID
    key: str | None  # system roles: their key; custom roles: None
    name: str
    mode: rules.Mode
    is_default: bool
    holders: int
    enrolled: int
    version: int  # 0: never saved (the default)


async def grace_days(session: AsyncSession) -> int:
    """The tenant's grace period in days (Appendix A default when never saved)."""
    found = await session.scalar(select(IdentitySettings.mfa_grace_days))
    return rules.GRACE_DAYS_DEFAULT if found is None else int(found)


async def _modes(session: AsyncSession) -> dict[uuid.UUID, tuple[rules.Mode, MfaPolicy | None]]:
    """Every role's mode (saved or default) and its saved row."""
    roles = (await session.execute(select(Role.id, Role.key, Role.is_system))).all()
    saved = {row.role_id: row for row in await session.scalars(select(MfaPolicy))}
    found: dict[uuid.UUID, tuple[rules.Mode, MfaPolicy | None]] = {}
    for role in roles:
        row = saved.get(role.id)
        mode: rules.Mode = (
            row.mode  # type: ignore[assignment]  # the column's check constraint holds the codes
            if row is not None
            else rules.default_mode(role.key if role.is_system else None)
        )
        found[role.id] = (mode, row)
    return found


async def person_mode(session: AsyncSession, user_id: uuid.UUID) -> rules.Mode:
    """The strictest mode of the person's roles here (unmapped people: their type's role)."""
    person = (
        await session.execute(
            select(User.user_type, User.roles_mapped_at).where(User.id == user_id)
        )
    ).one_or_none()
    if person is None:
        return "off"
    role_ids = list(
        await session.scalars(select(UserRole.role_id).where(UserRole.user_id == user_id))
    )
    modes = await _modes(session)
    if not role_ids and person.roles_mapped_at is None:
        return rules.default_mode(UNMAPPED_DEFAULT[person.user_type])
    return rules.strictest([modes[role_id][0] for role_id in role_ids if role_id in modes])


async def list_policies(session: AsyncSession) -> list[RolePolicy]:
    """Every role with its mode and enrolment counts, system roles first."""
    await ensure_system_roles(session)
    modes = await _modes(session)
    roles = (
        await session.execute(
            select(Role.id, Role.key, Role.name, Role.is_system).where(Role.deleted_at.is_(None))
        )
    ).all()
    counts = {
        row.role_id: (row.holders, row.enrolled)
        for row in await session.execute(
            select(
                UserRole.role_id,
                func.count().label("holders"),
                func.count(User.mfa_enrolled_at).label("enrolled"),
            )
            .join(User, User.id == UserRole.user_id)
            .where(User.status == "active", User.deleted_at.is_(None))
            .group_by(UserRole.role_id)
        )
    }
    order = {key: index for index, key in enumerate(SYSTEM_ROLES)}
    policies = [
        RolePolicy(
            role_id=role.id,
            key=role.key if role.is_system else None,
            name=role.name,
            mode=modes[role.id][0],
            is_default=modes[role.id][1] is None,
            holders=counts.get(role.id, (0, 0))[0],
            enrolled=counts.get(role.id, (0, 0))[1],
            version=0 if modes[role.id][1] is None else modes[role.id][1].version,  # type: ignore[union-attr]  # checked just before
        )
        for role in roles
    ]
    return sorted(
        policies, key=lambda p: (p.key is None, order.get(p.key or "", 99), p.name.lower())
    )


async def set_policy(
    session: AsyncSession,
    role_id: uuid.UUID,
    mode: str,
    *,
    expected_version: int,
) -> tuple[RolePolicy, rules.Mode]:
    """Save a role's mode (If-Match: 0 for a role still on its default); the previous mode."""
    if mode not in rules.MODES:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="mode",
                    code="mfa_mode_invalid",
                    message_key="errors.field.mfa_mode_invalid",
                )
            ]
        )
    role = await session.get(Role, role_id)
    if role is None or role.deleted_at is not None:
        raise NotFound(code="role_not_found")
    row = await session.scalar(
        select(MfaPolicy).where(MfaPolicy.role_id == role_id).with_for_update()
    )
    current = 0 if row is None else row.version
    if current != expected_version:
        if row is not None:
            raise await stale_version(session, row, expected_version=expected_version)
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current},
        )
    before = rules.default_mode(role.key if role.is_system else None) if row is None else row.mode
    context = session.info[SESSION_TENANT_KEY]
    if row is None:
        row = MfaPolicy(
            id=new_id(),
            tenant_id=context.tenant_id,
            role_id=role_id,
            mode=mode,
            version=1,
            created_by=context.user_id,
            updated_by=context.user_id,
        )
        session.add(row)
    elif row.mode != mode:
        row.mode = mode
        row.version += 1
        row.updated_by = context.user_id
    await session.flush()
    holders = list(
        await session.scalars(select(UserRole.user_id).where(UserRole.role_id == role_id))
    )
    await recompute(session, holders)
    await record_event(
        session,
        MfaChanged(change="policy", role_id=role_id),
        aggregate_id=context.tenant_id,
        aggregate_version=row.version,
    )
    found = next(p for p in await list_policies(session) if p.role_id == role_id)
    return found, before  # type: ignore[return-value]  # the column's codes


async def recompute(session: AsyncSession, user_ids: Iterable[uuid.UUID]) -> None:
    """Start or clear each person's grace period after a role or policy change."""
    now = datetime.now(UTC)
    for user_id in set(user_ids):
        person = await session.get(User, user_id)
        if person is None:
            continue
        required = await person_mode(session, user_id) == "required"
        if required and person.mfa_required_since is None:
            person.mfa_required_since = now
        elif not required and person.mfa_required_since is not None:
            person.mfa_required_since = None
    await session.flush()


async def status_of(session: AsyncSession, user_id: uuid.UUID) -> rules.MfaStatus:
    """The person's MFA status here from what SupportX knows (no Keycloak call)."""
    person = await session.get(User, user_id)
    if person is None:
        return rules.MfaStatus("off", enrolled=False, due_at=None)
    return rules.status(
        await person_mode(session, user_id),
        enrolled=person.mfa_enrolled_at is not None,
        required_since=person.mfa_required_since,
        grace_days=await grace_days(session),
    )


async def _enrolled(admin: IdentityAdmin, subject: str) -> bool | None:
    """Whether Keycloak holds the person's authenticator; None when it cannot be asked."""
    try:
        found = await admin.credentials(subject)
    except (IdentityAdminUnavailable, IdentityAdminNotConfigured):
        log.warning("mfa_credentials_unavailable")
        return None
    return any(credential.type == "otp" for credential in found)


@dataclass(frozen=True)
class Synced:
    """A person's status after `sync`, and whether Keycloak now holds their enrol actions."""

    status: rules.MfaStatus
    enforced: bool


async def sync(session: AsyncSession, admin: IdentityAdmin | None, user_id: uuid.UUID) -> Synced:
    """Refresh the person's enrolment from Keycloak, start their grace if due, enforce it.

    Called at sign-in, after the person set MFA up and by the schedule. Past the grace period
    without an authenticator, Keycloak's enrol actions are added to their account.
    """
    person = await session.get(User, user_id)
    if person is None or person.external_subject is None:
        return Synced(await status_of(session, user_id), enforced=False)
    if admin is not None:
        enrolled = await _enrolled(admin, person.external_subject)
        if enrolled is not None:
            person.mfa_enrolled_at = (
                (person.mfa_enrolled_at or datetime.now(UTC)) if enrolled else None
            )
    await recompute(session, [user_id])
    found = await status_of(session, user_id)
    if not found.must_enrol(datetime.now(UTC)) or admin is None:
        return Synced(found, enforced=False)
    try:
        await admin.require_actions(person.external_subject, list(rules.ENROL_ACTIONS))
    except (IdentityAdminUnavailable, IdentityAdminNotConfigured):
        log.warning("mfa_enrol_actions_unavailable")
        return Synced(found, enforced=False)
    return Synced(found, enforced=True)


async def on_sign_in(
    database: Database,
    admin: IdentityAdmin | None,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Synced:
    """The sign-in's MFA check (its own transaction): status, and enforcement when overdue."""
    async with database.tenant_session(TenantContext(tenant_id, user_id)) as session:
        return await sync(session, admin, user_id)


async def enforce_overdue(session: AsyncSession, admin: IdentityAdmin | None) -> int:
    """Schedule: add the enrol actions for everyone here past their grace period (count)."""
    if admin is None:
        return 0
    days = await grace_days(session)
    rows = await session.scalars(
        select(User).where(
            User.mfa_required_since.is_not(None),
            User.mfa_enrolled_at.is_(None),
            User.status == "active",
            User.external_subject.is_not(None),
        )
    )
    now = datetime.now(UTC)
    count = 0
    for person in rows:
        found = rules.status(
            "required",
            enrolled=False,
            required_since=person.mfa_required_since,
            grace_days=days,
        )
        if found.must_enrol(now):
            await admin.require_actions(person.external_subject or "", list(rules.ENROL_ACTIONS))
            count += 1
    return count


async def reset(
    session: AsyncSession,
    admin: IdentityAdmin | None,
    user_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
) -> User:
    """Remove the person's authenticator and recovery codes (REQ-SEC-025); never one's own."""
    if user_id == actor_id:
        raise PermissionDenied(code="mfa_reset_own")
    if admin is None:
        raise IdentityAdminNotConfigured
    person = await session.get(User, user_id)
    if person is None or person.deleted_at is not None:
        raise NotFound(code="user_not_found")
    if person.external_subject is None:
        raise Conflict(code="mfa_reset_not_signed_in")
    for credential in await admin.credentials(person.external_subject):
        if credential.type in rules.MFA_CREDENTIALS:
            await admin.delete_credential(person.external_subject, credential.id)
    person.mfa_enrolled_at = None
    if await person_mode(session, user_id) == "required":
        # They had their grace period: enrolling again comes at once, at their next sign-in.
        await admin.require_actions(person.external_subject, list(rules.ENROL_ACTIONS))
    await session.flush()
    context = session.info[SESSION_TENANT_KEY]
    await record_event(
        session,
        MfaChanged(change="reset", user_id=user_id),
        aggregate_id=context.tenant_id,
        aggregate_version=person.version,
    )
    return person


async def notify_reset(session: AsyncSession, settings: Settings, person: User) -> bool:
    """Tell the person their MFA was reset (REQ-SEC-025 AC2), in their language; False if no mail.

    The notice names no admin and carries no link: the person signs in as usual and sets MFA up
    again. Without outgoing mail the reset still stands (the audit entry records it).
    """
    if not person.email or not mail_configured(settings):
        log.warning("mfa_reset_notice_not_sent", reason="no_mail" if person.email else "no_email")
        return False
    language = _language(person.ui_locale or person.locale)
    context = session.info[SESSION_TENANT_KEY]
    brand = await email_branding(session, settings, context.tenant_id, language)
    tenant = await get_current_tenant(session)
    # Mail: no directional marks in the subject or plain text; <bdi> in the HTML part.
    subject = plain_label("mail.mfa_reset.subject", language)
    body = plain_label("mail.mfa_reset.body", language, organisation=tenant.name)
    body_html = html_label("mail.mfa_reset.body", language, organisation=tenant.name)
    await queue_mail(
        session,
        settings,
        OutgoingMail(
            kind="mfa_reset",
            to=(person.email,),
            language=language,
            subject=subject,
            text=body,
            html=wrap_html(
                Markup("<p>{}</p>").format(body_html), brand=brand, language=language, title=subject
            ),
            sender_name=tenant.name,
        ),
    )
    return True


def _language(locale: str | None) -> Language:
    found = (locale or "en").split("-")[0]
    return found if found in LANGUAGES else "en"  # type: ignore[return-value]  # one of LANGUAGES


async def enforce_schedule(database: Database, settings: Settings) -> None:
    """Hourly: in every tenant, people past their grace period get Keycloak's enrol actions."""
    admin = KeycloakAdmin.from_settings(settings)
    if admin is None:
        return
    try:
        async with database.platform_session() as platform:
            tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
        for tenant in tenants:
            async with database.tenant_session(TenantContext(tenant)) as session:
                count = await enforce_overdue(session, admin)
            if count:
                log.info("mfa_enrolment_enforced", tenant_id=str(tenant), people=count)
    except (IdentityAdminUnavailable, IdentityAdminNotConfigured):
        log.warning("mfa_enforcement_unavailable")
    finally:
        await admin.close()


async def on_roles_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: a role assigned or removed starts or clears the person's grace period."""
    assert session is not None  # noqa: S101 - transactional consumer
    await recompute(session, [uuid.UUID(str(envelope.payload["user_id"]))])


MFA_ROLES = ConsumerSpec(
    name="identity_access__mfa_roles",
    event_types=("identity_access.user_role.changed", "identity_access.user.created"),
    handler=on_roles_changed,
)
