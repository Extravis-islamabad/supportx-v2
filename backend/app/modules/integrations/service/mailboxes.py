"""Mailboxes: add, change, test, remove, and the mail page's view (WP-024).

Requirements: REQ-INT-050, REQ-INT-051, REQ-ADM-066.

Admins with `mailboxes.manage`. The password is sealed with the installation key ring before it
is stored and never returned; "test" connects with the given (or stored) settings and changes
nothing. A plain (non-TLS) connection is refused unless `allow_plain` is set, and that choice is
audited like every change (REQ-INT-050 AC3). Changes use the mailbox's version (If-Match).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Conflict, FieldError, NotFound, ServiceUnavailable, ValidationFailed
from app.modules.integrations.domain.mailboxes import (
    WAITING,
    AfterFetch,
    AuthModel,
    ConnectionSecurity,
    CredentialKind,
    MailboxCreates,
    MailboxProtocol,
    MailboxState,
    Outcome,
    UnknownSenders,
    check_security,
    oauth_problems,
    releasable,
)
from app.modules.integrations.events import MailboxChanged
from app.modules.integrations.infra.imap import MailboxUnavailableError
from app.modules.integrations.infra.models import Mailbox, MailFetched
from app.modules.integrations.service import inbound
from app.modules.integrations.service.connections import (
    CONSENT_DECLINED,
    CONSENT_EXPIRED,
    SECRET_PURPOSE,
    ConsentRefusedError,
    credential_expiry,
    finish_consent,
    key_ring,
    open_reader,
    pending_consent,
    seal,
    start_consent,
)
from app.modules.integrations.service.fetching import own_addresses
from app.shared.events import record_event
from app.shared.files.keyring import KeyRing

MANAGE = "mailboxes.manage"
Change = Literal["added", "changed", "removed", "fetched"]
FIELDS = (
    "address",
    "protocol",
    "auth_model",
    "client_id",
    "directory_id",
    "credential_kind",
    "credential_expires_at",
    "display_name",
    "host",
    "port",
    "security",
    "allow_plain",
    "username",
    "folder",
    "after_fetch",
    "move_to",
    "creates",
    "group_id",
    "unknown_senders",
    "allowed_domains",
    "enabled",
)


class KeyRingMissing(ServiceUnavailable):
    """No installation key ring: a mailbox password cannot be stored safely."""

    code = "mailbox_key_ring_missing"


@dataclass(frozen=True)
class MailboxView:
    """A mailbox as the mail page shows it (never its password)."""

    row: Mailbox
    has_password: bool  # the IMAP password, or the OAuth app's secret or certificate
    held: int  # messages kept for an admin (refused, flooding, not the requester)
    flooding: bool = False  # mail held because a sender went over the flood limit


# Every code `_problems` can give (labels errors.field.<code>; tests/test_error_labels.py reads
# FIELD_PROBLEMS sets).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        "plain_connection_refused",
        "mailbox_address_invalid",
        "mailbox_auth_model_unsupported",
        "oauth_certificate_invalid",
    }
)


def _field_error(name: str, code: str) -> FieldError:
    key = "errors.field.required" if code == "required" else f"errors.field.{code}"
    return FieldError(field=f"body.{name}", code=code, message_key=key)


def _problems(values: Mapping[str, Any], *, has_secret: bool) -> list[FieldError]:
    protocol = MailboxProtocol(values.get("protocol") or MailboxProtocol.IMAP)
    security = ConnectionSecurity(values.get("security") or "tls")
    errors = [
        _field_error("security", code)
        for code in check_security(security, allow_plain=bool(values.get("allow_plain")))
        if protocol is MailboxProtocol.IMAP
    ]
    if protocol is MailboxProtocol.IMAP:
        errors += [
            _field_error(name, "required")
            for name in ("host", "port", "username")
            if not values.get(name)
        ]
        if not has_secret:
            errors.append(_field_error("password", "required"))
    auth_model, kind = values.get("auth_model"), values.get("credential_kind")
    errors += [
        _field_error(name, code)
        for name, code in oauth_problems(
            protocol,
            auth_model=AuthModel(auth_model) if auth_model else None,
            credential_kind=CredentialKind(kind) if kind else None,
            client_id=values.get("client_id"),
            directory_id=values.get("directory_id"),
            has_credential=has_secret,
        )
    ]
    if values.get("after_fetch") == AfterFetch.MOVE.value and not values.get("move_to"):
        errors.append(
            FieldError(field="body.move_to", code="required", message_key="errors.field.required")
        )
    if "@" not in str(values.get("address", "@")):
        errors.append(
            FieldError(
                field="body.address",
                code="mailbox_address_invalid",
                message_key="errors.field.mailbox_address_invalid",
            )
        )
    return errors


async def _held_counts(session: AsyncSession) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(MailFetched.mailbox_id, func.count())
        .where(MailFetched.outcome.in_([o.value for o in WAITING]))
        .group_by(MailFetched.mailbox_id)
    )
    return {mailbox_id: int(count) for mailbox_id, count in rows}


async def changed(session: AsyncSession, row: Mailbox, change: Change) -> None:
    """The mail page refetches (outbox, same transaction)."""
    await record_event(
        session,
        MailboxChanged(mailbox_id=row.id, change=change),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def _flooding(session: AsyncSession) -> set[uuid.UUID]:
    """Mailboxes with mail waiting because a sender went over the flood limit (REQ-NTF-023)."""
    rows = await session.scalars(
        select(MailFetched.mailbox_id)
        .where(MailFetched.outcome == Outcome.HELD.value, MailFetched.reason == "sender_rate")
        .distinct()
    )
    return set(rows)


def _view(
    row: Mailbox, held: Mapping[uuid.UUID, int], flooding: set[uuid.UUID] | None = None
) -> MailboxView:
    return MailboxView(
        row, row.secret_sealed is not None, held.get(row.id, 0), row.id in (flooding or set())
    )


async def list_mailboxes(session: AsyncSession) -> list[MailboxView]:
    """Every mailbox of the tenant, by address."""
    held, flooding = await _held_counts(session), await _flooding(session)
    rows = await session.scalars(
        select(Mailbox).where(Mailbox.deleted_at.is_(None)).order_by(Mailbox.address)
    )
    return [_view(row, held, flooding) for row in rows]


async def get_mailbox(session: AsyncSession, mailbox_id: uuid.UUID) -> MailboxView:
    """One mailbox (404 when removed or unknown)."""
    row = await session.get(Mailbox, mailbox_id)
    if row is None or row.deleted_at is not None:
        raise NotFound(code="mailbox_not_found")
    return _view(row, await _held_counts(session), await _flooding(session))


def _apply(row: Mailbox, values: Mapping[str, Any]) -> None:
    for name in FIELDS:
        if name in values:
            value = values[name]
            setattr(row, name, value.lower() if name == "address" else value)


def _store_secret(row: Mailbox, ring: KeyRing, secret: str) -> None:
    """Seal the password or OAuth credential; a certificate's own expiry is announced ahead."""
    kind = CredentialKind(row.credential_kind) if row.credential_kind else None
    if row.protocol != MailboxProtocol.IMAP.value and kind is CredentialKind.CERTIFICATE:
        try:
            row.credential_expires_at = credential_expiry(kind, secret)
        except MailboxUnavailableError as exc:
            raise ValidationFailed(errors=[_field_error("client_secret", exc.reason)]) from exc
        row.credential_warned_at = None
    row.secret_key_id, row.secret_sealed = seal(ring, row.tenant_id, SECRET_PURPOSE, secret)


