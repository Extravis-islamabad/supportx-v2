"""The connector secrets store, as mailboxes use it (WP-040 session 1; REQ-INT-003, REQ-SEC-042).

Expand phase (migration 0045, D-113): a mailbox's credential and refresh token live in
`connector_secrets`, and every write also keeps the old mailbox columns current (the same sealed
bytes), so going back loses nothing until the contract step.

Reading prefers the store. When the store's copy is missing or does not open, the old column is
used so the mailbox keeps working, and that is never silent: a warning by code (never a value),
the `supportx_connector_secret_fallback` counter by code, and `secret_fallback_at` on the mailbox,
which the catalogue shows as degraded until a read from the store works again.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from opentelemetry import metrics
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.logging import get_logger
from app.modules.integrations.domain.mailboxes import CredentialKind, MailboxProtocol
from app.modules.integrations.infra.imap import MailboxUnavailableError
from app.modules.integrations.infra.models import ConnectorSecret, Mailbox
from app.modules.integrations.service.connections import (
    SECRET_PURPOSE,
    TOKEN_PURPOSE,
    UNREADABLE,
    Credentials,
    seal,
)
from app.shared.files.keyring import KeyRing, KeyRingError
from app.shared.ids import new_id

log = get_logger(__name__)
OWNER_MAILBOX = "mailbox"

_meter = metrics.get_meter("supportx.integrations")
_fallbacks = _meter.create_counter(
    "supportx_connector_secret_fallback",
    description="Connector secrets read from the old column because the store's copy failed",
)


class SecretRole(StrEnum):
    """Which of a mailbox's secrets."""

    CREDENTIAL = "credential"  # the IMAP password, or the OAuth app's secret or certificate
    REFRESH_TOKEN = "refresh_token"  # noqa: S105 - a role name, not a token


class Fallback(StrEnum):
    """Why the store's copy was not used (counter label and log code)."""

    MISSING = "store_missing"  # the reference points nowhere, or the row was removed
    UNREADABLE = "store_unreadable"  # the row does not open (key ring, tampering)
    NOT_MOVED = "not_moved"  # the old column holds a secret the store has no copy of


_PURPOSES = {SecretRole.CREDENTIAL: SECRET_PURPOSE, SecretRole.REFRESH_TOKEN: TOKEN_PURPOSE}


def _secret_type(mailbox: Mailbox, role: SecretRole) -> str:
    if role is SecretRole.REFRESH_TOKEN:
        return "refresh_token"
    if mailbox.protocol == MailboxProtocol.IMAP.value:
        return "password"
    if mailbox.credential_kind == CredentialKind.CERTIFICATE.value:
        return "certificate"
    return "client_secret"


def _ref(mailbox: Mailbox, role: SecretRole) -> uuid.UUID | None:
    return mailbox.secret_ref if role is SecretRole.CREDENTIAL else mailbox.token_ref


def _old(mailbox: Mailbox, role: SecretRole) -> tuple[str | None, bytes | None]:
    if role is SecretRole.CREDENTIAL:
        return mailbox.secret_key_id, mailbox.secret_sealed
    return mailbox.token_key_id, mailbox.token_sealed


def _open(ring: KeyRing, tenant_id: uuid.UUID, purpose: str, key_id: str, sealed: bytes) -> str:
    return ring.unseal(tenant_id, purpose, key_id, sealed).decode()


async def _stored(session: AsyncSession, ref: uuid.UUID) -> ConnectorSecret | None:
    return await session.scalar(
        select(ConnectorSecret)
        .options(undefer(ConnectorSecret.sealed))
        .where(ConnectorSecret.id == ref, ConnectorSecret.deleted_at.is_(None))
    )


async def _read(
    session: AsyncSession, mailbox: Mailbox, ring: KeyRing, role: SecretRole
) -> tuple[str | None, Fallback | None]:
    """The value and, when the old column had to be used, why."""
    purpose = _PURPOSES[role]
    ref = _ref(mailbox, role)
    old_key, old_sealed = _old(mailbox, role)
    fallback: Fallback | None = None
    if ref is not None:
        row = await _stored(session, ref)
        if row is None:
            fallback = Fallback.MISSING
        else:
            try:
                return _open(ring, mailbox.tenant_id, row.purpose, row.key_id, row.sealed), None
            except KeyRingError:
                fallback = Fallback.UNREADABLE
    elif old_key is not None and old_sealed is not None:
        fallback = Fallback.NOT_MOVED
    if old_key is None or old_sealed is None:
        if fallback is not None:
            raise MailboxUnavailableError(UNREADABLE)  # nothing left to try: the mailbox fails
        return None, None
    try:
        value = _open(ring, mailbox.tenant_id, purpose, old_key, old_sealed)
    except KeyRingError as exc:
        raise MailboxUnavailableError(UNREADABLE) from exc
    return value, fallback


