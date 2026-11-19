"""Vendor support grants (WP-057 S4c-1, REQ-SEC-045, D-173): reading, the opt-out and the end.

A tenant admin grants one named Extravis engineer temporary access; the grant makes a temporary
`vendor_support` account in the shared realm, at a plus-address of the engineer's own
(`domain.support_grants.account_email`). This part holds what does not depend on how the engineer
gets in (`delivery_for`, which waits for the product owner's item 14):

- the grants a tenant admin sees, newest first, with "waiting for the engineer" until the engineer
  completes Keycloak's required actions (lane B (12)): never "active" before;
- the "Never allow vendor support" setting (D-173 (9)); turning it on refuses while a grant is
  open, so an admin ends those first and sees which;
- the end of a grant (expiry, revoke): the grant and the local account change in one
  transaction; then, after the commit, every session ends (the session store's marker and
  Centrifugo, ADR-051) and the Keycloak account is disabled, then deleted (lane B (5)). The grant
  row and its audit stay; the account and its plus-address are gone.

Only tenant admins: grants are a tenant-admin decision (D-173 (1)), so `identity.manage` alone is
not enough.
"""

import ipaddress
import secrets
import string
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.core.logging import get_logger
from app.modules.identity_access.domain import support_grants as rules
from app.modules.identity_access.domain.permissions import TENANT_ADMIN
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.events import SupportGrantChanged, VendorSupportSettingChanged
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminNotConfigured,
    IdentityAdminRefused,
    IdentityAdminUnavailable,
)
from app.modules.identity_access.infra.models import (
    IdentitySettings,
    Role,
    SupportGrant,
    User,
    UserRole,
)
from app.modules.identity_access.service.directory import UserRepository
from app.modules.identity_access.service.sso import organization_of
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.ids import new_id
from app.shared.mail.service.outgoing import mail_configured

log = get_logger(__name__)

GRANT_RECORD_TYPE = "support_grant"

# `end(tenant_id, user_id)`: the session store's ended marker and the realtime disconnect
# (service/worker_sessions.py); None where sessions are not configured (tests, dev).
SessionEnder = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]


@dataclass(frozen=True)
class GrantView:
    """A grant as a tenant admin sees it. The engineer's address is theirs to see (D-173 (2))."""

    id: uuid.UUID
    engineer_name: str
    engineer_email: str
    reason: str
    ticket_ref: str | None
    access: str
    change_reason: str | None
    unmask_personal: bool
    ip_allowlist: list[str]
    starts_at: datetime
    ends_at: datetime
    state: str  # pending_verification reads "waiting for the engineer" (lane B (12))
    verification: str
    first_used_at: datetime | None
    ended_at: datetime | None
    version: int


def _view(row: SupportGrant) -> GrantView:
    return GrantView(
        id=row.id,
        engineer_name=row.engineer_name,
        engineer_email=row.engineer_email,
        reason=row.reason,
        ticket_ref=row.ticket_ref,
        access=row.access,
        change_reason=row.change_reason,
        unmask_personal=row.unmask_personal,
        ip_allowlist=[str(n) for n in row.ip_allowlist],
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        state=row.state,
        verification=row.verification,
        first_used_at=row.first_used_at,
        ended_at=row.ended_at,
        version=row.version,
    )


async def require_tenant_admin(session: AsyncSession, subject: Subject) -> None:
    """A tenant admin, by their own role (a group's or a custom role's rights are not enough)."""
    found = await session.scalar(
        select(Role.id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == subject.user_id,
            Role.key == TENANT_ADMIN,
            Role.deleted_at.is_(None),
        )
        .limit(1)
    )
    if found is None:
        raise PermissionDenied(code="vendor_support_tenant_admin_only")


async def list_grants(
    session: AsyncSession, subject: Subject, *, limit: int = 200
) -> list[GrantView]:
    """Every grant of the tenant, open ones first, then newest first."""
    await require_tenant_admin(session, subject)
    open_first = SupportGrant.state.in_([s.value for s in rules.OPEN_STATES])
    rows = await session.scalars(
        select(SupportGrant)
        .order_by(open_first.desc(), SupportGrant.created_at.desc(), SupportGrant.id)
        .limit(limit)
    )
    return [_view(r) for r in rows]


