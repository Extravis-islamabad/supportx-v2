"""Events of the ai module (WP-037, 038). Payloads carry IDs and names, never text or prompts."""

import uuid
from typing import ClassVar

from app.shared.events import DomainEvent


class AiSettingsChanged(DomainEvent):
    """The tenant's AI switches or retention changed: screens hide or show AI features live."""

    event_type: ClassVar[str] = "ai.settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "ai_settings"

    changed_fields: list[str]


class AiSummaryChanged(DomainEvent):
    """A record's conversation summary was made or became stale: its page refetches it."""

    event_type: ClassVar[str] = "ai.summary.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "ai_summary"

    record_type: str
    record_id: uuid.UUID
    stale: bool


EVENTS: tuple[type[DomainEvent], ...] = (AiSettingsChanged, AiSummaryChanged)
