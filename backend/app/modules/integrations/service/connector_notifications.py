"""Connector admins hear when a connector fails and when it recovers (WP-040; REQ-INT-005).

One notification source for every kind (record type "connector"). The people told are those who
may set up the kind's category (REQ-INT-013): for mailboxes, `mailboxes.manage`, as before.
`connector.failing` replaces `mailbox.failing` (migration 0046 copied each tenant's rule);
the mailbox source still handles old `mailbox.failing` events until the contract step.
"""

import uuid
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.identity_access import subject_for, worker_policy
from app.modules.integrations.events import ConnectorFailing, ConnectorRecovered
from app.modules.integrations.infra.models import ConnectorHealth
from app.modules.integrations.service.catalogue import manage_permission
from app.shared.connectors.ports import Registered, registered_connectors
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    LabelRef,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

RECORD_TYPE = "connector"
CONNECTOR_ADMINS = "connector_admins"
ADMINS_LIMIT = 200
FAILING = "connector.failing"
RECOVERED = "connector.recovered"

_VARIABLES = (
    Variable("record.title", "notification_variable.connector.name"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


def _kind(code: str) -> Registered | None:
    return next((r for r in registered_connectors() if r.kind.code == code), None)


class ConnectorNotifications:
    """The notification source of connectors (record type "connector")."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = "connector"
    events: ClassVar[tuple[NotificationEvent, ...]] = (
        NotificationEvent(
            FAILING,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(CONNECTOR_ADMINS,)),
            variables=(Variable("connector.reason", "notification_variable.connector.reason"),),
        ),
        NotificationEvent(
            RECOVERED,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(CONNECTOR_ADMINS,)),
        ),
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (CONNECTOR_ADMINS,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (
        ConnectorFailing.event_type,
        ConnectorRecovered.event_type,
    )

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notification event per domain event."""
        return {
            ConnectorFailing.event_type: (FAILING,),
            ConnectorRecovered.event_type: (RECOVERED,),
        }.get(envelope.event_type, ())

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The instance (by its owner's name) and the people who may set its kind up, now."""
        registered = _kind(str(envelope.payload["kind"]))
        if registered is None:
            return None  # a kind no longer installed: nobody to tell about it
        instance_id = uuid.UUID(str(envelope.payload["instance_id"]))
        instance = next(
            (i for i in await registered.source.instances(session) if i.id == instance_id), None
        )
        if instance is None:
            return None  # removed since: nothing to fix
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        permission = manage_permission(registered.kind.category)
        admins = await worker_policy().holders(session, tenant, permission, limit=ADMINS_LIMIT)
        values: dict[str, VariableValue] = {
            "record.title": instance.name,
            "record.link": registered.kind.page,
        }
        if event_code == FAILING:
            reason = str(envelope.payload["reason"])
            values["connector.reason"] = LabelRef(f"{registered.kind.reason_labels}.{reason}")
        return RecordContext(
            record_id=instance_id,
            display_id=instance.name,
            link=registered.kind.page,
            variables=values,
            public_variables=values,
            relatives={CONNECTOR_ADMINS: frozenset(user_id for user_id, _ in admins)},
            conditions={},
            event_code=event_code,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for people who may set up the instance's kind (checked at send time)."""
        kind = await session.scalar(
            select(ConnectorHealth.kind).where(ConnectorHealth.instance_id == record_id)
        )
        registered = _kind(kind) if kind is not None else None
        if registered is None:
            return RecordAccess.NONE
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        allowed = subject.holds(manage_permission(registered.kind.category))
        return RecordAccess.FULL if allowed else RecordAccess.NONE


SOURCE = ConnectorNotifications()


def register() -> None:
    """Make connectors notify (idempotent; called when the integrations module is imported)."""
    register_record_source(SOURCE)
