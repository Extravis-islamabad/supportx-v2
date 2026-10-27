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


def test_enum_values_may_be_added_not_removed(base: dict[str, Any]) -> None:
    def limit_key(document: dict[str, Any]) -> list[str]:
        values: list[str] = document["components"]["schemas"]["LimitKey"]["enum"]
        return values

    grown = copy.deepcopy(base)
    limit_key(grown).append("new_limit")
    assert openapi_diff.breaking_changes(base, grown) == []
    shrunk = copy.deepcopy(base)
    limit_key(shrunk).pop(0)
    problems = openapi_diff.breaking_changes(base, shrunk)
    assert any("lost enum values" in p for p in problems), problems


def test_a_parameter_may_accept_a_new_enum_value_not_lose_one(base: dict[str, Any]) -> None:
    """D-084 for parameters too (WP-017 added `branding` to the upload's owner_type)."""

    def owner_type(document: dict[str, Any]) -> list[str]:
        values: list[str] = document["components"]["schemas"]["OwnerType"]["enum"]
        return values

    grown = copy.deepcopy(base)
    owner_type(grown).append("new_owner")
    assert openapi_diff.breaking_changes(base, grown) == []
    shrunk = copy.deepcopy(base)
    owner_type(shrunk).remove("draft")
    problems = openapi_diff.breaking_changes(base, shrunk)
    assert any("parameter 'owner_type' changed type" in p for p in problems), problems


def test_a_map_keyed_by_codes_may_gain_a_key_code_not_lose_one(base: dict[str, Any]) -> None:
    """D-084 for maps keyed by an enum too (WP-021 added `department_id` to TemplateField)."""

    def template_field(document: dict[str, Any]) -> list[str]:
        values: list[str] = document["components"]["schemas"]["TemplateField"]["enum"]
        return values

    grown = copy.deepcopy(base)
    template_field(grown).append("new_field")
    assert openapi_diff.breaking_changes(base, grown) == []
    shrunk = copy.deepcopy(base)
    template_field(shrunk).pop(0)
    problems = openapi_diff.breaking_changes(base, shrunk)
    assert any("{key} lost enum values" in p for p in problems), problems


def test_a_request_field_may_accept_more_a_response_field_may_not(base: dict[str, Any]) -> None:
    """Sending a value that was valid stays valid; receiving a null the client never saw is not."""
    plain = {"type": "string", "maxLength": 200}
    nullable = {"anyOf": [plain, {"type": "null"}]}

    def with_field(where: str, schema: dict[str, Any]) -> dict[str, Any]:
        document = copy.deepcopy(base)
        document["components"]["schemas"][where]["properties"]["probe"] = schema
        return document

    request, response = "UserPreferencesPatch", "UserDetail"
    assert (
        openapi_diff.breaking_changes(with_field(request, plain), with_field(request, nullable))
        == []
    )
    problems = openapi_diff.breaking_changes(
        with_field(response, plain), with_field(response, nullable)
    )
    assert any("probe changed type" in p for p in problems), problems


def test_accepted_breaks_need_a_decision_and_a_date() -> None:
    """D-095: an accepted break names the decision and the date that accepted it."""
    accepted, errors = openapi_diff.accepted_breaks(
        {
            "public_api_released": False,
            "accepted": [
                {"break": "x changed type", "decision": "D-095", "date": "2026-10-27"},
                {"break": "y changed type", "decision": "later", "date": "soon"},
            ],
        }
    )
    assert accepted == {"x changed type", "y changed type"}
    assert len(errors) == 2


def test_after_the_public_api_release_the_list_must_be_empty() -> None:
    """D-095: from the first external API release on, a breaking change means /api/v2."""
    entry = {"break": "x changed type", "decision": "D-095", "date": "2026-10-27"}
    _, errors = openapi_diff.accepted_breaks({"public_api_released": True, "accepted": [entry]})
    assert any("/api/v2" in error for error in errors)
    _, errors = openapi_diff.accepted_breaks({"public_api_released": True, "accepted": []})
    assert errors == []


def test_the_committed_list_is_valid() -> None:
    """The real list (docs/architecture/openapi-accepted-breaks.json) passes its own rules."""
    rules = json.loads(openapi_diff.ACCEPTED_FILE.read_text(encoding="utf-8"))
    assert openapi_diff.accepted_breaks(rules)[1] == []


def test_cli_reports_accepted_breaks_without_failing(
    tmp_path: Path, base: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    rules = json.loads(openapi_diff.ACCEPTED_FILE.read_text(encoding="utf-8"))
    if not rules["accepted"]:
        pytest.skip("no accepted breaks right now")
    old = copy.deepcopy(base)
    old["components"]["schemas"]["UnitIn"] = {"type": "object"}  # what the list accepts
    (tmp_path / "old.json").write_text(json.dumps(old))
    (tmp_path / "new.json").write_text(json.dumps(base))
    assert openapi_diff.main([str(tmp_path / "old.json"), str(tmp_path / "new.json")]) == 0
    assert "ACCEPTED schema 'UnitIn' was removed or renamed" in capsys.readouterr().out
