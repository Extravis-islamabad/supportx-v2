"""The shared API conventions are visible in the published OpenAPI document (WP-008)."""

from app.main import create_app
from conftest import make_settings


def test_the_filter_dsl_schema_is_published() -> None:
    document = create_app(make_settings()).openapi()
    schemas = document["components"]["schemas"]
    assert {"FilterExpression", "FilterCondition", "FilterAnd", "FilterOr"} <= set(schemas)
    ops = schemas["FilterCondition"]["properties"]["op"]
    resolved = schemas[ops["$ref"].rsplit("/", 1)[-1]] if "$ref" in ops else ops
    assert {"eq", "between", "last_n_days", "starts_with"} <= set(resolved["enum"])
    (parameter,) = [
        p for p in document["paths"]["/api/v1/users"]["get"]["parameters"] if p["name"] == "filter"
    ]
    assert parameter["schema"]["contentSchema"] == {"$ref": "#/components/schemas/FilterExpression"}
    patch = document["paths"]["/api/v1/users/{user_id}"]["patch"]
    assert any(p["name"] == "If-Match" for p in patch["parameters"])
