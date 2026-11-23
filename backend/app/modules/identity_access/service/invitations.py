"""Invitations to sign in (WP-039 session 2; REQ-SEC-018, 019, 020; D-099).

An admin invites a person the tenant knows (added by hand or imported, WP-021) who has not signed
in yet. Keycloak sends the e-mail (D-099): SupportX makes sure the person has a Keycloak account
without a password and is a member of the tenant's organization, puts the tenant's brand and
the person's language on it, and asks Keycloak for its set-password e-mail, valid as long as the
invitation (`invitation_valid_days`, 7 by default, at most 30). The e-mail comes from the
installation's sender with the tenant's name; it never names the inviting admin or their address
(REQ-SEC-019). SupportX keeps the life cycle:

- **pending** until the person's first sign-in, which marks it **accepted** (users.py);
- **expired** (computed): pending past `expires_at`; the link no longer works (Keycloak refuses
  an expired or used link, single use, proved on 26.8.1);
- **revoked** by an admin: an account SupportX made for the invitation and never used is
  deleted, so the link stops at once (AC2); otherwise the person leaves the organization;
- **resent**: a new e-mail and a new expiry. The earlier link stops when the account was made for
  the invitation (made afresh); for an account that existed before, Keycloak cannot withdraw it,
  so it works until it expires and the screen says so (`earlier_links_work`).

Someone who already has a Keycloak password (a person of another tenant) gets the membership
and no e-mail: they sign in as they are used to (`delivery = existing_account`).
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.identity_access.domain import invite_link
from app.modules.identity_access.domain.password_policy import PasswordPolicy
from app.modules.identity_access.events import InvitationChanged, InvitationLinkCopied
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminNotConfigured,
    IdentityAdminRefused,
)
from app.modules.identity_access.infra.models import Invitation, User
from app.modules.identity_access.service.identity_settings import get_identity_settings
from app.modules.identity_access.service.sso import organization_of
from app.modules.organization import email_branding, get_current_tenant
from app.shared.events import record_event
from app.shared.history import stale_version
from app.shared.ids import new_id
from app.shared.mail import mail_configured

Status = Literal["pending", "accepted", "expired", "revoked"]
SET_PASSWORD = "UPDATE_PASSWORD"  # noqa: S105 - the name of a Keycloak required action, not a secret


@dataclass(frozen=True)
class InvitationView:
    """An invitation as the admin screen shows it."""

    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    status: Status
    delivery: str
    sent_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    sends: int
    # Links e-mailed earlier still work until they expire: Keycloak cannot withdraw one link
    # (proved on 26.8.1, even after ending the user's sessions), and only an account this
    # invitation made can be made afresh. The screen says so (product owner, 2026-10-28).
    earlier_links_work: bool
    version: int


def _status(row: Invitation, now: datetime) -> Status:
    if row.status == "pending" and row.expires_at <= now:
        return "expired"
    return row.status  # type: ignore[return-value]  # the column holds only these codes


def _view(row: Invitation, now: datetime | None = None) -> InvitationView:
    return InvitationView(
        id=row.id,
        user_id=row.user_id,
        email=row.email,
        status=_status(row, now or datetime.now(UTC)),
        delivery=row.delivery,
        sent_at=row.sent_at,
        expires_at=row.expires_at,
        accepted_at=row.accepted_at,
        sends=row.sends,
        earlier_links_work=row.sends > 1 and row.delivery == "email" and not row.created_account,
        version=row.version,
    )


def _require(admin: IdentityAdmin | None) -> IdentityAdmin:
    if admin is None:
        raise IdentityAdminNotConfigured
    return admin


async def _invitee(session: AsyncSession, user_id: uuid.UUID) -> User:
    person = await session.get(User, user_id)
    if person is None or person.deleted_at is not None:
        raise NotFound(code="user_not_found")
    if not person.email:
        raise Conflict(code="invitation_needs_email")
    if person.external_subject is not None:
        raise Conflict(code="invitation_already_signed_in")
    if person.status != "active" or not person.can_sign_in:
        raise Conflict(code="invitation_person_cannot_sign_in")
    return person


async def _brand(
    session: AsyncSession, settings: Settings, admin: IdentityAdmin, account: str, person: User
) -> None:
    """The tenant's brand and the person's language on the account, for Keycloak's e-mail."""
    context = session.info[SESSION_TENANT_KEY]
    locale = person.ui_locale or person.locale
    brand = await email_branding(session, settings, context.tenant_id, locale)
    tenant = await get_current_tenant(session)
    await admin.set_attributes(
        account,
        {
            "locale": locale,
            "sx_mail_kind": "invitation",
            "sx_brand_name": tenant.name,
            "sx_brand_logo": brand.logo_url or "",
            "sx_brand_colour": brand.primary_colour,
        },
    )


