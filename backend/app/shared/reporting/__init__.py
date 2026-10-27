"""Reporting port (WP-035, ADR-033): modules register what can be reported on; see ports.py."""

from app.shared.reporting.names import (
    NameResolver,
    names_resolver,
    register_names,
    unregister_names,
)
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
    "NameResolver",
    "ReportingSource",
    "SourceProvider",
    "UnknownEntityError",
    "names_resolver",
    "provider_for",
    "register_names",
    "register_source",
    "registered_entities",
    "unregister_names",
    "unregister_source",
]