async def create_mailbox(
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    password: str | None,
) -> MailboxView:
    """A new mailbox; fetched at the next poll once its connection works (or its consent)."""
    if errors := _problems(values, has_secret=bool(password)):
        raise ValidationFailed(errors=errors)
    ring = key_ring(settings)
    if ring is None:
        raise KeyRingMissing
    taken = await session.scalar(
        select(Mailbox.id).where(
            func.lower(Mailbox.address) == str(values["address"]).lower(),
            Mailbox.deleted_at.is_(None),
        )
    )
    if taken is not None:
        raise Conflict(code="mailbox_address_taken")
    row = Mailbox(tenant_id=tenant_id, state=MailboxState.NOT_SET_UP.value)
    _apply(row, values)
    if password:  # required for every kind (_problems)
        _store_secret(row, ring, password)
    session.add(row)
    await session.flush()
    await changed(session, row, "added")
    return _view(row, {})


async def update_mailbox(  # noqa: PLR0913 - the mailbox, its version and the change, explicit
    session: AsyncSession,
    settings: Settings,
    mailbox_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    password: str | None,
    expected_version: int,
) -> MailboxView:
    """Change a mailbox (If-Match); a new password replaces the stored one."""
    row = (await get_mailbox(session, mailbox_id)).row
    if row.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": row.version},
        )
    merged = {name: getattr(row, name) for name in FIELDS} | dict(values)
    if errors := _problems(merged, has_secret=bool(password) or row.secret_sealed is not None):
        raise ValidationFailed(errors=errors)
    signed_in = {"protocol", "auth_model", "client_id", "directory_id", "address"}
    if any(name in values and values[name] != getattr(row, name) for name in signed_in):
        # Another app, model or mailbox: the earlier sign-in no longer applies.
        row.token_key_id = row.token_sealed = row.connected_account = None
    _apply(row, values)
    if password:
        ring = key_ring(settings)
        if ring is None:
            raise KeyRingMissing
        _store_secret(row, ring, password)
    connection = {"host", "port", "security", "username", "folder"} | signed_in
    if password or connection & set(values):
        row.state, row.state_reason, row.next_fetch_at = MailboxState.NOT_SET_UP.value, None, None
    row.version += 1
    row.updated_at = datetime.now(UTC)
    await session.flush()
    await changed(session, row, "changed")
    return await get_mailbox(session, mailbox_id)


