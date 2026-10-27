"""Reporting port (WP-035, ADR-033): modules register what can be reported on; see ports.py."""

from app.shared.reporting.ports import (
    Dimension,
    DimensionKind,
    ReportingSource,
    SourceProvider,
    UnknownEntityError,
    provider_for,
    register_source,
    registered_entities,
    unregister_source,
)

__all__ = [
    "Dimension",
    "DimensionKind",
    "ReportingSource",
    "SourceProvider",
    "UnknownEntityError",
    "provider_for",
    "register_source",
    "registered_entities",
    "unregister_source",
]
