"""Integrations events on realtime (WP-011 pattern; docs/architecture/realtime.md).

The mail page refetches on a tenant-wide signal with no IDs or values; the API decides who sees
mailboxes (`mailboxes.manage`), so the signal reveals nothing.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

MAILBOXES_CHANGED = "integrations.mailboxes_changed"


async def _mailboxes_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), MAILBOXES_CHANGED)]
    )


ROUTES = [RealtimeRoute(("integrations.mailbox.changed",), _mailboxes_changed)]
