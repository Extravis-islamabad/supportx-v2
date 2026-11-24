"""Which record a reply is about, from the mail it answers (WP-024; REQ-INC-023 AC2).

A reply's In-Reply-To/References name Message-IDs of mail SupportX sent; the delivery log knows
which record each notification e-mail was about. Used when the subject lost its token.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
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


async def mail_recipients_for(
    session: AsyncSession, message_ids: Sequence[str], *, event_code: str
) -> list[tuple[uuid.UUID, uuid.UUID, datetime]]:
    """(record id, recipient id, last sent) of one notice's e-mails these Message-IDs name.

    WP-047a S4 (REQ-SR-038): a reply counts as an approval decision only when it answers the
    approval mail itself (the coordinator's condition 2), so a mail forwarded or written for
    another request can never decide this one; the time says which approvals that mail could
    have been about (none made after it). Only e-mails to a person; oldest first.
    """
    mail_ids = await mails_with_message_ids(session, message_ids)
    if not mail_ids:
        return []
    rows = await session.execute(
        select(
            NotificationDelivery.record_id,
            NotificationDelivery.user_id,
            func.max(NotificationDelivery.created_at),
        )
        .where(
            NotificationDelivery.mail_id.in_(mail_ids),
            NotificationDelivery.event_code == event_code,
            NotificationDelivery.channel == "email",
            NotificationDelivery.user_id.is_not(None),
        )
        .group_by(NotificationDelivery.record_id, NotificationDelivery.user_id)
        .order_by(func.max(NotificationDelivery.created_at))
    )
    return [(record_id, user_id, sent) for record_id, user_id, sent in rows if user_id is not None]
