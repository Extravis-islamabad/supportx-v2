"""Tenant admins hear when a verified domain lapses (WP-057 S5d, REQ-SEC-010; lane B (3)).

One notification source (record type "verified_domain"): after 3 failed checks over at least 72
hours a domain stops being verified and its sign-in routing stops. Its tenant's admins are told,
in the app and by e-mail, urgent, required and locked (#480). The message names the domain and
links to Sign-in and security.
"""

import uuid
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.events import VerifiedDomainChanged
from app.modules.identity_access.infra.models import VerifiedDomain
from app.modules.identity_access.service.break_glass_notifications import tenant_admins
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

RECORD_TYPE = "verified_domain"
TENANT_ADMINS = "tenant_admins"
LAPSED = "verified_domain.lapsed"
LINK = "/admin/security?tab=domains"

_VARIABLES = (
    Variable("record.title", "notification_variable.verified_domain.domain"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


class VerifiedDomainNotifications:
    """The notification source of lapsed domains."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = "users"
    events: ClassVar[tuple[NotificationEvent, ...]] = (
        NotificationEvent(
            LAPSED,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(TENANT_ADMINS,), notify_actor=True),
            required=True,  # people cannot switch it off
            locked=True,  # nor can an admin change or reset its rule (#480)
        ),
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (TENANT_ADMINS,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (VerifiedDomainChanged.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """A notice for a lapse only (never for an admin's own delete)."""
        lapsed = (
            envelope.event_type == VerifiedDomainChanged.event_type
            and envelope.payload.get("change") == "lapsed"
        )
        return (LAPSED,) if lapsed else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The domain, and the tenant's admins now."""
        del event_code
        change = VerifiedDomainChanged.model_validate(envelope.payload)
        row = await session.get(VerifiedDomain, change.domain_id)
        if row is None:
            return None
        values: dict[str, VariableValue] = {"record.title": row.domain, "record.link": LINK}
        return RecordContext(
            record_id=row.id,
            display_id=row.domain,
            link=LINK,
            variables=values,
            public_variables=values,
            relatives={TENANT_ADMINS: frozenset(await tenant_admins(session))},
            conditions={},
            urgent=True,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for the tenant's admins (checked at send time), nobody else."""
        del record_id
        return (
            RecordAccess.FULL if user_id in set(await tenant_admins(session)) else RecordAccess.NONE
        )


SOURCE = VerifiedDomainNotifications()


def register() -> None:
    """Make lapses notify (idempotent; called when identity_access is imported)."""
    register_record_source(SOURCE)
