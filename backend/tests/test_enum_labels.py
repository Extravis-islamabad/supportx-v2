"""Every enum value the API can send has an English and an Arabic label (CLAUDE.md rule d, WP-010).

Walks the OpenAPI contract as the code builds it (`tooling.export_openapi.build_schema`; the
file is generated, never committed, D-127) and finds every enum: named schemas (`UserType`) and
inline property enums (`UserDetail.status`). Each must be mapped to a label prefix below, and
every value must have a label `<prefix>.<value>` in en and ar. A new enum without a mapping
fails here, so nobody ships a code the UI cannot translate. Error codes, event types and the
licence catalogue have their own checks (test_error_labels.py, test_event_labels.py,
test_licensing_labels.py).
"""

from collections.abc import Iterator
from typing import Any

import pytest

from tests.test_error_labels import label_keys

# Enum location in the contract -> label prefix the UI uses.
ENUM_PREFIXES: dict[str, str] = {
    "InstanceOut.status": "workflow_instance_status",  # WP-048b
    "JobIn.kind": "workflow_job_kind",  # WP-048b S3
    "JobOut.kind": "workflow_job_kind",
    "JobOut.status": "workflow_job_status",
    "WaitEvent": "workflow_wait_event",  # S3e: the change a test run hears
    "TestRunOut.status": "workflow_instance_status",  # S3e: a test run's states are a run's
    "NodeType": "workflow_node_type",  # S4: the designer's palette
    "NodeCategory": "workflow_node_category",
    "AiSettingsOut.summary_sources[]": "ai_summary_source",
    "DuplicateOut.reasons[]": "duplicate_reason",
    "DuplicatesOut.method": "duplicate_method",
    "WritingIn.kind": "ai_writing_kind",
    "WritingIn.mode": "ai_writing_mode",
    # AI gateway (WP-037)
    "AiArea": "ai_area",
    # Problems' evidence panel (WP-044b)
    "EvidenceSource": "problem_evidence_source",
    "ApprovalPurpose": "approval_purpose",
    "RecipientSet": "problem_recipient_set",
    "CopyPart": "problem_follow_up_copy",
    "OutcomeIn.outcome": "ai_outcome",
    # Asset catalogue (WP-049a)
    "AssetAgeBasis": "asset_age_basis",
    "AssetDepreciationMethod": "asset_depreciation",
    # The asset list's built-in views (WP-049b s4a)
    "AssetView": "asset_view",
    # Asset financials (WP-049b s2)
    "DepreciationChoice": "asset_depreciation",
    "CostKind": "asset_cost_kind",
    "TermsSource": "asset_terms_source",
    # Labels, audits, scans and the overdue rule (WP-049b s3)
    "AssetChangeOriginOut.kind": "asset_change_origin",
    "AssetChangeOriginOut.reason_code": "asset_change_reason",
    "AuditFix": "asset_audit_fix",
    "AuditItemKind": "asset_audit_item_kind",
    "AuditItemResult": "asset_audit_result",
    "AuditKind": "asset_audit_kind",
    "AuditMarkMethod": "asset_audit_method",
    "AuditScanIn.result": "asset_audit_result",
    "AuditState": "asset_audit_state",
    "AuditHolderIn.kind": "asset_holder_kind",
    "LabelJobStatus": "asset_label_job_status",
    "LabelLayout": "asset_label_layout",
    "LabelTarget": "asset_label_target",
    "LabelsIn.language": "locale",
    "OverdueAction": "asset_overdue_action",
    "ScanFailure": "asset_scan_failure",
    "ScanResult": "asset_scan_result",
    "ScanSource": "asset_scan_source",
    "ScanType": "asset_scan_type",
    "Symbology": "asset_label_symbology",
    "AssetStateCategory": "asset_state_category",
    "AssetDisposalIn.method": "asset_disposal_method",
    "AssetHolderIn.kind": "asset_holder_kind",
    "AssetLinkIn.kind": "asset_link_kind",
    "AssetDisposalIn.components": "asset_components_choice",
    "AcknowledgementOut.status": "asset_ack_status",
    "AssetGroupIn.kind": "asset_group_kind",
    "LoanOut.status": "asset_loan_status",
    "LoanReturnIn.outcome": "asset_return_outcome",
    # WP-049b s1: the stock ledger and bookings ahead
    "AssetMovementOut.kind": "asset_movement_kind",
    "AssetAllocationIn.recipient_kind": "asset_recipient_kind",
    "AssetBookingOut.status": "asset_booking_status",
    "AssetBookingOut.channel": "asset_booking_channel",
    "AssetGroupOut.kind": "asset_group_kind",
    "AcknowledgementAnswerIn.channel": "asset_ack_channel",
    "AssetTypeCategory": "asset_type_category",
    "AssetTypeKind": "asset_type_kind",
    # SLA set-up (WP-025)
    "ActionKind": "sla_action_kind",
    "Anchor": "sla_level_anchor",
    "RecipientKind": "sla_recipient_kind",
    "HolidayPart": "sla_holiday_part",
    "CalendarSource": "sla_calendar_source",
    "PriorityRule": "sla_priority_rule",
    "ReopenRule": "sla_reopen_rule",
    "TargetKind": "sla_target_kind",
    # The record's SLA panel (WP-025 s2)
    "SlaTargetOut.kind": "sla_target_kind",
    "SlaTargetOut.state": "sla_target_state",
    "SlaLevelRunOut.anchor": "sla_level_anchor",
    "SlaLevelRunOut.state": "sla_run_state",
    "SlaTargetOut.met_how": "sla_met_how",
    "WorkItemSlaOut.reason": "sla_applied_reason",
    "TargetUnit": "sla_target_unit",
    "WeekPreset": "sla_week_preset",
    # Mailboxes (WP-024)
    "AfterFetch": "mailbox_after_fetch",
    "ConnectionSecurity": "mailbox_security",
    "MailboxCreates": "mailbox_creates",
    "MailboxState": "mailbox_state",
    "UnknownSenders": "mailbox_unknown_senders",
    # Microsoft 365 and Gmail mailboxes (WP-024 session 2)
    "MailboxProtocol": "mailbox_protocol",
    "AuthModel": "mailbox_auth_model",
    "CredentialKind": "mailbox_credential_kind",
    "WaitingOut.outcome": "mail_outcome",
    # Connector catalogue (WP-040)
    "ConnectorCategory": "connector_category",
    "ConnectorStatus": "connector_status",
    "SecretType": "secret_type",
    # Notifications (WP-023)
    "NotificationCategory": "notification_category",
    # Tasks, worklogs and links (WP-020e)
    "TaskStatus": "task_status",
    "TaskPriority": "task_priority",
    "WorklogType": "worklog_type",
    "LinkKind": "link_kind",
    "PortalSettingsOut.search_sources[]": "portal.search.group",
    "WorkItemTypeCode": "work_item_type",
    "WorkItemLinkOut.relation": "link_relation",
    "WorkItemTaskMoveIn.direction": "task_move_direction",
    # Incident lists and bulk jobs (WP-020d)
    "BulkAction": "bulk_action",
    "BulkOutcome": "bulk_outcome",
    "BulkStatus": "bulk_status",
    "ViewVisibility": "view_visibility",
    "NotificationChannel": "notification_channel",
    "ConditionOperator": "notification_condition_operator",
    "NotificationDeliveryOut.state": "notification_state",
    # Dashboard widgets, decision D-114
    "FlowSpec.bucket": "report_bucket",
    "RecordsSpec-Input.sort": "dashboard_records_sort",
    "RecordsSpec-Output.sort": "dashboard_records_sort",
    # Knowledge (WP-033)
    "ArticleIn.language": "locale",
    "ArticleIn.requesters": "kb_requesters",
    "ArticlePatch.requesters": "kb_requesters",
    "TopicIn.requesters": "kb_requesters",
    "TopicPatch.requesters": "kb_requesters",
    "VoteIn.reason": "kb_vote_reason",
    "RecordRef.how": "kb_link_source",
    # API keys (WP-041)
    "ApiKeyOut.status": "api_key_status",
    "ApiKeyCreatedOut.status": "api_key_status",
    "ScopeOut.access": "api_scope_access",
    # Knowledge on incidents (WP-033 session 4)
    "ApplyIn.audience": "kb_apply_audience",
    "ApplyIn.language": "locale",
    "ApplyIn.mode": "kb_apply_mode",
    "FindingOut.field": "kb_personal_field",
    "FindingOut.kind": "kb_personal_data",
    # Reports (WP-035)
    "ChartType": "report_chart",
    "DateBucket": "report_bucket",
    "ResultOrder": "report_order",
    "ReportExportIn.content": "report_export_content",
    "ReportExportIn.format": "report_export_format",
    "ExportFormatsOut.formats[]": "report_export_format",
    "ReportExportIn.language": "locale",
    "ReportRunIn.language": "locale",
    "ReportExportOut.status": "report_export_status",
    "ReportSettingsOut.week_start": "report_week_start",
    "ReportSettingsPatch.week_start": "report_week_start",
    "ReportScheduleIn.content": "report_export_content",
    "ReportScheduleIn.format": "report_export_format",
    "ReportScheduleIn.frequency": "report_frequency",
    "ReportScheduleOut.content": "report_export_content",
    "ReportScheduleOut.format": "report_export_format",
    "ReportScheduleOut.frequency": "report_frequency",
    "ReportScheduleOut.status": "report_schedule_status",
    "AuditActorType": "audit_actor_type",
    "AuditCategory": "audit_category",
    "AuditClient": "audit_client",
    "AuditOutcome": "audit_outcome",
    "FingerprintStatus": "audit_fingerprint_status",  # WP-064 S2 (ADR-046)
    "ExportFilter": "audit_export_filter",
    "AuditExportIn.format": "audit_export_format",
    "ReadCategory": "audit_read_category",
    "AnnouncementAction": "announcement_action",
    "AnnouncementAudience": "announcement_audience",
    "AnnouncementSeverity": "announcement_severity",
    "AnnouncementStatus": "announcement_status",
    "AnnouncementVisibility": "announcement_visibility",
    "HistoryEntryOut.actor_type": "actor_type",
    "KbHistoryEntryOut.actor_type": "actor_type",
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
    # Personal preferences (WP-042): the same labels as the shared theme and instance settings.
    "ThemeMode": "appearance.theme",
    "UserOut.week_start": "instance.week_start",
    "UserOut.time_format": "instance.time_format",
    "UserOut.digits": "preferences.digits",
    "UserOut.urdu_script": "preferences.urdu_script",
    "Op": "filter_op",
    "ReadinessResponse.status": "readiness_status",
    "ReadinessResponse.event_delivery": "event_delivery_state",
    "StateReason": "entitlement_reason",
    "TenantStatus": "tenant_status",
    "UserDetail.locale": "locale",
    "UserDetail.status": "user_status",
    "UserOut.locale": "locale",
    "UserType": "user_type",
    "PersonType": "user_type",  # the types a person can be given (WP-040: never `service`)
    "SyncScope": "sync_scope",  # who a directory syncs (WP-040 session 2)
    "Security": "ldap_security",  # how an AD/LDAP directory is reached (WP-040, D-118)
    "Vendor": "ldap_vendor",  # which kind of directory
    "EmailFrom": "email_from",
    "ActionMode": "rule_action_mode",
    "AssignMethod": "assign_method",
    "Availability": "availability",
    "RuleActionIO.kind": "rule_action_kind",
    "TriggerActionIO.kind": "trigger_action_kind",
    "RuleEvent": "rule_event",
    "RuleState": "rule_state",
    "TriggerEvent": "trigger_event",
    "Relative": "transition_relative",
    "TriggerActionKind": "trigger_action_kind",
    "LoopStop": "loop_stop",
    "FieldKind": "rule_field_kind",
    "IdentitySettingsOut.password_policy_state": "password_policy_state",
    "InvitationOut.status": "invitation_status",
    "InvitationOut.delivery": "invitation_delivery",
    "AccountSecurityOut.mfa_mode": "mfa_mode",
    "MfaRoleOut.mode": "mfa_mode",
    "SignInOut.method": "sign_in_method",
    "SignInOut.outcome": "sign_in_outcome",
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
    # The stage engine and releases (WP-058a)
    "RailState": "rail_state",
    "ReleaseRisk": "release_risk",
    "ChangeCopyIn.parts[]": "change_copy_part",  # WP-045a (REQ-CHG-003)
    "RiskLevel": "risk_level",  # WP-045b (REQ-CHG-056)
    "BoardRule": "change_board_rule",  # WP-045b S2 (REQ-CHG-042)
    "BoardChoice": "change_board_choice",  # WP-045b S3 (REQ-CHG-041)
    "WindowKind": "change_window_kind",  # WP-045c (REQ-CHG-075, -076)
    "WindowMode": "change_window_mode",  # WP-045c (REQ-CHG-077)
    "ConflictKind": "change_conflict",  # WP-045c (REQ-CHG-073, -074)
    "Watched": "reapproval_field",  # WP-045b S4 (REQ-CHG-053)
    "OnChange": "reapproval_effect",
    "StageOutcome": "stage_outcome",
    "DowntimePhase": "downtime_phase",
    "LevelRule": "approval_rule",
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
    # The service catalog (WP-030)
    "ApprovalStatus": "approval_status",
    "OnBehalfScope": "work_item_on_behalf_scope",
    # WP-030 s2: the approval engine.
    "ApprovalState": "approval_state",
    "ApproverOrigin": "approval_origin",
    "Decision": "approval_decision",
    "DecisionChannel": "approval_channel",
    "RouteReason": "approval_route_reason",
    "ApproverKind": "catalog_approver_kind",
    # catalog administration (WP-031)
    "ItemKind": "catalog_item_kind",
    "ItemStatus": "catalog_item_status",
    "QuestionAudience": "catalog_question_audience",
    "ItemAudience": "catalog_item_audience",
    "QuestionKind": "catalog_question_kind",
    "IndexFailure": "custom_field_index_error",
    # The portal (WP-028)
    "PortalStatus": "portal_status",
    "KnownProblem": "known_problem",  # WP-044c D15 (REQ-PRB-075)
    # WP-044c D16 (REQ-PRB-068): repeat incident rules
    "RepeatRuleOut.match": "repeat_match",
    "RepeatRuleIn.match": "repeat_match",
    "RepeatRulePatch.match": "repeat_match",
    "RepeatHandleIn.outcome": "repeat_outcome",
    "PortalReach": "portal_reach",
    "PortalState": "portal_state",
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


@pytest.fixture
def contract_enums(openapi_contract: dict[str, Any]) -> list[tuple[str, list[str]]]:
    return list(enums(openapi_contract["components"]["schemas"]))


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