async def credentials(
    session: AsyncSession, mailbox: Mailbox, ring: KeyRing, *, mark: bool = True
) -> Credentials:
    """The mailbox's secrets for a connection; marks the mailbox degraded on a fallback.

    The caller's transaction keeps the mark (`secret_fallback_at`), and clears it once every
    secret came from the store. A connection test passes `mark=False`: it saves nothing
    (REQ-INT-002 AC1), though the fallback is still counted and logged.
    """
    secret, secret_fallback = await _read(session, mailbox, ring, SecretRole.CREDENTIAL)
    token, token_fallback = await _read(session, mailbox, ring, SecretRole.REFRESH_TOKEN)
    fell_back = [f for f in (secret_fallback, token_fallback) if f is not None]
    for code in fell_back:
        _fallbacks.add(1, {"code": code.value})
        # Codes and IDs only: never the value, the address or the key.
        log.warning("connector_secret_fallback", code=code.value, mailbox_id=str(mailbox.id))
    if not mark:
        pass
    elif fell_back:
        mailbox.secret_fallback_at = mailbox.secret_fallback_at or datetime.now(UTC)
    else:
        mailbox.secret_fallback_at = None
    return Credentials(secret, token)


async def put(
    session: AsyncSession, mailbox: Mailbox, ring: KeyRing, role: SecretRole, value: str
) -> None:
    """Store (or rotate) one secret: the store's row and the old column get the same bytes."""
    purpose = _PURPOSES[role]
    key_id, sealed = seal(ring, mailbox.tenant_id, purpose, value)
    if role is SecretRole.CREDENTIAL:
        mailbox.secret_key_id, mailbox.secret_sealed = key_id, sealed
    else:
        mailbox.token_key_id, mailbox.token_sealed = key_id, sealed
    now = datetime.now(UTC)
    ref = _ref(mailbox, role)
    row = await _stored(session, ref) if ref is not None else None
    if row is None:
        row = ConnectorSecret(
            id=new_id(),
            tenant_id=mailbox.tenant_id,
            name=f"{OWNER_MAILBOX}.{mailbox.id}.{role.value}",
            owner_kind=OWNER_MAILBOX,
            owner_id=mailbox.id,
            role=role.value,
        )
        await _drop_owner_role(session, mailbox.id, role)  # a removed earlier copy, if any
        await session.flush()  # the old copy leaves the unique index before the new one comes
        session.add(row)
    row.secret_type = _secret_type(mailbox, role)
    row.purpose, row.key_id, row.sealed, row.set_at = purpose, key_id, sealed, now
    row.updated_at = now
    await session.flush()
    if role is SecretRole.CREDENTIAL:
        mailbox.secret_ref = row.id
    else:
        mailbox.token_ref = row.id


async def _drop_owner_role(session: AsyncSession, owner_id: uuid.UUID, role: SecretRole) -> None:
    stale = await session.scalars(
        select(ConnectorSecret).where(
            ConnectorSecret.owner_kind == OWNER_MAILBOX,
            ConnectorSecret.owner_id == owner_id,
            ConnectorSecret.role == role.value,
            ConnectorSecret.deleted_at.is_(None),
        )
    )
    now = datetime.now(UTC)
    for row in stale:
        row.deleted_at = row.updated_at = now


async def clear(session: AsyncSession, mailbox: Mailbox, role: SecretRole) -> None:
    """Forget one secret (a disconnected sign-in, a removed mailbox): both copies."""
    if role is SecretRole.CREDENTIAL:
        mailbox.secret_key_id = mailbox.secret_sealed = mailbox.secret_ref = None
    else:
        mailbox.token_key_id = mailbox.token_sealed = mailbox.token_ref = None
    await _drop_owner_role(session, mailbox.id, role)
