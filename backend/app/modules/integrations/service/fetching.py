"""Polling mailboxes (WP-024; REQ-INC-023 AC1/AC3/AC4, REQ-ADM-066 AC1, REQ-ADM-067).

The `integrations__mail_fetch` schedule runs every minute; each enabled mailbox is fetched when
its `next_fetch_at` is due (every 2 minutes, Appendix A). Per mailbox:

1. open the reader with the password unsealed from the key ring;
2. for each new message: `inbound.process` in its own tenant transaction, committed, and only
   then the message is marked read, moved or deleted on the server (REQ-ADM-067: never deleted
   unless the admin chose it; a crash in between finds it again and the ledger skips it);
3. the mailbox's state: working, or failing with a reason code the mail page shows, so a
   connection problem is visible in the product, not only in logs (REQ-INC-023 AC4).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.integrations.domain.mailboxes import (
    POLL_SECONDS,
    AfterFetch,
    ConnectionSecurity,
    MailboxState,
)
from app.modules.integrations.events import MailboxChanged
from app.modules.integrations.infra.imap import (
    ImapReader,
    ImapSettings,
    MailboxReader,
    MailboxUnavailableError,
)
from app.modules.integrations.infra.models import Mailbox
from app.modules.integrations.service.inbound import process
from app.shared.events import record_event
from app.shared.files.keyring import KeyRing, KeyRingError

log = get_logger(__name__)
SECRET_PURPOSE = "mailbox"  # noqa: S105 - the sealing context, not a password
NOT_SET = "mailbox_no_password"
UNREADABLE = "mailbox_secret_unreadable"


def key_ring(settings: Settings) -> KeyRing | None:
    """The installation key ring (the same as for files), or None when not configured."""
    if settings.files_keys is None:
        return None
    return KeyRing.parse(settings.files_keys.get_secret_value())


def seal_password(ring: KeyRing, tenant_id: uuid.UUID, password: str) -> tuple[str, bytes]:
    """(key id, sealed bytes) to store on the mailbox; the password is never stored in clear."""
    return ring.seal(tenant_id, SECRET_PURPOSE, password.encode())


def reader_for(mailbox: Mailbox, ring: KeyRing) -> MailboxReader:
    """The IMAP reader of a mailbox (Graph and Gmail readers come in session 2)."""
    if mailbox.secret_key_id is None or mailbox.secret_sealed is None:
        raise MailboxUnavailableError(NOT_SET)
    try:
        password = ring.unseal(
            mailbox.tenant_id, SECRET_PURPOSE, mailbox.secret_key_id, mailbox.secret_sealed
        ).decode()
    except KeyRingError as exc:
        raise MailboxUnavailableError(UNREADABLE) from exc
    return ImapReader(
        ImapSettings(
            host=mailbox.host,
            port=mailbox.port,
            security=ConnectionSecurity(mailbox.security),
            username=mailbox.username,
            password=password,
            folder=mailbox.folder,
        )
    )


def own_addresses(settings: Settings, mailboxes: list[Mailbox]) -> tuple[str, ...]:
    """Addresses mail from which is a loop with ourselves."""
    addresses = [m.address for m in mailboxes]
    if settings.mail_from_address:
        addresses.append(settings.mail_from_address)
    return tuple(a.lower() for a in addresses)


async def _set_state(
    session: AsyncSession,
    mailbox_id: uuid.UUID,
    state: MailboxState,
    reason: str | None,
    *,
    handled: int,
) -> None:
    mailbox = await session.get(Mailbox, mailbox_id)
    if mailbox is None:
        return
    now = datetime.now(UTC)
    moved = (mailbox.state, mailbox.state_reason) != (state.value, reason)
    mailbox.state, mailbox.state_reason = state.value, reason
    mailbox.last_fetch_at = now
    mailbox.next_fetch_at = now + timedelta(seconds=POLL_SECONDS)
    if moved or handled:  # a quiet poll every 2 minutes signals nothing
        await record_event(
            session,
            MailboxChanged(mailbox_id=mailbox.id, change="fetched"),
            aggregate_id=mailbox.id,
            aggregate_version=mailbox.version,
        )


async def fetch_mailbox(  # noqa: PLR0913 - the mailbox and its collaborators, explicit
    database: Database,
    settings: Settings,
    tenant: uuid.UUID,
    mailbox_id: uuid.UUID,
    *,
    ring: KeyRing,
    reader: MailboxReader | None = None,
) -> int:
    """Fetch one mailbox now; how many new messages were handled."""
    async with database.tenant_session(TenantContext(tenant)) as session:
        mailbox = await session.get(Mailbox, mailbox_id)
        if mailbox is None or not mailbox.enabled or mailbox.deleted_at is not None:
            return 0
        boxes = list(await session.scalars(select(Mailbox).where(Mailbox.deleted_at.is_(None))))
        ours = own_addresses(settings, boxes)
        after, move_to = AfterFetch(mailbox.after_fetch), mailbox.move_to
    handled = 0
    try:
        reader = reader or reader_for(mailbox, ring)
        try:
            for fetched in await reader.new_messages():
                async with database.tenant_session(TenantContext(tenant)) as session:
                    live = await session.get(Mailbox, mailbox_id)
                    if live is None:
                        break
                    outcome = await process(
                        session, settings, live, fetched.raw, own_addresses=ours
                    )
                # Committed: now the server copy (also for a message seen before).
                await reader.done(fetched.uid, after, move_to)
                handled += outcome is not None
        finally:
            await reader.close()
    except MailboxUnavailableError as exc:
        log.warning("mailbox_fetch_failed", mailbox_id=str(mailbox_id), reason=exc.reason)
        async with database.tenant_session(TenantContext(tenant)) as session:
            await _set_state(session, mailbox_id, MailboxState.FAILING, exc.reason, handled=handled)
        return handled
    async with database.tenant_session(TenantContext(tenant)) as session:
        await _set_state(session, mailbox_id, MailboxState.WORKING, None, handled=handled)
    return handled


async def fetch_schedule(database: Database, settings: Settings) -> None:
    """Every minute: fetch the mailboxes that are due, in every tenant."""
    ring = key_ring(settings)
    if ring is None:
        return  # no key ring, no stored passwords: nothing can be fetched (the page says so)
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    now = datetime.now(UTC)
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            due = list(
                await session.scalars(
                    select(Mailbox.id).where(
                        Mailbox.enabled.is_(True),
                        Mailbox.deleted_at.is_(None),
                        (Mailbox.next_fetch_at.is_(None)) | (Mailbox.next_fetch_at <= now),
                    )
                )
            )
        for mailbox_id in due:
            await fetch_mailbox(database, settings, tenant, mailbox_id, ring=ring)
