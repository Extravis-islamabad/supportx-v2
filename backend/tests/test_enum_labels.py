"""Every enum value the API can send has an English and an Arabic label (CLAUDE.md rule d, WP-010).

Walks the committed OpenAPI contract (frontend/packages/api-client/openapi.json, kept in sync by
the drift check) and finds every enum: named schemas (`UserType`) and inline property enums
(`UserDetail.status`). Each must be mapped to a label prefix below, and every value must have a
label `<prefix>.<value>` in en and ar. A new enum without a mapping fails here, so nobody ships a
code the UI cannot translate. Error codes, event types and the licence catalogue have their own
checks (test_error_labels.py, test_event_labels.py, test_licensing_labels.py).
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.test_error_labels import label_keys

OPENAPI = Path(__file__).resolve().parents[2] / "frontend/packages/api-client/openapi.json"

# Enum location in the contract -> label prefix the UI uses.
ENUM_PREFIXES: dict[str, str] = {
    "AnnouncementAction": "announcement_action",
    "AnnouncementAudience": "announcement_audience",
    "AnnouncementSeverity": "announcement_severity",
    "AnnouncementStatus": "announcement_status",
    "AnnouncementVisibility": "announcement_visibility",
    "HistoryEntryOut.actor_type": "actor_type",
    "HistoryEntryOut.kind": "change_kind",
    "HistoryEntryOut.source": "change_source",
    "CheckStatus": "check_status",
    "EffectivePermission.scope": "scope",
    "EffectivePermission.scopes[]": "scope",
    "GrantIO.scope": "scope",
    "PermissionOut.scopes[]": "scope",
    "Edition": "edition",
    "EntitlementState": "entitlement_state",
    "FailureReason": "failure_reason",
    "Feature": "feature",
    "LimitKey": "limit",
    "NavLayout": "nav_layout",
    "Op": "filter_op",
    "ReadinessResponse.status": "readiness_status",
    "StateReason": "entitlement_reason",
    "TenantStatus": "tenant_status",
    "UserDetail.locale": "locale",
    "UserDetail.status": "user_status",
    "UserOut.locale": "locale",
    "UserType": "user_type",
}


def enums(schemas: dict[str, Any]) -> Iterator[tuple[str, list[str]]]:
    """(location, values) for every enum in the component schemas."""
    for name, schema in schemas.items():
        if "enum" in schema:
            yield name, schema["enum"]
        for prop, spec in schema.get("properties", {}).items():
            if "enum" in spec:
                yield f"{name}.{prop}", spec["enum"]
            if "enum" in spec.get("items", {}):  # list of codes, e.g. scopes: [...]
                yield f"{name}.{prop}[]", spec["items"]["enum"]


@pytest.fixture(scope="module")
def contract_enums() -> list[tuple[str, list[str]]]:
    return list(enums(json.loads(OPENAPI.read_text(encoding="utf-8"))["components"]["schemas"]))


def test_every_enum_in_the_contract_has_a_label_prefix(
    contract_enums: list[tuple[str, list[str]]],
) -> None:
    unmapped = sorted(location for location, _ in contract_enums if location not in ENUM_PREFIXES)
    assert unmapped == [], "add these to ENUM_PREFIXES (and their labels)"
    assert len(contract_enums) >= 14  # the walker must find the enums at all


@pytest.mark.parametrize("locale", ["en", "ar"])
def test_every_enum_value_has_a_label(
    locale: str, contract_enums: list[tuple[str, list[str]]]
) -> None:
    keys = label_keys(locale)
    missing = sorted(
        f"{ENUM_PREFIXES[location]}.{value}"
        for location, values in contract_enums
        if location in ENUM_PREFIXES
        for value in values
        if f"{ENUM_PREFIXES[location]}.{value}" not in keys
    )
    assert missing == [], f"add these keys to packages/labels/src/resources/{locale}.ts"
