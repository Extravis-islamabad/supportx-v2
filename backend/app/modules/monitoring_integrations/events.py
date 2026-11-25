"""Event contracts of monitoring_integrations (WP-053 S6). IDs and codes only."""

import uuid
from typing import ClassVar, Literal

from app.shared.events import DomainEvent

ConnectionChange = Literal["added", "changed", "removed"]


class ConnectionChanged(DomainEvent):
    """A MonetX connection was added, changed or removed (never its token)."""

    event_type: ClassVar[str] = "monitoring_integrations.connection.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "monitoring_connection"

    connection_id: uuid.UUID
    change: ConnectionChange
    version: int


class TopologyRunChanged(DomainEvent):
    """A topology import started or finished: its state and counts, never device names."""

    event_type: ClassVar[str] = "monitoring_integrations.topology_run.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "monitoring_connection"

    connection_id: uuid.UUID
    run_id: uuid.UUID
    state: str
    created: int = 0
    updated: int = 0
    stale: int = 0
    ended: int = 0


class HealthChanged(DomainEvent):
    """A watched CI's health changed: the state code only (the coordinator's S6 condition 4)."""

    event_type: ClassVar[str] = "monitoring_integrations.health.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "cmdb_ci"

    ci_id: uuid.UUID
    state: str


EVENTS: tuple[type[DomainEvent], ...] = (ConnectionChanged, TopologyRunChanged, HealthChanged)