async def remove_mailbox(
    session: AsyncSession, mailbox_id: uuid.UUID, *, expected_version: int
) -> None:
    """Stop reading the mailbox (soft delete; its ledger stays for the records it made)."""
    row = (await get_mailbox(session, mailbox_id)).row
    if row.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": row.version},
        )
    now = datetime.now(UTC)
    row.deleted_at, row.updated_at, row.enabled = now, now, False
    row.version += 1
    await session.flush()
    await changed(session, row, "removed")


@dataclass(frozen=True)
class WaitingMail:
    """A message in the review queue: who sent it, about what, and why it waits."""

    row: MailFetched
    releasable: bool


async def waiting_mail(session: AsyncSession, mailbox_id: uuid.UUID) -> list[WaitingMail]:
    """The mailbox's review queue, oldest first (D-109 (9): held mail is never invisible)."""
    await get_mailbox(session, mailbox_id)
    rows = await session.scalars(
        select(MailFetched)
        .where(
            MailFetched.mailbox_id == mailbox_id,
            MailFetched.outcome.in_([o.value for o in WAITING]),
        )
        .order_by(MailFetched.created_at)
        .limit(500)
    )
    return [
        WaitingMail(row, releasable(Outcome(row.outcome), row.reason) and row.reason is not None)
        for row in rows
    ]


async def _waiting_row(session: AsyncSession, mailbox: Mailbox, message_id: str) -> MailFetched:
    row = await session.get(MailFetched, (mailbox.tenant_id, mailbox.id, message_id))
    if row is None or Outcome(row.outcome) not in WAITING:
        raise inbound.NotWaiting
    return row


async def release_mail(
    session: AsyncSession,
    settings: Settings,
    mailbox_id: uuid.UUID,
    message_id: str,
    *,
    admin_id: uuid.UUID,
) -> MailFetched:
    """Hand a held message in again; the row says what it became (or why it waits again)."""
    mailbox = (await get_mailbox(session, mailbox_id)).row
    row = await _waiting_row(session, mailbox, message_id)
    boxes = list(await session.scalars(select(Mailbox).where(Mailbox.deleted_at.is_(None))))
    await inbound.release(
        session, settings, mailbox, row, own_addresses=own_addresses(settings, boxes),
        admin_id=admin_id,
    )  # fmt: skip
    await changed(session, mailbox, "changed")
    return row