async def get_grant(session: AsyncSession, subject: Subject, grant_id: uuid.UUID) -> GrantView:
    """One grant, or 404."""
    await require_tenant_admin(session, subject)
    row = await session.get(SupportGrant, grant_id)
    if row is None:
        raise NotFound(code="support_grant_not_found")
    return _view(row)


async def open_grants(session: AsyncSession) -> int:
    """How many grants still count (waiting for the engineer, or in use)."""
    count = await session.scalar(
        select(func.count())
        .select_from(SupportGrant)
        .where(SupportGrant.state.in_([s.value for s in rules.OPEN_STATES]))
    )
    return int(count or 0)


async def never_allowed(session: AsyncSession) -> bool:
    """The tenant's opt-out (D-173 (9)); no settings row yet means allowed."""
    found = await session.scalar(select(IdentitySettings.never_allow_vendor_support).limit(1))
    return bool(found)


async def set_never_allow(
    session: AsyncSession,
    subject: Subject,
    *,
    never_allow: bool,
    expected_version: int,
) -> int:
    """Turn the opt-out on or off; the settings' new version. Refused on while grants are open.

    The same row and version as the other sign-in settings (no row yet is version 0, as
    `get_identity_settings` reads it), written the same way: an upsert that only lands on the
    version read. The route records the audit entry; the event tells every tenant admin.
    """
    await require_tenant_admin(session, subject)
    current = await session.scalar(select(IdentitySettings).with_for_update())
    version = 0 if current is None else current.version
    if version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": version},
        )
    if current is not None and current.never_allow_vendor_support == never_allow:
        return version
    if current is None and not never_allow:
        return version  # the default already
    if never_allow and await open_grants(session):
        raise Conflict(code="vendor_support_grants_open")
    context = session.info[SESSION_TENANT_KEY]
    saved = await session.scalar(
        insert(IdentitySettings)
        .values(
            tenant_id=context.tenant_id,
            created_by=subject.user_id,
            updated_by=subject.user_id,
            version=1,
            never_allow_vendor_support=never_allow,
        )
        .on_conflict_do_update(
            index_elements=[IdentitySettings.tenant_id],
            set_={
                "never_allow_vendor_support": never_allow,
                "updated_by": subject.user_id,
                "updated_at": func.now(),
                "version": IdentitySettings.version + 1,
            },
            where=IdentitySettings.version == expected_version,
        )
        .returning(IdentitySettings.version)
    )
    if saved is None:  # changed by someone else between the read and the write
        raise Conflict(code="version_conflict", params={"expected_version": expected_version})
    new_version = int(saved)
    await record_event(
        session,
        VendorSupportSettingChanged(never_allow=never_allow),
        aggregate_id=context.tenant_id,
        aggregate_version=new_version,
    )
    return new_version


@dataclass(frozen=True)
class Ended:
    """A grant just ended in the database: what the after-commit steps need."""

    grant_id: uuid.UUID
    tenant_id: uuid.UUID
    support_user_id: uuid.UUID | None
    keycloak_id: str | None


