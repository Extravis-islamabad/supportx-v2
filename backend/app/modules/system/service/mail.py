"""Worker side of the mail service (WP-039 session 2): send, retry, clear old content.

Registered by the `system` module, as for the files service: `app/shared/mail` holds the rules
and tables, this wires them to the event bus and the schedules.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.shared.events import EventEnvelope
from app.shared.mail.service import outgoing

log = get_logger(__name__)


async def on_mail_queued(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: send a message just queued (a temporary failure is retried by the schedule)."""
    assert session is not None  # noqa: S101 - transactional consumer
    await outgoing.deliver(session, get_settings(), uuid.UUID(str(envelope.payload["mail_id"])))


async def _tenant_ids(database: Database) -> list[uuid.UUID]:
    async with database.platform_session() as session:
        return list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())


async def retry(database: Database, settings: Settings) -> None:
    """Schedule: send queued messages whose next attempt is due."""
    if not outgoing.mail_configured(settings):
        return
    for tenant in await _tenant_ids(database):
        async with database.tenant_session(TenantContext(tenant)) as session:
            due = await outgoing.due_messages(session)
        for mail_id in due:
            async with database.tenant_session(TenantContext(tenant)) as session:
                await outgoing.deliver(session, settings, mail_id)


async def purge(database: Database, settings: Settings) -> None:
    """Schedule: clear bodies and attachments of messages done long enough ago."""
    del settings
    for tenant in await _tenant_ids(database):
        async with database.tenant_session(TenantContext(tenant)) as session:
            cleared = await outgoing.purge_content(session)
        if cleared:
            log.info("mail_content_purged", tenant_id=str(tenant), messages=cleared)
