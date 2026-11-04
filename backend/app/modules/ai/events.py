"""Events of the ai module (WP-037). Payloads carry field names, never values or prompt text."""

from typing import ClassVar

from app.shared.events import DomainEvent


class AiSettingsChanged(DomainEvent):
    """The tenant's AI switches or retention changed: screens hide or show AI features live."""

    event_type: ClassVar[str] = "ai.settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "ai_settings"

    changed_fields: list[str]


EVENTS: tuple[type[DomainEvent], ...] = (AiSettingsChanged,)
