"""Event catalogue: which event types exist, in which schema versions (WP-007).

Modules list their event classes in `ModuleSpec(events=[...])`. The registry is built from the
discovered modules and checks the naming rules once, at startup:

- `event_type` is `<module>.<entity>.<action>` in lowercase snake case, and `<module>` is the
  declaring module (no module can publish in another module's name);
- `(event_type, schema_version)` is unique; a breaking change is a new class with the next
  version, never an edit of the old one (docs/architecture/events.md, "Versioning").

The outbox writer refuses any event whose class is not registered, so an event that skipped this
check can never be written.
"""

import re
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

from app.core.modules import discover_modules
from app.shared.events.envelope import EVENT_TYPE_PATTERN, DomainEvent, EventEnvelope

if TYPE_CHECKING:
    from app.core.modules import ModuleSpec

EventKey = tuple[str, int]
_AGGREGATE_TYPE = re.compile(r"^[a-z][a-z0-9_]*$")


class EventRegistrationError(RuntimeError):
    """An event class breaks the naming or versioning rules. Always a programming error."""


class UnregisteredEventError(RuntimeError):
    """An event was written or parsed that no module registered."""


class EventRegistry:
    """Event classes by (event_type, schema_version)."""

    def __init__(self) -> None:
        self._events: dict[EventKey, type[DomainEvent]] = {}

    def register(self, event: type, *, module: str) -> None:
        """Add one event class declared by `module`."""
        if not (isinstance(event, type) and issubclass(event, DomainEvent)):
            msg = f"{module}: {event!r} is not a DomainEvent subclass"
            raise EventRegistrationError(msg)
        event_type = getattr(event, "event_type", None)
        aggregate_type = getattr(event, "aggregate_type", None)
        if not isinstance(event_type, str) or not EVENT_TYPE_PATTERN.fullmatch(event_type):
            msg = f"{event.__name__}: event_type must be '<module>.<entity>.<action>' snake case"
            raise EventRegistrationError(msg)
        if event_type.split(".", 1)[0] != module:
            msg = f"{event.__name__}: event_type {event_type!r} must start with {module!r}"
            raise EventRegistrationError(msg)
        if not isinstance(aggregate_type, str) or not _AGGREGATE_TYPE.fullmatch(aggregate_type):
            msg = f"{event.__name__}: aggregate_type must be a snake_case name"
            raise EventRegistrationError(msg)
        if not isinstance(event.schema_version, int) or event.schema_version < 1:
            msg = f"{event.__name__}: schema_version must be an integer >= 1"
            raise EventRegistrationError(msg)
        key = (event_type, event.schema_version)
        existing = self._events.get(key)
        if existing is not None and existing is not event:
            msg = f"{event_type} v{event.schema_version} is declared twice"
            raise EventRegistrationError(msg)
        self._events[key] = event

    def require(self, event: DomainEvent) -> None:
        """Raise UnregisteredEventError unless this exact class is registered."""
        key = (type(event).event_type, type(event).schema_version)
        if self._events.get(key) is not type(event):
            msg = f"{key[0]} v{key[1]} is not registered by any module"
            raise UnregisteredEventError(msg)

    def model_for(self, event_type: str, schema_version: int) -> type[DomainEvent] | None:
        """The class for one event version, if registered."""
        return self._events.get((event_type, schema_version))

    def parse(self, envelope: EventEnvelope) -> DomainEvent:
        """The envelope's payload as its typed event (raises for unknown types or bad payloads)."""
        model = self.model_for(envelope.event_type, envelope.schema_version)
        if model is None:
            msg = f"{envelope.event_type} v{envelope.schema_version} is not registered"
            raise UnregisteredEventError(msg)
        return model.model_validate(envelope.payload)

    def event_types(self) -> set[str]:
        """Every registered event type (any version)."""
        return {event_type for event_type, _ in self._events}

    def __iter__(self) -> Iterator[tuple[EventKey, type[DomainEvent]]]:
        """(key, class) pairs, sorted by type then version."""
        return iter(sorted(self._events.items()))

    @classmethod
    def from_modules(cls, modules: Iterable["ModuleSpec"]) -> "EventRegistry":
        """Registry of every event the given modules declare."""
        registry = cls()
        for spec in modules:
            for event in spec.events:
                registry.register(event, module=spec.name)
        return registry


_active: EventRegistry | None = None


def install_registry(registry: EventRegistry) -> None:
    """Make `registry` the process registry (app factory, workers, tests)."""
    global _active  # noqa: PLW0603 - one catalogue per process, set at startup
    _active = registry


def active_registry() -> EventRegistry:
    """The process registry; built from the discovered modules if nothing installed one."""
    if _active is None:
        install_registry(EventRegistry.from_modules(discover_modules()))
    if _active is None:  # pragma: no cover - install_registry just set it
        raise UnregisteredEventError
    return _active
