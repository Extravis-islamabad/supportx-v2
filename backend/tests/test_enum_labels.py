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
    # Reports (WP-035)
    "ChartType": "report_chart",
    "DateBucket": "report_bucket",
    "ResultOrder": "report_order",
    "ReportExportIn.content": "report_export_content",
    "ReportExportIn.format": "report_export_format",
    "ReportExportIn.language": "locale",
    "ReportExportOut.status": "report_export_status",
    "ReportSettingsOut.week_start": "report_week_start",
    "ReportSettingsPatch.week_start": "report_week_start",
    "AuditActorType": "audit_actor_type",
    "AuditCategory": "audit_category",
    "AuditClient": "audit_client",
    "AuditOutcome": "audit_outcome",
    "ExportFilter": "audit_export_filter",
    "AuditExportIn.format": "audit_export_format",
    "ReadCategory": "audit_read_category",
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
    "FormDensity": "form_density",
    "Op": "filter_op",
    "ReadinessResponse.status": "readiness_status",
    "StateReason": "entitlement_reason",
    "TenantStatus": "tenant_status",
    "UserDetail.locale": "locale",
    "UserDetail.status": "user_status",
    "UserOut.locale": "locale",
    "UserType": "user_type",
    "AccessSettingsIn.technician_scope": "technician_scope",
    "AccessSettingsOut.technician_scope": "technician_scope",
    "SsoBody.preset": "sso_preset",
    "SsoOut.preset": "sso_preset",
    "SsoOut.protocol": "sso_protocol",
    "SsoOut.state": "sso_state",
    "SsoTestResultOut.status": "sso_test_status",
    "ImportOut.file_format": "people_import_format",
    "ImportOut.match_on": "people_import_match",
    "ImportOut.status": "people_import_status",
    "Channel": "work_item_channel",
    "Impact": "impact",
    "Priority": "priority",
    "PrioritySource": "priority_source",
    "ReasonList": "reason_list",
    "ReasonMode": "reason_mode",
    "Scale": "scale",
    "StatusCategory": "status_category",
    "Urgency": "urgency",
    "WorkItemAction": "work_item_action",
    "PickList": "pick_list",
    "TemplateField": "work_item.field",
    "DeliveryReason": "delivery_reason",
    "DeliveryState": "delivery_state",
    "EntryKind": "entry_kind",
    "FirstResponseAction": "first_response_action",
    "FollowReason": "follow_reason",
    "ReplyMode": "reply_mode",
    "TypingIn.state": "typing_state",
    "Visibility": "visibility",
    "WorkItemHistoryEntryOut.actor_type": "actor_type",
    "WorkItemHistoryEntryOut.kind": "change_kind",
    "WorkItemHistoryEntryOut.source": "change_source",
    # Files (WP-022)
    "Disposition": "file_disposition",
    "FileState": "file_state",
    "Kind": "file_kind",
    "OwnerType": "file_owner_type",
    # Branding and domains (WP-017).
    "CheckCode": "branding.check",
    "DomainStatus": "domain_status",
    "TlsMode": "domain_tls_mode",
    "TlsStatus": "domain_tls_status",
    "StatusOut.warnings[]": "file_warning",
    # Custom fields (WP-026)
    "ChoiceDisplay": "custom_field_display",
    "CustomFieldEntity": "custom_field_entity",
    "FieldType": "custom_field_type",
    "IndexState": "custom_field_index_state",
    "IndexFailure": "custom_field_index_error",
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