async def _deliver(  # noqa: PLR0913 - the person and how to reach them, keyword-only rest
    session: AsyncSession,
    settings: Settings,
    admin: IdentityAdmin,
    person: User,
    *,
    valid_days: int,
    send: bool = True,
) -> tuple[str, bool, str]:
    """(Keycloak account, whether SupportX created it, delivery) after sending or linking.

    `send` False (no outgoing mail set up, REQ-SEC-021): the account is made and joined to the
    organization, and no e-mail goes; an admin copies a single-use link instead (`link`).
    """
    organization = await organization_of(session, admin)
    found = await admin.find_user(person.email or "")
    created = found is None
    if found is None:
        account = await admin.create_user(
            email=person.email or "",
            first_name=person.first_name,
            last_name=person.last_name or "",
            locale=person.ui_locale or person.locale,
            # A copied link reaches no mailbox: the address stays unproven (lane B).
            email_verified=send,
        )
    else:
        account = found.id
    await admin.add_member(organization.id, account)
    if found is not None and found.has_password:
        return account, created, "existing_account"
    if not send:
        return account, created, "link"
    await _brand(session, settings, admin, account, person)
    await admin.send_actions_email(account, [SET_PASSWORD], valid_days * 86400)
    return account, created, "email"


async def invite(
    session: AsyncSession, settings: Settings, admin: IdentityAdmin | None, user_id: uuid.UUID
) -> InvitationView:
    """Invite a person who has not signed in yet (one pending invitation per person)."""
    keycloak = _require(admin)
    person = await _invitee(session, user_id)
    pending = await session.scalar(
        select(Invitation.id).where(Invitation.user_id == user_id, Invitation.status == "pending")
    )
    if pending is not None:
        raise Conflict(code="invitation_pending", params={"invitation_id": str(pending)})
    valid_days = (await get_identity_settings(session)).invitation_valid_days
    account, created, delivery = await _deliver(
        session, settings, keycloak, person, valid_days=valid_days, send=mail_configured(settings)
    )
    now = datetime.now(UTC)
    context = session.info[SESSION_TENANT_KEY]
    row = Invitation(
        id=new_id(),
        tenant_id=context.tenant_id,
        user_id=user_id,
        email=person.email or "",
        status="pending",
        delivery=delivery,
        keycloak_user_id=account,
        created_account=created,
        sent_at=now,
        expires_at=now + timedelta(days=valid_days),
        sends=1,
        version=1,
    )
    session.add(row)
    await session.flush()
    await _changed(session, row, "sent")
    return _view(row, now)


async def _row(
    session: AsyncSession, invitation_id: uuid.UUID, expected_version: int
) -> Invitation:
    row = await session.scalar(
        select(Invitation).where(Invitation.id == invitation_id).with_for_update()
    )
    if row is None:
        raise NotFound(code="invitation_not_found")
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    return row


async def resend(
    session: AsyncSession,
    settings: Settings,
    admin: IdentityAdmin | None,
    invitation_id: uuid.UUID,
    *,
    expected_version: int,
) -> InvitationView:
    """A new e-mail and a new expiry for a pending or expired invitation."""
    keycloak = _require(admin)
    row = await _row(session, invitation_id, expected_version)
    if row.status != "pending":
        raise Conflict(code="invitation_not_pending")
    person = await _invitee(session, row.user_id)
    valid_days = (await get_identity_settings(session)).invitation_valid_days
    # Keycloak cannot withdraw one link, so an account this invitation made and nobody has used
    # is made afresh: the earlier e-mail's link then names an account that no longer exists and
    # stops working (QA WP-039 BUG-01). An account that existed before keeps its earlier links
    # until they expire (it is not ours to delete).
    if row.created_account and row.keycloak_user_id is not None:
        found = await keycloak.find_user(row.email)
        if found is not None and found.id == row.keycloak_user_id and not found.has_password:
            await keycloak.delete_user(row.keycloak_user_id)
    account, created, delivery = await _deliver(
        session, settings, keycloak, person, valid_days=valid_days, send=mail_configured(settings)
    )
    now = datetime.now(UTC)
    row.link_token_hash = None  # a resend ends any copied link
    row.keycloak_user_id = account
    row.created_account = row.created_account or created
    row.delivery = delivery
    row.sent_at, row.expires_at = now, now + timedelta(days=valid_days)
    row.sends += 1
    row.version += 1
    await session.flush()
    await _changed(session, row, "resent")
    return _view(row, now)


