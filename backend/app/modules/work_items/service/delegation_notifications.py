"""Notices of approval delegations (WP-047a S3b; REQ-SR-035; the coordinator's condition 1).

Both people hear of a delegation being set, changed and ended (early or at its end): the
delegator and the delegate, and nobody else. At send time the delegation is read again, so a
notice names the dates and people as they are then.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import user_names
from app.modules.work_items.domain.delegations import Window
from app.modules.work_items.events import ApprovalDelegationChanged
from app.modules.work_items.infra.models import ApprovalDelegation
from app.modules.work_items.service.realtime import RECORD_KIND
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

RECORD_TYPE = "approval_delegation"
DELEGATOR = "delegator"
DELEGATE = "delegate"
SET = "approval_delegation.set"
CHANGED = "approval_delegation.changed"
ENDED = "approval_delegation.ended"
LINK = "/approvals/delegations"
_CODES = {"created": SET, "changed": CHANGED, "ended": ENDED, "expired": ENDED}

VARIABLES = (
    Variable("delegation.delegator", "notification_variable.delegation.delegator"),
    Variable("delegation.delegate", "notification_variable.delegation.delegate"),
    Variable("delegation.starts_at", "notification_variable.delegation.starts_at"),
    Variable("delegation.ends_at", "notification_variable.delegation.ends_at"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)
EVENTS = tuple(
    NotificationEvent(
        code,
        NotificationCategory.APPROVAL,
        EventDefault(enabled=True, recipients=(DELEGATOR, DELEGATE)),
        required=True,  # condition 1: both people are told, always
    )
    for code in (SET, CHANGED, ENDED)
)


class DelegationNotifications:
    """`RecordSource` for approval delegations."""

    record_type = RECORD_TYPE
    channel_kind = RECORD_KIND
    events = EVENTS
    recipient_kinds = (DELEGATOR, DELEGATE)
    variables = VARIABLES
    conditions = ()
    event_types = (ApprovalDelegationChanged.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notice per committed change."""
        code = _CODES.get(str(envelope.payload.get("change")))
        return (code,) if code is not None else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The delegation as it is now; both its people told."""
        row = await session.get(
            ApprovalDelegation, uuid.UUID(str(envelope.payload["delegation_id"]))
        )
        if row is None or row.deleted_at is not None:
            return None
        names = await user_names(session, [str(row.delegator_id), str(row.delegate_id)])
        values: dict[str, VariableValue] = {
            "delegation.delegator": names.get(str(row.delegator_id)),
            "delegation.delegate": names.get(str(row.delegate_id)),
            "delegation.starts_at": row.starts_at,
            # When it stops: its end, or the early end if it was ended.
            "delegation.ends_at": Window(row.starts_at, row.ends_at, row.ended_at).until,
        }
        return RecordContext(
            record_id=row.id,
            display_id="",
            link=LINK,
            variables=values,
            public_variables={},
            relatives={
                DELEGATOR: frozenset({row.delegator_id}),
                DELEGATE: frozenset({row.delegate_id}),
            },
            conditions={},
            urgent=False,
            event_code=event_code,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for its two people; nothing for anyone else."""
        row = await session.get(ApprovalDelegation, record_id)
        if row is None or row.deleted_at is not None:
            return RecordAccess.NONE
        return (
            RecordAccess.FULL
            if user_id in {row.delegator_id, row.delegate_id}
            else RecordAccess.NONE
        )


SOURCE = DelegationNotifications()


def register() -> None:
    """Make delegations notify (idempotent; called when work_items is imported)."""
    register_record_source(SOURCE)


__all__ = ["SOURCE", "register"]
