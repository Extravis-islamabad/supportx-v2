"""A schedule's owner hears when a run left recipients out (ADR-047 §5; shape agreed with lane A).

A recipient whose roles hide or mask a field the report uses gets no file (they would see the
field otherwise). The owner is told once per run, in the app and by e-mail: how many were left
out and which fields, named in the owner's language. Never a value, never the recipients' names
in the event (IDs only, rule c); the notice is required, so no preference mutes it.

Record type `report_schedule`; the only recipient is the schedule's owner, and only while they
still own it and may schedule reports.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.analytics.events import ReportScheduleRecipientsSkipped
from app.modules.analytics.infra.models import ReportSchedule
from app.modules.analytics.service.naming import field_label
from app.modules.identity_access import subject_for
from app.shared.events import EventEnvelope
from app.shared.labels import LANGUAGES, plain_label
from app.shared.notifications.ports import (
    EventDefault,
    Localised,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)
from app.shared.reporting import names_resolver

RECORD_TYPE = "report_schedule"
OWNER = "schedule_owner"
SKIPPED = "report_schedule.recipients_skipped"
SCHEDULE_RIGHT = "reports.schedule"
# The reports home with the schedules list open (the console reads `schedules=open`).
LINK = "/reports?schedules=open"
FIELDS_UNKNOWN = "report_schedule_result.fields_unknown"
# How each language separates the items of a short list in running text (mail and in-app).
_SEPARATORS: Mapping[str, str] = {"en": ", ", "ar": "، ", "ur": "، "}

_VARIABLES = (
    Variable("record.title", "notification_variable.report_schedule.name"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


async def _field_labels(session: AsyncSession, entity: str, fields: Sequence[str]) -> Localised:
    """The fields' names per language, joined: built-in labels and the admin's custom names."""
    resolver = names_resolver(f"{entity}.custom_field")
    texts: dict[str, str] = {}
    for language in LANGUAGES:
        if not fields:
            # No recipient's access could be read: say so plainly, never an empty line (lane A).
            texts[language] = plain_label(FIELDS_UNKNOWN, language)
            continue
        custom = await resolver(session, (), language, "") if resolver else {}
        names = [field_label(name, language, custom) for name in fields]
        texts[language] = _SEPARATORS.get(language, ", ").join(names)
    return Localised(texts)


class ScheduleNotifications:
    """The notification source of report schedules (record type "report_schedule")."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = RECORD_TYPE
    events: ClassVar[tuple[NotificationEvent, ...]] = (
        NotificationEvent(
            SKIPPED,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(OWNER,)),
            # The owner must learn that the report did not reach people (lane A, 2026-11-14).
            required=True,
            variables=(
                Variable("skipped.count", "notification_variable.report_schedule.skipped_count"),
                Variable("fields.labels", "notification_variable.report_schedule.fields"),
            ),
        ),
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (OWNER,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (ReportScheduleRecipientsSkipped.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notification per skipped-recipients event."""
        if envelope.event_type == ReportScheduleRecipientsSkipped.event_type:
            return (SKIPPED,)
        return ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The schedule, its owner now, the count and the fields named for the owner."""
        payload = envelope.payload
        schedule_id = uuid.UUID(str(payload["schedule_id"]))
        row = await session.get(ReportSchedule, schedule_id)
        if row is None or row.deleted_at is not None:
            return None  # removed since: nothing to tell
        entity = str(payload["entity"])
        fields = [str(name) for name in payload.get("fields", [])]
        values: dict[str, VariableValue] = {
            "record.title": row.title,
            "record.link": LINK,
            "skipped.count": len(payload.get("skipped", [])),
            "fields.labels": await _field_labels(session, entity, fields),
        }
        return RecordContext(
            record_id=row.id,
            display_id=row.title,
            link=LINK,
            variables=values,
            public_variables=values,
            # Whoever owns it now (it may have moved to a successor since the run).
            relatives={OWNER: frozenset({row.owner_id})},
            conditions={},
            event_code=event_code,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for the schedule's owner while they may schedule reports (checked at send)."""
        row = await session.get(ReportSchedule, record_id)
        if row is None or row.deleted_at is not None or row.owner_id != user_id:
            return RecordAccess.NONE
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        return RecordAccess.FULL if subject.holds(SCHEDULE_RIGHT) else RecordAccess.NONE


SOURCE = ScheduleNotifications()


def register() -> None:
    """Make report schedules notify (idempotent; called when the analytics module is imported)."""
    register_record_source(SOURCE)
