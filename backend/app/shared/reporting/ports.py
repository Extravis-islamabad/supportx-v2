"""The reporting port (WP-035, ADR-033).

A module that owns a reportable entity registers a `SourceProvider`. For a signed-in subject it
returns a `ReportingSource`: the module's own list query with its scope filter already applied
(the very query the list uses), the filter allowlist, and which of those fields can be grouped
and how they are labelled. The analytics module only wraps that query in aggregates, so a report
can never count a record the viewer could not list (REQ-RPT-002, D-052), and analytics never
names another module's tables (CLAUDE.md rule e).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api.filters import ResourceFields


class DimensionKind(StrEnum):
    """How a groupable field's values are shown."""

    CODE = "code"  # built-in code: label key f"{label_prefix}.{code}"
    ADMIN_CODE = "admin_code"  # admin-defined code (status, level, custom choice): admin label
    REFERENCE = "reference"  # id of another record (group, site, user…): shown by its name
    DATETIME = "datetime"  # grouped by day, week, month, quarter or year in the viewer's zone
    NUMBER = "number"  # grouped by value; summed and averaged by measures
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class Dimension:
    """A field of the source that a report may group by."""

    kind: DimensionKind
    label_prefix: str | None = None  # CODE only, e.g. "priority"
    reference: str | None = None  # REFERENCE only: "group", "site", "department", "user"…


@dataclass(frozen=True)
class ReportingSource:
    """One entity, as the subject may see it."""

    entity: str
    # The module's scope-filtered list query. Analytics replaces its columns and adds WHERE,
    # GROUP BY and aggregates; it never removes the scope filter.
    rows: Select[Any]
    fields: ResourceFields  # the list's filter allowlist, custom fields included
    dimensions: Mapping[str, Dimension]  # keys are names in `fields`
    list_path: str  # drill-down opens this list with the same filter, e.g. "incidents"


class SourceProvider(Protocol):
    """Registered by the owning module at startup."""

    @property
    def entity(self) -> str:
        """Entity code, e.g. "incident"."""
        ...

    @property
    def feature(self) -> str:
        """Licence feature that must be on for the entity to be reported on."""
        ...

    @property
    def permission(self) -> str:
        """The list permission, e.g. "incidents.view"; reports need it too."""
        ...

    async def source(self, session: AsyncSession, subject: Any) -> ReportingSource:  # noqa: ANN401 - identity_access.Subject; shared code cannot import a module
        """The entity as `subject` may see it."""
        ...


class UnknownEntityError(LookupError):
    """No module has registered this entity."""


_PROVIDERS: dict[str, SourceProvider] = {}


def register_source(provider: SourceProvider) -> None:
    """Make an entity reportable (call from the owning module's startup)."""
    _PROVIDERS[provider.entity] = provider


def unregister_source(entity: str) -> None:
    """Undo `register_source` (module shutdown, tests)."""
    _PROVIDERS.pop(entity, None)


def provider_for(entity: str) -> SourceProvider:
    """The provider of `entity`; UnknownEntityError when none is registered."""
    try:
        return _PROVIDERS[entity]
    except KeyError:
        raise UnknownEntityError(entity) from None


def registered_entities() -> tuple[str, ...]:
    """Entities that can be reported on in this process."""
    return tuple(sorted(_PROVIDERS))
