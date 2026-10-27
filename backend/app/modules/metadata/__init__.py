"""Metadata module (WP-026; architecture.md §6.1, §6.6): custom fields for every module.

Definitions live here; values live on each module's records (typed JSON). Licensed with the
`incident` feature while incidents are the only entity with custom fields.

Public interface for other modules:
- `definitions(session, entity)`: fields by key (types, choices, validation, retired);
- `clean(session, entity, values, current=, creating=, defaults=)`: checked values + problems;
- `problem_params(session, entity, problems)`: the limits value problems name ("Maximum is 5");
- `mark_used(session, entity, keys)`: fields that now hold values (only retirable from then);
- `filter_fields(session, entity, table)`: `custom.<key>` fields for the shared filter DSL;
- `text_for_search(session, entity, values)`: free text for the search port (WP-027).
"""

from app.core.modules import ModuleSpec
from app.modules.metadata.api.routes import router
from app.modules.metadata.domain.fields import (
    CustomFieldEntity,
    Definition,
    FieldType,
)
from app.modules.metadata.events import EVENTS
from app.modules.metadata.service.custom_fields import (
    clean,
    definitions,
    filter_fields,
    mark_used,
    problem_params,
    register_field_usage,
    text_for_search,
)
from app.modules.metadata.service.realtime import ROUTES

FEATURE = "incident"

module = ModuleSpec(
    name="metadata",
    routers=[router],
    events=EVENTS,
    feature=FEATURE,
    permissions=(),
    realtime=ROUTES,
)

__all__ = [
    "CustomFieldEntity",
    "Definition",
    "FieldType",
    "clean",
    "definitions",
    "filter_fields",
    "mark_used",
    "module",
    "problem_params",
    "register_field_usage",
    "text_for_search",
]
