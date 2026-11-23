"""Every kind of object the audit log names has a label (rule d; settings QA AUD-01).

The log's "On" column and the entry drawer show `audit.object.<type>`. A missing key fell back to
the code title-cased ("Sla Holiday List"). Types are collected from the code itself: literal
`object_type="..."` arguments, and every `audited(...)` route of the running app (work items
build theirs per record type, e.g. `incident_settings`), so a new one without labels fails here.
"""

import re
from pathlib import Path

import pytest

from app.main import create_app
from conftest import make_settings
from tests.test_audit_routes import _audit_spec
from tests.test_error_labels import label_keys
from tooling.route_permissions import api_routes

APP_DIR = Path(__file__).resolve().parents[1] / "app"
_LITERAL = re.compile(r"object_type=\"([a-z_]+)\"")


def object_types() -> set[str]:
    found: set[str] = set()
    for source in APP_DIR.rglob("*.py"):
        if "tests" not in source.parts:
            found |= set(_LITERAL.findall(source.read_text(encoding="utf-8")))
    for _method, _path, dependant, _endpoint in api_routes(create_app(make_settings())):
        spec = _audit_spec(dependant)
        if spec is not None and spec.object_type is not None:
            found.add(spec.object_type)
    return found


def test_the_scan_finds_literal_and_built_types() -> None:
    assert {"role", "sla_holiday_list", "incident_settings"} <= object_types()


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_every_audited_object_type_has_a_label(locale: str) -> None:
    keys = label_keys(locale)
    missing = sorted(f"audit.object.{t}" for t in object_types() if f"audit.object.{t}" not in keys)
    assert missing == [], f"add these keys to packages/labels/src/resources/audit/{locale}.ts"
