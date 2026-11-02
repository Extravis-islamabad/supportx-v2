"""Which record a reply is about, from the mail it answers (WP-024; REQ-INC-023 AC2).

A reply's In-Reply-To/References name Message-IDs of mail SupportX sent; the delivery log knows
which record each notification e-mail was about. Used when the subject lost its token.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.infra.models import NotificationDelivery
from app.shared.mail import mails_with_message_ids


async def records_for_mail(
    session: AsyncSession, message_ids: Sequence[str]
) -> list[tuple[str, uuid.UUID]]:
    """(record type, record id) of the notification e-mails with these Message-IDs."""
    mail_ids = await mails_with_message_ids(session, message_ids)
    if not mail_ids:
        return []
    rows = await session.execute(
        select(NotificationDelivery.record_type, NotificationDelivery.record_id)
        .where(NotificationDelivery.mail_id.in_(mail_ids))
        .distinct()
    )
    return [(record_type, record_id) for record_type, record_id in rows]
