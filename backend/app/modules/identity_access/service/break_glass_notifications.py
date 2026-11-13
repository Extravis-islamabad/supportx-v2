"""Every other tenant admin hears of a break-glass sign-in (REQ-SEC-009 AC3; WP-057 S1b).

One notification source (record type "break_glass"): the event names the admin who used their
break-glass account; the people told are the tenant's other admins (the person themselves is
not, `notify_actor` off), through the one notification engine, in-app and by e-mail. Urgent: it
is never held for a digest. The message links to Sign-in and security.
"""

import uuid
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.domain.permissions import TENANT_ADMIN
from app.modules.identity_access.events import BreakGlassSignedIn
from app.modules.identity_access.infra.models import Role, User, UserRole
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

RECORD_TYPE = "break_glass"
OTHER_ADMINS = "other_tenant_admins"
SIGNED_IN = "break_glass.signed_in"
LINK = "/admin/security"
ADMINS_LIMIT = 200

_VARIABLES = (
    Variable("record.title", "notification_variable.break_glass.person"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


async def _admins(session: AsyncSession) -> list[uuid.UUID]:
    found = await session.scalars(
        select(UserRole.user_id)
        .join(Role, Role.id == UserRole.role_id)
        .join(User, User.id == UserRole.user_id)
        .where(
            Role.key == TENANT_ADMIN,
            Role.deleted_at.is_(None),
            User.status == "active",
            User.deleted_at.is_(None),
        )
        .limit(ADMINS_LIMIT)
    )
    return list(found)


class BreakGlassNotifications:
    """The notification source of break-glass sign-ins."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = "users"
    events: ClassVar[tuple[NotificationEvent, ...]] = (
        NotificationEvent(
            SIGNED_IN,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(OTHER_ADMINS,)),
            required=True,  # a security alert: people cannot switch it off
            locked=True,  # nor can an admin change or reset its rule
        ),
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (OTHER_ADMINS,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (BreakGlassSignedIn.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notification per break-glass sign-in."""
        return (SIGNED_IN,) if envelope.event_type == BreakGlassSignedIn.event_type else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """Who signed in, and the tenant's other admins now."""
        del event_code
        user_id = uuid.UUID(str(envelope.payload["user_id"]))
        person = await session.get(User, user_id)
        if person is None:
            return None
        others = frozenset(a for a in await _admins(session) if a != user_id)
        values: dict[str, VariableValue] = {
            "record.title": person.display_name,
            "record.link": LINK,
        }
        return RecordContext(
            record_id=user_id,
            display_id=person.display_name,
            link=LINK,
            variables=values,
            public_variables=values,
            relatives={OTHER_ADMINS: others},
            conditions={},
            urgent=True,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for the tenant's admins (checked at send time), nobody else."""
        del record_id
        return RecordAccess.FULL if user_id in set(await _admins(session)) else RecordAccess.NONE


SOURCE = BreakGlassNotifications()


def register() -> None:
    """Make break-glass sign-ins notify (idempotent; called when identity_access is imported)."""
    register_record_source(SOURCE)