async def revoke(
    session: AsyncSession,
    admin: IdentityAdmin | None,
    invitation_id: uuid.UUID,
    *,
    expected_version: int,
) -> InvitationView:
    """Stop the invitation's link at once (AC2); see the module docstring."""
    keycloak = _require(admin)
    row = await _row(session, invitation_id, expected_version)
    if row.status != "pending":
        raise Conflict(code="invitation_not_pending")
    if row.keycloak_user_id is not None:
        found = await keycloak.find_user(row.email)
        unused = found is not None and found.id == row.keycloak_user_id and not found.has_password
        if row.created_account and unused:
            await keycloak.delete_user(row.keycloak_user_id)
        else:
            organization = await organization_of(session, keycloak)
            await keycloak.remove_member(organization.id, row.keycloak_user_id)
    row.status = "revoked"
    row.revoked_at = datetime.now(UTC)
    row.link_token_hash = None  # a copied link dies with it (lane B)
    row.version += 1
    await session.flush()
    await _changed(session, row, "revoked")
    return _view(row)


LIST_LIMIT = 200


async def list_invitations(
    session: AsyncSession, *, user_id: uuid.UUID | None = None
) -> list[InvitationView]:
    """The tenant's newest invitations, or one person's, newest first."""
    query = select(Invitation).order_by(Invitation.created_at.desc()).limit(LIST_LIMIT)
    if user_id is not None:
        query = query.where(Invitation.user_id == user_id)
    rows = await session.scalars(query)
    now = datetime.now(UTC)
    return [_view(row, now) for row in rows]


