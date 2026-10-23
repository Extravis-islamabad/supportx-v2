"""OpenAPI breaking-change check (WP-008)."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tooling import openapi_diff

COMMITTED = Path(__file__).resolve().parents[2] / "frontend/packages/api-client/openapi.json"


@pytest.fixture
def base() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(COMMITTED.read_text(encoding="utf-8"))
    return document


def users_get(document: dict[str, Any]) -> dict[str, Any]:
    operation: dict[str, Any] = document["paths"]["/api/v1/users/{user_id}"]["get"]
    return operation


def user_detail(document: dict[str, Any]) -> dict[str, Any]:
    schema: dict[str, Any] = document["components"]["schemas"]["UserDetail"]
    return schema


def test_identical_and_additive_changes_pass(base: dict[str, Any]) -> None:
    now = copy.deepcopy(base)
    now["paths"]["/api/v1/new"] = {"get": {"responses": {"200": {"description": "x"}}}}
    user_detail(now)["properties"]["nickname"] = {"type": "string"}
    users_get(now)["parameters"].append({"name": "expand", "in": "query", "required": False})
    user_detail(now)["properties"]["email"]["description"] = "reworded"
    assert openapi_diff.breaking_changes(base, now) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d["paths"].pop("/api/v1/users/{user_id}"), "operation was removed"),
        (lambda d: user_detail(d)["properties"].pop("email"), "response.email was removed"),
        (
            lambda d: user_detail(d)["properties"].update(version={"type": "string"}),
            "response.version changed type",
        ),
        (
            lambda d: user_detail(d)["required"].remove("email"),
            "response.email became optional",
        ),
        (
            lambda d: users_get(d)["parameters"].append(
                {"name": "must", "in": "query", "required": True, "schema": {"type": "string"}}
            ),
            "new required parameter 'must'",
        ),
        (lambda d: users_get(d)["parameters"].pop(0), "was removed"),
    ],
)
def test_breaking_changes_are_reported(base: dict[str, Any], mutate: Any, expected: str) -> None:  # noqa: ANN401 - lambdas over JSON
    now = copy.deepcopy(base)
    mutate(now)
    problems = openapi_diff.breaking_changes(base, now)
    assert any(expected in p for p in problems), problems


def test_renamed_schema_is_breaking(base: dict[str, Any]) -> None:
    now = copy.deepcopy(base)
    now["components"]["schemas"]["UserView"] = now["components"]["schemas"].pop("UserDetail")
    assert "schema 'UserDetail' was removed or renamed" in openapi_diff.breaking_changes(base, now)


def test_new_required_body_field_is_breaking(base: dict[str, Any]) -> None:
    now = copy.deepcopy(base)
    patch = now["components"]["schemas"]["UserPreferencesPatch"]
    patch["required"] = ["signature"]
    problems = openapi_diff.breaking_changes(base, now)
    assert any("new required field 'signature'" in p for p in problems), problems


def test_cli(tmp_path: Path, base: dict[str, Any]) -> None:
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    old.write_text(json.dumps(base))
    new.write_text(json.dumps(base))
    assert openapi_diff.main([str(old), str(new)]) == 0
    broken = copy.deepcopy(base)
    broken["paths"].pop("/api/v1/users")
    new.write_text(json.dumps(broken))
    assert openapi_diff.main([str(old), str(new)]) == 1
    assert openapi_diff.main([str(old)]) == 2
