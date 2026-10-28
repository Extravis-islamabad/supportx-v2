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
    AfterFetch,
    ConnectionSecurity,
    MailboxCreates,
    MailboxState,
    Outcome,
    UnknownSenders,
    check_security,
)
from app.modules.integrations.events import MailboxChanged
from app.modules.integrations.infra.imap import ImapReader, ImapSettings, MailboxUnavailableError
from app.modules.integrations.infra.models import Mailbox, MailFetched
from app.modules.integrations.service.fetching import key_ring, seal_password
from app.shared.events import record_event

MANAGE = "mailboxes.manage"
Change = Literal["added", "changed", "removed", "fetched"]
FIELDS = (
    "address",
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
    has_password: bool
    held: int  # messages kept for an admin (refused, flooding, not the requester)


def _problems(values: Mapping[str, Any]) -> list[FieldError]:
    security = ConnectionSecurity(values.get("security", "tls"))
    errors = [
        FieldError(
            field="body.security",
            code="plain_connection_refused",
            message_key="errors.field.plain_connection_refused",
        )
        for _ in check_security(security, allow_plain=bool(values.get("allow_plain")))
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
        .where(MailFetched.outcome == Outcome.HELD.value)
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


def _view(row: Mailbox, held: Mapping[uuid.UUID, int]) -> MailboxView:
    return MailboxView(row, row.secret_sealed is not None, held.get(row.id, 0))


async def list_mailboxes(session: AsyncSession) -> list[MailboxView]:
    """Every mailbox of the tenant, by address."""
    held = await _held_counts(session)
    rows = await session.scalars(
        select(Mailbox).where(Mailbox.deleted_at.is_(None)).order_by(Mailbox.address)
    )
    return [_view(row, held) for row in rows]


async def get_mailbox(session: AsyncSession, mailbox_id: uuid.UUID) -> MailboxView:
    """One mailbox (404 when removed or unknown)."""
    row = await session.get(Mailbox, mailbox_id)
    if row is None or row.deleted_at is not None:
        raise NotFound(code="mailbox_not_found")
    return _view(row, await _held_counts(session))


def _apply(row: Mailbox, values: Mapping[str, Any]) -> None:
    for name in FIELDS:
        if name in values:
            value = values[name]
            setattr(row, name, value.lower() if name == "address" else value)


async def create_mailbox(
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    password: str,
) -> MailboxView:
    """A new mailbox; fetched at the next poll once its connection works."""
    if errors := _problems(values):
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
    row.secret_key_id, row.secret_sealed = seal_password(ring, tenant_id, password)
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
    if errors := _problems(merged):
        raise ValidationFailed(errors=errors)
    _apply(row, values)
    if password:
        ring = key_ring(settings)
        if ring is None:
            raise KeyRingMissing
        row.secret_key_id, row.secret_sealed = seal_password(ring, row.tenant_id, password)
    connection = {"host", "port", "security", "username", "folder"}
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


async def test_connection(settings: ImapSettings) -> str | None:
    """Connect and count new mail, changing nothing; None when it works, else a reason code."""
    reader = ImapReader(settings)
    try:
        await reader.new_messages(limit=1)
    except MailboxUnavailableError as exc:
        return exc.reason
    finally:
        await reader.close()
    return None


__all__ = [
    "MANAGE",
    "AfterFetch",
    "MailboxCreates",
    "MailboxView",
    "UnknownSenders",
    "create_mailbox",
    "get_mailbox",
    "list_mailboxes",
    "remove_mailbox",
    "test_connection",
    "update_mailbox",
]