async def discard_mail(
    session: AsyncSession, mailbox_id: uuid.UUID, message_id: str, *, admin_id: uuid.UUID
) -> None:
    """Discard a waiting message (kept in the ledger as discarded)."""
    mailbox = (await get_mailbox(session, mailbox_id)).row
    await inbound.discard(await _waiting_row(session, mailbox, message_id), admin_id=admin_id)
    await changed(session, mailbox, "changed")


async def try_connection(
    mailbox: Mailbox, settings: Settings, *, secret: str | None = None
) -> str | None:
    """Connect and look for new mail, changing nothing; None when it works, else a reason code.

    `secret` tries a new password or credential before it is saved; otherwise the stored one.
    """
    ring = key_ring(settings)
    if ring is None:
        return "mailbox_key_ring_missing"
    try:
        opened = await open_reader(mailbox, ring, settings, secret=secret)
    except MailboxUnavailableError as exc:
        return exc.reason
    try:
        await opened.reader.new_messages(limit=1)
    except MailboxUnavailableError as exc:
        return exc.reason
    finally:
        await opened.reader.close()
    return None


async def start_sign_in(
    session: AsyncSession,
    settings: Settings,
    mailbox_id: uuid.UUID,
    *,
    admin_id: uuid.UUID,
    origin: str,
) -> str:
    """The Microsoft or Google sign-in address for this mailbox's consent (ten minutes)."""
    row = (await get_mailbox(session, mailbox_id)).row
    ring = key_ring(settings)
    if ring is None:
        raise KeyRingMissing
    try:
        return start_consent(row, ring, settings, admin_id=admin_id, origin=origin)
    except ConsentRefusedError as exc:  # IMAP, or Microsoft 365 with application permission
        raise Conflict(code="mailbox_sign_in_not_needed") from exc
    except MailboxUnavailableError as exc:  # no credential stored, or it cannot be unsealed
        raise Conflict(code="mailbox_credential_unreadable") from exc


@dataclass(frozen=True)
class SignInResult:
    """Where the callback sends the admin back: the mailbox, and a reason when it failed."""

    mailbox_id: uuid.UUID | None
    reason: str | None


async def complete_sign_in(  # noqa: PLR0913 - the callback's facts, explicit
    session: AsyncSession,
    settings: Settings,
    *,
    state: str,
    code: str | None,
    declined: bool,
    admin_id: uuid.UUID,
    origin: str,
) -> SignInResult:
    """Finish a consent; a refusal is returned (not raised) so the cleared state is committed."""
    row = await pending_consent(session, state) if state else None
    ring = key_ring(settings)
    if row is None or ring is None:
        return SignInResult(None, CONSENT_EXPIRED)
    try:
        if declined or not code:
            row.oauth_state_hash = row.oauth_pending_key_id = None
            row.oauth_pending_sealed = row.oauth_pending_until = None
            raise ConsentRefusedError(CONSENT_DECLINED, row.id)  # noqa: TRY301 - one refusal path
        await finish_consent(row, ring, settings, code=code, admin_id=admin_id, origin=origin)
    except ConsentRefusedError as exc:
        return SignInResult(row.id, exc.reason)
    row.version += 1
    row.updated_at = datetime.now(UTC)
    await session.flush()
    await changed(session, row, "changed")
    return SignInResult(row.id, None)


__all__ = [
    "MANAGE",
    "AfterFetch",
    "MailboxCreates",
    "MailboxView",
    "SignInResult",
    "UnknownSenders",
    "WaitingMail",
    "complete_sign_in",
    "create_mailbox",
    "discard_mail",
    "get_mailbox",
    "list_mailboxes",
    "release_mail",
    "remove_mailbox",
    "start_sign_in",
    "try_connection",
    "update_mailbox",
    "waiting_mail",
]
