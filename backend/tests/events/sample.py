"""A test-only event type, registered by the events test fixtures (never by the app)."""

from typing import ClassVar

from app.core.modules import ModuleSpec
from app.shared.events import DomainEvent


class ProbeHappened(DomainEvent):
    event_type: ClassVar[str] = "probe.item.happened"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "item"

    note: str


PROBE_MODULE = ModuleSpec(name="probe", events=[ProbeHappened])