async def mark_accepted(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    """The person signed in for the first time: their pending invitation is accepted (AC3)."""
    row = await session.scalar(
        select(Invitation).where(Invitation.user_id == user_id, Invitation.status == "pending")
    )
    if row is None:
        return
    row.status, row.accepted_at = "accepted", now
    row.link_token_hash = None  # single use
    row.version += 1
    await session.flush()
    await _changed(session, row, "accepted")


LINK_TOKEN_BYTES = 32
LINK_MAX_AGE = timedelta(days=7)
INVITE_PAGE = "invite"  # the set-password page, in the console and the portal


@dataclass(frozen=True)
class CopiedLink:
    """A copied invite link's token (shown once, never stored) and when it stops working."""

    token: str
    expires_at: datetime
    link: str  # a technician's opens the console; anyone else's, the portal


def link_token_hash(token: str) -> bytes:
    """What is stored and looked up: the SHA-256 of the token's text, never the token."""
    return hashlib.sha256(token.encode("ascii")).digest()


async def copy_link(
    session: AsyncSession,
    settings: Settings,
    invitation_id: uuid.UUID,
    *,
    expected_version: int,
    now: datetime,
) -> CopiedLink:
    """A new single-use link for a pending invitation, for when no mail is set up (REQ-SEC-021).

    Each copy replaces the last (earlier copies stop working). The link works until the
    invitation expires, at most LINK_MAX_AGE from this copy (lane B).
    """
    if mail_configured(settings):
        raise Conflict(code="invite_link_mail_configured")
    row = await _row(session, invitation_id, expected_version)
    if row.status != "pending" or row.expires_at <= now:
        raise Conflict(code="invitation_not_pending")
    if row.delivery == "existing_account":
        raise Conflict(code="invite_link_has_account")  # they sign in as they are used to
    token = secrets.token_urlsafe(LINK_TOKEN_BYTES)  # 32 random bytes
    row.link_token_hash = link_token_hash(token)
    row.link_copied_at = now
    row.expires_at = min(row.expires_at, now + LINK_MAX_AGE)
    row.version += 1
    await session.flush()
    await record_event(
        session, InvitationLinkCopied(), aggregate_id=row.id, aggregate_version=row.version
    )
    person = await session.get(User, row.user_id)
    for_console = person is not None and person.user_type == "technician"
    # The tenant's own address, as e-mailed links use; where no subdomain names the tenant, `t`
    # does (D-132). The token goes in the fragment only, which a browser never sends.
    brand = await email_branding(
        session, settings, session.info[SESSION_TENANT_KEY].tenant_id, "en"
    )
    base = brand.console_url if for_console else brand.portal_url
    tenant = "" if settings.tenant_base_domain else f"?t={quote(brand.tenant_slug)}"
    return CopiedLink(token, row.expires_at, f"{base}{INVITE_PAGE}{tenant}#{token}")


async def clear_links(session: AsyncSession, user_id: uuid.UUID) -> None:
    """The person's copied invite links stop working (deactivated, sign-in stopped)."""
    await session.execute(
        update(Invitation)
        .where(Invitation.user_id == user_id, Invitation.link_token_hash.is_not(None))
        .values(link_token_hash=None, updated_at=datetime.now(UTC))
    )


async def _changed(session: AsyncSession, row: Invitation, change: str) -> None:
    await record_event(
        session,
        InvitationChanged(change=change, status=row.status),  # type: ignore[arg-type]  # checked literals
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


# --- The person's side of a copied link (REQ-SEC-021; lane B's public-side conditions) --------


@dataclass(frozen=True)
class LinkInvitation:
    """What the set-password page may know of a working link: which app, and the rules."""

    for_console: bool
    policy: PasswordPolicy


def _invalid() -> NotFound:
    """Every way a link does not work, one answer (lane B): never which check failed."""
    return NotFound(code=invite_link.INVALID)


async def _linked(
    session: AsyncSession, admin: IdentityAdmin, token: str, now: datetime, *, lock: bool
) -> tuple[Invitation, User]:
    """The pending invitation a token belongs to and its person; `_invalid` for anything else.

    Checked again at use (lane B): pending, not expired, delivered by link, the person active
    and allowed to sign in, and their Keycloak account the invitation's own, enabled, with no
    password yet. Only then is a password policy error ever told.
    """
    if not invite_link.token_shape_ok(token):
        raise _invalid()
    statement = select(Invitation).where(
        Invitation.link_token_hash == link_token_hash(token), Invitation.status == "pending"
    )
    row = await session.scalar(statement.with_for_update() if lock else statement)
    if row is None or row.expires_at <= now or row.delivery != "link":
        raise _invalid()
    person = await session.get(User, row.user_id)
    if (
        person is None
        or person.deleted_at is not None
        or person.status != "active"
        or not person.can_sign_in
        or not row.keycloak_user_id
    ):
        raise _invalid()
    found = await admin.find_user(person.email or "")
    if found is None or found.id != row.keycloak_user_id or not found.enabled or found.has_password:
        raise _invalid()
    return row, person


async def peek_link(
    session: AsyncSession, admin: IdentityAdmin | None, token: str, now: datetime
) -> LinkInvitation:
    """Whether a link works, for the page to show its form; nothing changes."""
    if admin is None:
        raise _invalid()
    _row_found, person = await _linked(session, admin, token, now, lock=False)
    rules = (await get_identity_settings(session)).password_policy()
    return LinkInvitation(person.user_type == "technician", rules)


async def accept_link(
    session: AsyncSession, admin: IdentityAdmin | None, token: str, password: str, now: datetime
) -> uuid.UUID:
    """Set the person's first password from a copied link, once; the person's ID.

    Keycloak sets the password (not temporary) and takes the set-password action off; nothing
    else of the account changes (never `emailVerified`) and nobody is signed in: the person
    signs in as usual next. The invitation is accepted and the link used up in this
    transaction (the row is locked, so a second submit finds nothing).
    """
    if admin is None:
        raise _invalid()
    row, person = await _linked(session, admin, token, now, lock=True)
    if invite_link.too_long(password):
        raise _password_problem(invite_link.TOO_LONG)
    # Keycloak is written before this transaction commits (lane B): should the commit then fail,
    # the person has a password and a still-pending invitation, and signing in accepts it
    # (`mark_accepted`); the link stays used only once, as the account now has a password and
    # `_linked` refuses any account that has one.
    try:
        await admin.set_password(row.keycloak_user_id or "", password)
    except IdentityAdminRefused as refused:
        raise _password_problem(invite_link.refusal(refused.message)) from None
    await admin.clear_actions(row.keycloak_user_id or "", [SET_PASSWORD])
    row.status, row.accepted_at = "accepted", now
    row.link_token_hash = None  # single use
    row.version += 1
    await session.flush()
    await _changed(session, row, "accepted")
    return person.id


def _password_problem(code: str) -> ValidationFailed:
    return ValidationFailed(
        errors=[FieldError(field="body.password", code=code, message_key=f"errors.field.{code}")]
    )
