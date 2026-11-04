"""OpenAPI additions for the shared API conventions (WP-008).

The `filter` query parameter is a JSON document. FastAPI can only describe it as a string, so
this hook publishes the DSL's JSON Schema as `components.schemas.FilterExpression` (and its parts)
and points every `filter` parameter at it, so the frontend gets generated TypeScript types.
"""

from collections.abc import Callable, Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic.json_schema import models_json_schema

from app.core.authorization import declared_access
from app.core.scopes import scope_of
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


# --- security schemes and scopes (WP-041, D-128) ---------------------------------------------

SESSION_SCHEME = "BrowserSession"
KEY_SCHEME = "ApiKey"


def _dependencies(dependant: Any) -> Iterator[Callable[..., Any]]:  # noqa: ANN401 - FastAPI Dependant
    stack = list(dependant.dependencies)
    while stack:
        current = stack.pop()
        if current.call is not None:
            yield current.call
        stack.extend(current.dependencies)


def route_access(app: FastAPI) -> dict[tuple[str, str], str]:
    """(method, path) → how the route is protected ('permission:<keys>', 'signed_in', 'public')."""
    found: dict[tuple[str, str], str] = {}
    for context in iter_route_contexts(app.routes):
        if not isinstance(context.original_route, APIRoute) or context.endpoint is None:
            continue
        access = declared_access(list(_dependencies(context.dependant)), context.endpoint)
        for method in context.methods or ():
            found[(method.lower(), str(context.path))] = access or "signed_in"
    return found


def add_security(document: dict[str, Any], access: dict[tuple[str, str], str]) -> dict[str, Any]:
    """Security schemes, and per operation who may call it and which key scopes reach it.

    A permission route takes a browser session or an API key holding one of its scopes
    (`x-scopes`); a signed-in-only route takes the browser session alone (`x-api-key: false`).
    """
    components = document.setdefault("components", {})
    components["securitySchemes"] = {
        SESSION_SCHEME: {
            "type": "apiKey",
            "in": "cookie",
            "name": "supportx_session",
            "description": "The screens' session (sign in through the browser); in production"
            " the cookie is __Host-supportx_session.",
        },
        KEY_SCHEME: {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "sxk_<tenant>_<key id>_<secret>",
            "description": "An API key (docs/api/keys.md).",
        },
    }
    for path, operations in document.get("paths", {}).items():
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            rule = access.get((method, path), "signed_in")
            if rule == "public":
                operation["security"] = []
            elif rule.startswith("permission:"):
                keys = rule.removeprefix("permission:").split(",")
                operation["security"] = [{SESSION_SCHEME: []}, {KEY_SCHEME: []}]
                operation["x-scopes"] = sorted({scope_of(k) for k in keys})
            else:
                operation["security"] = [{SESSION_SCHEME: []}]
                operation["x-api-key"] = False
    return document
