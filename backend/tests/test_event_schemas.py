"""Event schema export and the breaking-change check (WP-007, events.md "Versioning")."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tooling import event_schemas

COMMITTED = Path(__file__).resolve().parents[2] / "docs/architecture/event-schemas.json"
LOGGED_IN = "identity_access.user.logged_in"


@pytest.fixture
def base() -> dict[str, Any]:
    return event_schemas.current_schemas()


def payload(schemas: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = schemas["events"][LOGGED_IN]["1"]
    return result


def test_committed_export_is_up_to_date(base: dict[str, Any]) -> None:
    assert COMMITTED.read_text(encoding="utf-8") == event_schemas.render(base), (
        "run `make events-schemas` and commit docs/architecture/event-schemas.json"
    )


def test_no_change_is_not_breaking(base: dict[str, Any]) -> None:
    assert event_schemas.breaking_changes(base, copy.deepcopy(base)) == []


def test_new_optional_field_and_doc_edits_are_allowed(base: dict[str, Any]) -> None:
    now = copy.deepcopy(base)
    payload(now)["properties"]["session_kind"] = {"type": "string", "default": "web"}
    payload(now)["properties"]["client"]["description"] = "reworded"
    payload(now)["description"] = "The class docstring changed too."
    now["events"]["identity_access.user.logged_in"]["2"] = {"type": "object"}
    assert event_schemas.breaking_changes(base, now) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda p: p["properties"].pop("client"), "field 'client' was removed"),
        (
            lambda p: p["properties"].__setitem__("client", {"type": "integer"}),
            "field 'client' changed type",
        ),
        (
            lambda p: (
                p["properties"].__setitem__("mfa", {"type": "boolean"}),
                p["required"].append("mfa"),
            ),
            "field 'mfa' became required",
        ),
        (lambda p: p["required"].remove("client"), "required field 'client' became optional"),
        (lambda p: p.update(additionalProperties=False), "schema options changed"),
    ],
)
def test_breaking_changes_are_reported(base: dict[str, Any], mutate: Any, expected: str) -> None:  # noqa: ANN401 - lambdas over JSON
    now = copy.deepcopy(base)
    mutate(payload(now))
    problems = event_schemas.breaking_changes(base, now)
    assert any(expected in p for p in problems), problems


def test_removing_a_published_version_is_breaking(base: dict[str, Any]) -> None:
    now = copy.deepcopy(base)
    del now["events"][LOGGED_IN]
    assert event_schemas.breaking_changes(base, now) == [
        f"{LOGGED_IN} v1: version was removed (published versions are forever)"
    ]


def test_changed_shared_definition_is_breaking() -> None:
    old = {"properties": {}, "$defs": {"Kind": {"enum": ["a", "b"]}}}
    new = {"properties": {}, "$defs": {"Kind": {"enum": ["a"]}}}
    assert event_schemas.compare_object("x", old, new) == ["x: shared definition 'Kind' changed"]


def test_cli_write_and_check(tmp_path: Path, base: dict[str, Any]) -> None:
    target = tmp_path / "schemas.json"
    assert event_schemas.main(["check", str(target)]) == 1  # missing file = out of date
    assert event_schemas.main(["write", str(target)]) == 0
    assert event_schemas.main(["check", str(target)]) == 0
    widened = copy.deepcopy(base)
    payload(widened)["properties"]["old_field"] = {"type": "string"}
    baseline = tmp_path / "main.json"
    baseline.write_text(json.dumps(widened), encoding="utf-8")
    # The target branch had a field this branch removed: CI fails even with a fresh export.
    assert event_schemas.main(["check", str(target), "--base", str(baseline)]) == 1
