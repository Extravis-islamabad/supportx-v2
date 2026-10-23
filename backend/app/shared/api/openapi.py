"""OpenAPI additions for the shared API conventions (WP-008).

The `filter` query parameter is a JSON document. FastAPI can only describe it as a string, so
this hook publishes the DSL's JSON Schema as `components.schemas.FilterExpression` (and its parts)
and points every `filter` parameter at it, so the frontend gets generated TypeScript types.
"""

from typing import Any

from pydantic.json_schema import models_json_schema

from app.shared.api.filters import FilterAnd, FilterCondition, FilterExpression, FilterOr

REF_TEMPLATE = "#/components/schemas/{model}"


def add_filter_schema(document: dict[str, Any]) -> dict[str, Any]:
    """Add the DSL schemas and link `filter` parameters to them (mutates and returns `document`)."""
    _, definitions = models_json_schema(
        [
            (FilterExpression, "validation"),
            (FilterCondition, "validation"),
            (FilterAnd, "validation"),
            (FilterOr, "validation"),
        ],
        ref_template=REF_TEMPLATE,
    )
    schemas = document.setdefault("components", {}).setdefault("schemas", {})
    schemas.update(definitions.get("$defs", {}))
    expression = schemas.get("FilterExpression", {})
    root = expression.get("properties", {}).get("root")
    if root is not None:
        # Publish the node union itself under the wrapper's name: that is what `filter` holds.
        schemas["FilterExpression"] = {**root, "title": "FilterExpression"}
    for path in document.get("paths", {}).values():
        for operation in path.values():
            for parameter in operation.get("parameters", []) if isinstance(operation, dict) else []:
                if parameter.get("in") == "query" and parameter.get("name") == "filter":
                    parameter["schema"] = {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "title": "Filter",
                        "description": "JSON text of a FilterExpression.",
                        "contentMediaType": "application/json",
                        "contentSchema": {"$ref": REF_TEMPLATE.format(model="FilterExpression")},
                    }
    return document