async def end_grant(  # noqa: PLR0913 - the grant, how it ends and who ends it, keyword-only
    session: AsyncSession,
    grant_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
    revoked_by: uuid.UUID | None,
    now: datetime,
    source: Source,
) -> Ended | None:
    """End an open grant in this transaction (revoked by an admin, or its time is up).

    The local account is disabled with it, so the database refuses a sign-in at once; the
    sessions and the Keycloak account go after the commit (`finish_end`). None when the grant was
    not open (already ended: idempotent, as the schedule and an admin may race).
    """
    row = await session.scalar(
        select(SupportGrant).where(SupportGrant.id == grant_id).with_for_update()
    )
    if row is None or not rules.is_open(row.state):
        return None
    before = row.state
    row.state = (rules.GrantState.REVOKED if revoked_by else rules.GrantState.ENDED).value
    row.ended_at = now
    row.ended_by = revoked_by
    row.version += 1
    keycloak_id: str | None = None
    if row.support_user_id is not None:
        account = await session.get(User, row.support_user_id)
        if account is not None:
            keycloak_id = account.external_subject
            await session.execute(
                update(User)
                .where(User.id == account.id)
                .values(status="disabled", can_sign_in=False, version=User.version + 1)
            )
    if keycloak_id is None:
        row.account_removed_at = now  # no Keycloak account was ever made: nothing to remove
    await session.flush()
    await record_changes(
        session,
        record_type=GRANT_RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="updated",
        changes=[Change("state", before, row.state)],
        source=source,
    )
    await record_event(
        session,
        SupportGrantChanged(
            grant_id=row.id,
            change="revoked" if revoked_by else "ended",
            access=rules.Access(row.access).value,
            ends_at=row.ends_at,
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return Ended(row.id, tenant_id, row.support_user_id, keycloak_id)


async def finish_end(
    ended: Ended, *, end_sessions: SessionEnder | None, admin: IdentityAdmin | None
) -> str | None:
    """After the commit: end every session, then disable and delete the Keycloak account.

    The error class of the first failed disable or delete, or None once Keycloak confirmed the
    account gone (deleted, or already 404). A failure never counts as done (lane B): the caller
    records it (`record_removal`) and the sweep tries again. Each step runs on its own; a failed
    logout alone stays best effort, as disable and delete end the sessions anyway.
    """
    if end_sessions is not None and ended.support_user_id is not None:
        try:
            await end_sessions(ended.tenant_id, ended.support_user_id)
        except Exception:  # noqa: BLE001 - any failure here is logged; the next step still runs
            log.warning("support_grant_sessions_end_failed", grant_id=str(ended.grant_id))
    if ended.keycloak_id is None:
        return None
    if admin is None:
        return "IdentityAdminNotConfigured"
    account = ended.keycloak_id
    failed: str | None = None
    steps: tuple[tuple[str, Callable[[], Awaitable[None]]], ...] = (
        ("logout", lambda: admin.logout_user(account)),
        ("disable", lambda: admin.set_enabled(account, enabled=False)),
        ("delete", lambda: admin.delete_user(account)),
    )
    for name, step in steps:
        try:
            await step()
        except (IdentityAdminRefused, IdentityAdminUnavailable) as exc:
            log.warning(
                "support_grant_account_step_failed", step=name, grant_id=str(ended.grant_id)
            )
            if name != "logout" and failed is None:
                failed = type(exc).__name__
    return failed


async def record_removal(
    session: AsyncSession, grant_id: uuid.UUID, *, error: str | None, now: datetime
) -> None:
    """Record how the account's removal went: removed once confirmed, or the failure (audited).

    A failure leaves `account_removed_at` empty, so the grant shows "removing the account" and the
    sweep (`removal_pending`) tries again; it also moves `updated_at`, which spaces the retries.
    """
    row = await session.scalar(
        select(SupportGrant).where(SupportGrant.id == grant_id).with_for_update()
    )
    if row is None or row.account_removed_at is not None:
        return
    row.updated_at = now
    if error is None:
        row.account_removed_at = now
        row.version += 1
    await session.flush()
    await record_event(
        session,
        SupportGrantChanged(
            grant_id=row.id,
            change="account_removed" if error is None else "account_removal_failed",
            access=rules.Access(row.access).value,
            ends_at=row.ends_at,
            error_class=error,
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


RETRY_AFTER = timedelta(minutes=5)


async def removal_pending(session: AsyncSession, now: datetime) -> list[Ended]:
    """Ended grants whose Keycloak account is not confirmed gone, last tried 5+ minutes ago."""
    rows = (
        await session.execute(
            select(SupportGrant.id, SupportGrant.tenant_id, User.id, User.external_subject)
            .join(User, User.id == SupportGrant.support_user_id)
            .where(
                SupportGrant.state.not_in([s.value for s in rules.OPEN_STATES]),
                SupportGrant.account_removed_at.is_(None),
                SupportGrant.updated_at <= now - RETRY_AFTER,
            )
        )
    ).all()
    return [Ended(g, t, u, k) for g, t, u, k in rows]


STUCK_AFTER = timedelta(hours=24)


async def stuck_removals(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """Grants ended over 24 hours ago whose account is still not confirmed gone (S4d's flag)."""
    rows = await session.scalars(
        select(SupportGrant.id).where(
            SupportGrant.state.not_in([s.value for s in rules.OPEN_STATES]),
            SupportGrant.account_removed_at.is_(None),
            SupportGrant.ended_at <= now - STUCK_AFTER,
        )
    )
    return list(rows)


async def mark_alerted(session: AsyncSession, grant_id: uuid.UUID, now: datetime) -> bool:
    """Claim the one notice for a stuck removal; False when it was already sent."""
    claimed = await session.scalar(
        update(SupportGrant)
        .where(SupportGrant.id == grant_id, SupportGrant.removal_alerted_at.is_(None))
        .values(removal_alerted_at=now)
        .returning(SupportGrant.id)
    )
    return claimed is not None


async def due(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """Open grants whose time is up, for the 30-second schedule."""
    rows = await session.scalars(
        select(SupportGrant.id).where(
            SupportGrant.state.in_([s.value for s in rules.OPEN_STATES]),
            SupportGrant.ends_at <= now,
        )
    )
    return list(rows)


# --- making a grant ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Made:
    """A new grant, how the engineer gets in, and the one-time password when the admin passes it.

    The password is shown once in the console (D-173) and is never logged, stored or e-mailed;
    it exists only on the out-of-band path (lane B (11)). `admin_could_act` is shown on the grant
    and recorded in the audit, so a review can tell which grants an admin could have used.
    """

    grant: GrantView
    delivery: rules.Delivery
    admin_could_act: bool
    one_time_password: str | None = field(default=None, repr=False)


def _one_time_password() -> str:
    """A password that meets any realm policy we set: 24 characters, every class, random."""
    alphabet = string.ascii_letters + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(20))
    return (
        body
        + secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.ascii_lowercase)
        + secrets.choice(string.digits)
        + secrets.choice("!#%+-=?@^_")
    )


def _networks(given: Sequence[str]) -> list[str]:
    """The IP list as normalised CIDRs; a bad entry is a 422 naming it."""
    out: list[str] = []
    for entry in given:
        try:
            out.append(str(ipaddress.ip_network(entry.strip(), strict=False)))
        except ValueError as exc:
            raise ValidationFailed(
                errors=[
                    FieldError(
                        field="body.ip_allowlist",
                        code="invalid_network",
                        message_key="errors.field.invalid_network",
                        params={"value": entry[:64]},
                    )
                ]
            ) from exc
    return out


def _refuse(problems: list[tuple[str, str]]) -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(field=f"body.{f}", code=c, message_key=f"errors.field.{c}")
            for f, c in problems
        ]
    )


async def create_grant(  # noqa: PLR0913 - the request, its context and the account port
    session: AsyncSession,
    subject: Subject,
    request: rules.GrantRequest,
    *,
    settings: Settings,
    admin: IdentityAdmin | None,
    now: datetime,
    source: Source,
) -> Made:
    """Make a grant and its temporary account; refused unless every D-173 rule holds.

    Order: every check, then the grant row (its UUIDv7 names the account), then the Keycloak
    account; if Keycloak fails after the account exists, the account is deleted again and the
    transaction rolls back, so no half-made grant remains.
    """
    await require_tenant_admin(session, subject)
    problems = rules.grant_problems(
        request,
        allowed_domains=settings.vendor_support_email_domains,
        open_grants=await open_grants(session),
        opted_out=await never_allowed(session),
    )
    if problems:
        raise _refuse(problems)
    delivery = rules.delivery_for(request.verification, mail_available=mail_configured(settings))
    if delivery is None:
        raise Conflict(code=rules.PENDING_DECISION)
    if admin is None:
        raise IdentityAdminNotConfigured
    networks = _networks(request.ip_allowlist)
    starts_at, ends_at = rules.window(now, request.hours)
    grant_id = new_id()
    address = rules.account_email(request.engineer_email, grant_id)
    if address is None:  # grant_problems refused it already; kept for the type checker
        raise _refuse([("engineer_email", "support_email_not_taggable")])
    out_of_band = request.verification is rules.Verification.OUT_OF_BAND
    row = SupportGrant(
        id=grant_id,
        engineer_name=request.engineer_name.strip(),
        engineer_email=request.engineer_email.strip().lower(),
        reason=request.reason.strip(),
        ticket_ref=(request.ticket_ref or "").strip() or None,
        access=request.access.value,
        change_reason=(request.change_reason or "").strip() or None
        if request.access is rules.Access.VIEW_AND_CHANGE
        else None,
        unmask_personal=request.unmask_personal,
        ip_allowlist=networks,
        starts_at=starts_at,
        ends_at=ends_at,
        state=rules.GrantState.PENDING_VERIFICATION.value,
        verification=request.verification.value,
        confirmed_by=subject.user_id if out_of_band else None,
        confirmation_note=(request.confirmation_note or "").strip() or None
        if out_of_band
        else None,
        created_by=subject.user_id,
        updated_by=subject.user_id,
    )
    session.add(row)
    await session.flush()
    organization = await organization_of(session, admin)
    account = await admin.create_user(
        email=address,
        first_name=row.engineer_name[:100],
        last_name="",
        locale="en",
        email_verified=out_of_band,  # never proven by mail on that path; the warning says so
    )
    password: str | None = None
    try:
        await admin.add_member(organization.id, account)
        actions = list(rules.actions_for(request.verification))
        if delivery is rules.Delivery.ACTIONS_EMAIL:
            await admin.send_actions_email(
                account, actions, rules.link_lifespan_seconds(now, ends_at)
            )
        else:
            password = _one_time_password()
            await admin.set_password(account, password)
            await admin.require_actions(account, actions)
        person = await UserRepository(session).add(
            User(
                external_subject=account,
                email=address,
                display_name=row.engineer_name[:100],
                first_name=row.engineer_name[:100],
                user_type=rules.SUPPORT_USER_TYPE,
                can_sign_in=True,
                roles_mapped_at=now,  # SupportX's roles only, never Keycloak's (as S4a)
            )
        )
        row.support_user_id = person.id
        await session.flush()
    except Exception:
        try:
            await admin.delete_user(account)
        except (IdentityAdminRefused, IdentityAdminUnavailable):
            log.warning("support_grant_account_cleanup_failed", grant_id=str(grant_id))
        raise
    await record_changes(
        session,
        record_type=GRANT_RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="created",
        changes=[
            Change("state", None, row.state),
            Change("access", None, row.access),
            Change("verification", None, row.verification),
        ],
        source=source,
    )
    await record_event(
        session,
        SupportGrantChanged(
            grant_id=row.id,
            change="created",
            access=rules.Access(row.access).value,
            ends_at=row.ends_at,
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return Made(
        grant=_view(row),
        delivery=delivery,
        admin_could_act=rules.admin_could_act_as_engineer(delivery),
        one_time_password=password,
    )


async def extend_grant(  # noqa: PLR0913 - the grant, its version, the hours and context
    session: AsyncSession,
    subject: Subject,
    grant_id: uuid.UUID,
    *,
    expected_version: int,
    extra_hours: int,
    source: Source,
) -> GrantView:
    """Move an open grant's end later, never past 72 hours from its start (D-173 (3)).

    The route asks for a recent sign-in (lane B); every admin is told through the event.
    """
    await require_tenant_admin(session, subject)
    row = await session.scalar(
        select(SupportGrant).where(SupportGrant.id == grant_id).with_for_update()
    )
    if row is None:
        raise NotFound(code="support_grant_not_found")
    if row.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": row.version},
        )
    if not rules.is_open(row.state):
        raise Conflict(code="support_grant_not_open")
    new_end = rules.extended_end(row.starts_at, row.ends_at, extra_hours)
    if new_end is None:
        raise _refuse([("hours", "support_grant_length")])
    before = row.ends_at
    row.ends_at = new_end
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await record_changes(
        session,
        record_type=GRANT_RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="updated",
        changes=[Change("ends_at", before.isoformat(), new_end.isoformat())],
        source=source,
    )
    await record_event(
        session,
        SupportGrantChanged(
            grant_id=row.id,
            change="extended",
            access=rules.Access(row.access).value,
            ends_at=row.ends_at,
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return _view(row)
