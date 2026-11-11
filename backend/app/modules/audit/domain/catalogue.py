"""What the audit log records: actions, categories, outcomes, actor types (REQ-AUD-002, 003).

Every action is a stable lowercase code with labels in en/ar/ur (`audit.action.<code>`); the UI
never shows the code itself. New privileged routes add their action here and mark the route
with `audited(...)` (an architecture test fails otherwise).
"""

from dataclasses import dataclass
from enum import StrEnum

from app.modules.audit.domain.lifecycle import RECORD_TYPES


class AuditCategory(StrEnum):
    """Groups of actions, used in filters and for the read-logging switches."""

    SESSION = "session"
    ACCESS = "access"
    ORGANISATION = "organisation"
    CONFIGURATION = "configuration"
    RECORDS = "records"
    SECURITY = "security"
    DATA = "data"
    LICENCE = "licence"
    READS = "reads"


class AuditOutcome(StrEnum):
    """Done, refused (permission, licence, read-only, step-up) or failed (validation, error)."""

    DONE = "done"
    REFUSED = "refused"
    FAILED = "failed"


class AuditActorType(StrEnum):
    """Who acted. Only `person` has a user ID; the others name the kind of actor."""

    PERSON = "person"
    SERVICE_ACCOUNT = "service_account"
    API_KEY = "api_key"
    AI_AGENT = "ai_agent"
    AUTOMATION = "automation"
    SYSTEM = "system"
    VENDOR_SUPPORT = "vendor_support"


class AuditClient(StrEnum):
    """Where the request came from."""

    CONSOLE = "console"
    PORTAL = "portal"
    MOBILE = "mobile"
    API = "api"
    WORKER = "worker"


class ReadCategory(StrEnum):
    """Kinds of sensitive reads that can be logged (REQ-AUD-004). Defaults in DEFAULT_READS."""

    AUDIT_LOG = "audit_log"
    ACCESS_INFORMATION = "access_information"
    SECURITY_SETTINGS = "security_settings"
    SECRETS = "secrets"
    EXPORTS = "exports"


# On for every new tenant; an admin can switch any of them off except the audit log itself.
DEFAULT_READS: frozenset[ReadCategory] = frozenset(ReadCategory)
ALWAYS_LOGGED_READS: frozenset[ReadCategory] = frozenset({ReadCategory.AUDIT_LOG})


@dataclass(frozen=True)
class Action:
    """One kind of audited action."""

    code: str
    category: AuditCategory
    module: str


def _actions(*items: tuple[str, AuditCategory, str]) -> dict[str, Action]:
    return {code: Action(code, category, module) for code, category, module in items}


ACTIONS: dict[str, Action] = _actions(
    # sign-in and session (failed sign-ins, MFA and password resets come with WP-039)
    ("session.signed_in", AuditCategory.SESSION, "identity_access"),
    ("session.quick_sign_in", AuditCategory.SESSION, "identity_access"),  # dev only (D-151)
    ("session.signed_out", AuditCategory.SESSION, "identity_access"),
    ("session.tenant_switched", AuditCategory.SESSION, "identity_access"),
    ("session.ended", AuditCategory.SESSION, "identity_access"),  # one session ended from a list
    # roles and access
    ("role.created", AuditCategory.ACCESS, "identity_access"),
    ("role.updated", AuditCategory.ACCESS, "identity_access"),
    ("role.deleted", AuditCategory.ACCESS, "identity_access"),
    ("user.role_assigned", AuditCategory.ACCESS, "identity_access"),
    ("user.role_removed", AuditCategory.ACCESS, "identity_access"),
    ("role.group_added", AuditCategory.ACCESS, "identity_access"),
    ("role.group_removed", AuditCategory.ACCESS, "identity_access"),
    ("organization.settings_changed", AuditCategory.CONFIGURATION, "organization"),
    ("user.preferences_changed", AuditCategory.ACCESS, "identity_access"),
    ("user.contact_changed", AuditCategory.ACCESS, "identity_access"),  # WP-028, REQ-PRT-013
    # API keys (WP-041, D-128): made, revoked, refused (address not allowed), the tenant's rules
    ("api_key.created", AuditCategory.SECURITY, "identity_access"),
    ("api_key.revoked", AuditCategory.SECURITY, "identity_access"),
    ("api_key.refused", AuditCategory.SECURITY, "identity_access"),
    ("api_key.settings_changed", AuditCategory.SECURITY, "identity_access"),
    # automation (WP-029)
    ("automation.rule_created", AuditCategory.CONFIGURATION, "automation"),
    ("automation.rule_changed", AuditCategory.CONFIGURATION, "automation"),
    ("automation.rule_deleted", AuditCategory.CONFIGURATION, "automation"),
    ("automation.rules_reordered", AuditCategory.CONFIGURATION, "automation"),
    ("automation.trigger_created", AuditCategory.CONFIGURATION, "automation"),
    ("automation.trigger_changed", AuditCategory.CONFIGURATION, "automation"),
    ("automation.trigger_deleted", AuditCategory.CONFIGURATION, "automation"),
    ("automation.triggers_reordered", AuditCategory.CONFIGURATION, "automation"),
    ("automation.transition_saved", AuditCategory.CONFIGURATION, "automation"),
    # workflows on a record (WP-048b S3a; REQ-WF-026)
    ("automation.workflow_stopped", AuditCategory.RECORDS, "automation"),
    ("automation.workflow_restarted", AuditCategory.RECORDS, "automation"),
    ("automation.workflow_retried", AuditCategory.RECORDS, "automation"),
    ("automation.workflow_skipped", AuditCategory.RECORDS, "automation"),  # WP-048b S5
    ("automation.workflow_job_queued", AuditCategory.RECORDS, "automation"),  # bulk (S3b)
    ("automation.workflow_copied", AuditCategory.CONFIGURATION, "automation"),  # S3d
    ("automation.workflow_imported", AuditCategory.CONFIGURATION, "automation"),
    ("automation.workflow_exported", AuditCategory.DATA, "automation"),
    ("automation.workflow_deleted", AuditCategory.CONFIGURATION, "automation"),
    # A test run's one live call (S3e): who, which node, which record (the route's details).
    ("automation.workflow_test_live_call", AuditCategory.RECORDS, "automation"),
    ("automation.transition_reset", AuditCategory.CONFIGURATION, "automation"),
    ("automation.routing_created", AuditCategory.CONFIGURATION, "automation"),
    ("automation.routing_changed", AuditCategory.CONFIGURATION, "automation"),
    ("automation.routing_deleted", AuditCategory.CONFIGURATION, "automation"),
    ("automation.routing_reordered", AuditCategory.CONFIGURATION, "automation"),
    ("automation.routing_settings_changed", AuditCategory.CONFIGURATION, "automation"),
    ("automation.assignment_changed", AuditCategory.CONFIGURATION, "automation"),
    ("automation.availability_changed", AuditCategory.ACCESS, "automation"),
    # SLA set-up (WP-025)
    ("sla.calendar_created", AuditCategory.CONFIGURATION, "sla"),
    ("sla.calendar_changed", AuditCategory.CONFIGURATION, "sla"),
    ("sla.calendar_deleted", AuditCategory.CONFIGURATION, "sla"),
    ("sla.special_hours_changed", AuditCategory.CONFIGURATION, "sla"),
    ("sla.holiday_list_created", AuditCategory.CONFIGURATION, "sla"),
    ("sla.holiday_list_changed", AuditCategory.CONFIGURATION, "sla"),
    ("sla.holiday_list_deleted", AuditCategory.CONFIGURATION, "sla"),
    ("sla.holidays_changed", AuditCategory.CONFIGURATION, "sla"),
    ("sla.holidays_imported", AuditCategory.CONFIGURATION, "sla"),
    ("sla.holidays_copied", AuditCategory.CONFIGURATION, "sla"),
    ("sla.policy_created", AuditCategory.CONFIGURATION, "sla"),
    ("sla.policy_changed", AuditCategory.CONFIGURATION, "sla"),
    ("sla.policy_deleted", AuditCategory.CONFIGURATION, "sla"),
    ("sla.policies_reordered", AuditCategory.CONFIGURATION, "sla"),
    ("sla.settings_changed", AuditCategory.CONFIGURATION, "sla"),
    # people (WP-021)
    ("user.created", AuditCategory.ACCESS, "identity_access"),
    ("user.changed", AuditCategory.ACCESS, "identity_access"),
    ("user.type_changed", AuditCategory.ACCESS, "identity_access"),
    ("user.sign_in_changed", AuditCategory.ACCESS, "identity_access"),
    ("user.deactivated", AuditCategory.ACCESS, "identity_access"),
    ("user.reactivated", AuditCategory.ACCESS, "identity_access"),
    ("people.import_started", AuditCategory.ACCESS, "identity_access"),
    ("access.settings_changed", AuditCategory.ACCESS, "identity_access"),
    # organisation
    ("site.created", AuditCategory.ORGANISATION, "organization"),
    ("site.renamed", AuditCategory.ORGANISATION, "organization"),
    ("site.member_added", AuditCategory.ORGANISATION, "organization"),
    ("site.member_removed", AuditCategory.ORGANISATION, "organization"),
    ("group.created", AuditCategory.ORGANISATION, "organization"),
    ("group.renamed", AuditCategory.ORGANISATION, "organization"),
    ("group.member_added", AuditCategory.ORGANISATION, "organization"),
    ("group.member_removed", AuditCategory.ORGANISATION, "organization"),
    # WP-021: details, inactive, removal; departments and desks.
    ("site.changed", AuditCategory.ORGANISATION, "organization"),
    ("site.deleted", AuditCategory.ORGANISATION, "organization"),
    ("group.changed", AuditCategory.ORGANISATION, "organization"),
    ("group.deleted", AuditCategory.ORGANISATION, "organization"),
    ("department.created", AuditCategory.ORGANISATION, "organization"),
    ("department.changed", AuditCategory.ORGANISATION, "organization"),
    ("department.deleted", AuditCategory.ORGANISATION, "organization"),
    ("desk.created", AuditCategory.CONFIGURATION, "organization"),
    ("desk.changed", AuditCategory.CONFIGURATION, "organization"),
    # branding and addresses (WP-017)
    ("identity.settings_changed", AuditCategory.SECURITY, "identity_access"),
    # the service catalog (WP-030)
    ("catalog.item_changed", AuditCategory.CONFIGURATION, "service_catalog"),
    ("catalog.category_changed", AuditCategory.CONFIGURATION, "service_catalog"),
    # catalog administration (WP-031)
    ("catalog.item_deleted", AuditCategory.CONFIGURATION, "service_catalog"),
    ("catalog.item_scheduled", AuditCategory.CONFIGURATION, "service_catalog"),
    ("catalog.category_deleted", AuditCategory.CONFIGURATION, "service_catalog"),
    ("catalog.settings_changed", AuditCategory.CONFIGURATION, "service_catalog"),
    ("catalog.starter_seeded", AuditCategory.CONFIGURATION, "service_catalog"),
    ("catalog.starter_published", AuditCategory.CONFIGURATION, "service_catalog"),
    ("identity.password_policy_reapplied", AuditCategory.SECURITY, "identity_access"),
    ("identity.mfa_policy_changed", AuditCategory.SECURITY, "identity_access"),
    ("user.mfa_reset", AuditCategory.SECURITY, "identity_access"),
    ("sso.added", AuditCategory.SECURITY, "identity_access"),
    ("sso.updated", AuditCategory.SECURITY, "identity_access"),
    ("sso.tested", AuditCategory.SECURITY, "identity_access"),
    ("sso.switched_on", AuditCategory.SECURITY, "identity_access"),
    ("sso.switched_off", AuditCategory.SECURITY, "identity_access"),
    ("sso.removed", AuditCategory.SECURITY, "identity_access"),
    ("invitation.sent", AuditCategory.ACCESS, "identity_access"),
    ("invitation.resent", AuditCategory.ACCESS, "identity_access"),
    ("invitation.revoked", AuditCategory.ACCESS, "identity_access"),
    ("user.password_reset_forced", AuditCategory.SECURITY, "identity_access"),
    ("branding.updated", AuditCategory.CONFIGURATION, "organization"),
    ("domain.added", AuditCategory.CONFIGURATION, "organization"),
    ("domain.verified", AuditCategory.CONFIGURATION, "organization"),
    ("domain.removed", AuditCategory.CONFIGURATION, "organization"),
    ("domain.certificate_uploaded", AuditCategory.CONFIGURATION, "organization"),
    # configuration
    ("incident.settings_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("incident.category_created", AuditCategory.CONFIGURATION, "work_items"),
    ("incident.category_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("incident.template_created", AuditCategory.CONFIGURATION, "work_items"),
    ("incident.template_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("metadata.custom_field_created", AuditCategory.CONFIGURATION, "metadata"),
    ("metadata.custom_field_changed", AuditCategory.CONFIGURATION, "metadata"),
    ("metadata.custom_field_deleted", AuditCategory.CONFIGURATION, "metadata"),
    ("incident.reply_template_created", AuditCategory.CONFIGURATION, "work_items"),
    ("incident.reply_template_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("incident.reply_template_deleted", AuditCategory.CONFIGURATION, "work_items"),
    ("announcement.settings_changed", AuditCategory.CONFIGURATION, "announcements"),
    ("notification.rule_changed", AuditCategory.CONFIGURATION, "notifications"),
    ("notification.rule_reset", AuditCategory.CONFIGURATION, "notifications"),
    ("mailbox.created", AuditCategory.CONFIGURATION, "integrations"),
    ("mailbox.changed", AuditCategory.CONFIGURATION, "integrations"),
    ("mailbox.removed", AuditCategory.CONFIGURATION, "integrations"),
    ("mailbox.mail_released", AuditCategory.CONFIGURATION, "integrations"),
    ("mailbox.consent_started", AuditCategory.CONFIGURATION, "integrations"),
    ("mailbox.connected", AuditCategory.CONFIGURATION, "integrations"),
    ("mailbox.mail_discarded", AuditCategory.CONFIGURATION, "integrations"),
    ("directory.created", AuditCategory.CONFIGURATION, "integrations"),
    ("directory.changed", AuditCategory.CONFIGURATION, "integrations"),
    ("directory.removed", AuditCategory.CONFIGURATION, "integrations"),
    ("directory.sync_requested", AuditCategory.CONFIGURATION, "integrations"),
    # Every use of the supportx-federation account (WP-040, D-118; product owner 2026-11-03).
    ("directory.federation_applied", AuditCategory.CONFIGURATION, "integrations"),
    ("directory.federation_failed", AuditCategory.CONFIGURATION, "integrations"),
    ("directory.federation_removed", AuditCategory.CONFIGURATION, "integrations"),
    ("connector_settings.changed", AuditCategory.CONFIGURATION, "integrations"),  # D-041
    # record actions (REQ-WI-021)
    ("incident.deleted", AuditCategory.RECORDS, "work_items"),
    ("incident.restored", AuditCategory.RECORDS, "work_items"),
    # The showcase seed's step 6 (Haider, 2026-11-09): an older incident's SLA from creation.
    ("incident.sla_applied_from_creation", AuditCategory.RECORDS, "work_items"),
    ("incident.bulk_started", AuditCategory.RECORDS, "work_items"),
    ("incident.note_visibility_changed", AuditCategory.RECORDS, "work_items"),
    ("incident.closed_record_edited", AuditCategory.RECORDS, "work_items"),
    ("incident.due_date_changed", AuditCategory.RECORDS, "work_items"),
    # service requests (WP-030): the same actions, by the type's own code
    ("service_request.settings_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("portal.settings_changed", AuditCategory.CONFIGURATION, "work_items"),  # WP-032 D8
    ("approvals.settings_changed", AuditCategory.CONFIGURATION, "work_items"),  # D-146 chair
    ("service_request.category_created", AuditCategory.CONFIGURATION, "work_items"),
    ("service_request.category_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("service_request.template_created", AuditCategory.CONFIGURATION, "work_items"),
    ("service_request.template_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("service_request.reply_template_created", AuditCategory.CONFIGURATION, "work_items"),
    ("service_request.reply_template_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("service_request.reply_template_deleted", AuditCategory.CONFIGURATION, "work_items"),
    ("service_request.deleted", AuditCategory.RECORDS, "work_items"),
    ("service_request.restored", AuditCategory.RECORDS, "work_items"),
    # WP-030 s2: approval decisions and withdrawals (REQ-SR-025, -061).
    ("service_request.approval_decided", AuditCategory.RECORDS, "work_items"),
    ("service_request.withdrawn", AuditCategory.RECORDS, "work_items"),
    # WP-030 s3: a signed one-time action link was used, or refused (REQ-NTF-024).
    ("action_link.used", AuditCategory.SECURITY, "system"),
    ("service_request.bulk_started", AuditCategory.RECORDS, "work_items"),
    ("service_request.note_visibility_changed", AuditCategory.RECORDS, "work_items"),
    ("service_request.closed_record_edited", AuditCategory.RECORDS, "work_items"),
    ("service_request.due_date_changed", AuditCategory.RECORDS, "work_items"),
    # problems (WP-044a): the same actions, by the type's own code
    ("problem.settings_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("problem.category_created", AuditCategory.CONFIGURATION, "work_items"),
    ("problem.category_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("problem.template_created", AuditCategory.CONFIGURATION, "work_items"),
    ("problem.template_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("problem.reply_template_created", AuditCategory.CONFIGURATION, "work_items"),
    ("problem.reply_template_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("problem.reply_template_deleted", AuditCategory.CONFIGURATION, "work_items"),
    ("problem.deleted", AuditCategory.RECORDS, "work_items"),
    ("problem.restored", AuditCategory.RECORDS, "work_items"),
    ("problem.bulk_started", AuditCategory.RECORDS, "work_items"),
    ("problem.note_visibility_changed", AuditCategory.RECORDS, "work_items"),
    ("problem.closed_record_edited", AuditCategory.RECORDS, "work_items"),
    ("problem.due_date_changed", AuditCategory.RECORDS, "work_items"),
    # ADR-040: an investigator reaches a problem outside their own scope.
    ("problem.investigator_added", AuditCategory.RECORDS, "work_items"),
    ("problem.approval_requested", AuditCategory.RECORDS, "work_items"),  # WP-044b s4
    ("problem.approval_decided", AuditCategory.RECORDS, "work_items"),
    ("problem.investigator_removed", AuditCategory.RECORDS, "work_items"),
    # WP-044c D16 (REQ-PRB-068): repeat incident rules and what was done with their sets.
    ("problem.repeat_rule_created", AuditCategory.CONFIGURATION, "work_items"),
    ("problem.repeat_rule_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("problem.repeat_rule_removed", AuditCategory.CONFIGURATION, "work_items"),
    ("problem.repeat_hit_handled", AuditCategory.RECORDS, "work_items"),
    # releases (WP-058a): the same actions, by the type's own code
    ("release.settings_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("release.category_created", AuditCategory.CONFIGURATION, "work_items"),
    ("release.category_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("release.template_created", AuditCategory.CONFIGURATION, "work_items"),
    ("release.template_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("release.reply_template_created", AuditCategory.CONFIGURATION, "work_items"),
    ("release.reply_template_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("release.reply_template_deleted", AuditCategory.CONFIGURATION, "work_items"),
    ("release.deleted", AuditCategory.RECORDS, "work_items"),
    ("release.restored", AuditCategory.RECORDS, "work_items"),
    ("release.bulk_started", AuditCategory.RECORDS, "work_items"),
    ("release.note_visibility_changed", AuditCategory.RECORDS, "work_items"),
    ("release.closed_record_edited", AuditCategory.RECORDS, "work_items"),
    ("release.due_date_changed", AuditCategory.RECORDS, "work_items"),
    ("release.approval_decided", AuditCategory.RECORDS, "work_items"),
    # changes (WP-045a): the same actions, by the type's own code
    ("change.settings_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("change.board_changed", AuditCategory.CONFIGURATION, "work_items"),  # WP-045b S2
    ("change.approval_rerouted", AuditCategory.RECORDS, "work_items"),  # WP-045b S3
    ("change.sent_back_for_approval", AuditCategory.RECORDS, "work_items"),  # WP-045b S4
    ("change.emergency_override", AuditCategory.SECURITY, "work_items"),  # D-144
    ("change.window_changed", AuditCategory.CONFIGURATION, "work_items"),  # WP-045c
    ("change.freeze_override", AuditCategory.SECURITY, "work_items"),  # WP-045c, as D-144
    ("change.freeze_passed_by_cab", AuditCategory.SECURITY, "work_items"),  # D-156
    ("change.category_created", AuditCategory.CONFIGURATION, "work_items"),
    ("change.category_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("change.template_created", AuditCategory.CONFIGURATION, "work_items"),
    ("change.template_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("change.reply_template_created", AuditCategory.CONFIGURATION, "work_items"),
    ("change.reply_template_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("change.reply_template_deleted", AuditCategory.CONFIGURATION, "work_items"),
    ("change.deleted", AuditCategory.RECORDS, "work_items"),
    ("change.restored", AuditCategory.RECORDS, "work_items"),
    ("change.bulk_started", AuditCategory.RECORDS, "work_items"),
    ("change.note_visibility_changed", AuditCategory.RECORDS, "work_items"),
    ("change.closed_record_edited", AuditCategory.RECORDS, "work_items"),
    ("change.due_date_changed", AuditCategory.RECORDS, "work_items"),
    ("change.approval_decided", AuditCategory.RECORDS, "work_items"),
    # the audit log itself
    # Files (WP-022): names are personal data and never in details.
    ("file.uploaded", AuditCategory.RECORDS, "system"),
    ("file.deleted", AuditCategory.RECORDS, "system"),
    ("file.downloaded", AuditCategory.DATA, "system"),
    ("file.blocked", AuditCategory.SECURITY, "system"),
    ("file.rescan_requested", AuditCategory.SECURITY, "system"),
    ("file.purged", AuditCategory.DATA, "system"),
    ("file_settings.changed", AuditCategory.CONFIGURATION, "system"),
    ("audit.settings_changed", AuditCategory.SECURITY, "audit"),
    ("audit.verification_requested", AuditCategory.SECURITY, "audit"),
    ("audit.verification_failed", AuditCategory.SECURITY, "audit"),
    ("audit.probing_detected", AuditCategory.SECURITY, "audit"),
    ("audit.subject_erased", AuditCategory.DATA, "audit"),
    # One-off showcase repair (QA 2026-11-09): dates the old seed step moved, put back.
    ("work_item.dates_restored", AuditCategory.DATA, "work_items"),
    ("service_request.fulfiller_repaired", AuditCategory.DATA, "work_items"),  # D-154 E1
    ("work_item.settings_topped_up", AuditCategory.CONFIGURATION, "work_items"),
    ("audit.export_requested", AuditCategory.DATA, "audit"),
    ("audit.export_downloaded", AuditCategory.DATA, "audit"),
    ("audit.entries_archived", AuditCategory.DATA, "audit"),
    ("audit.archive_failed", AuditCategory.SECURITY, "audit"),
    ("audit.archive_restore_requested", AuditCategory.DATA, "audit"),
    # reports (WP-035): settings, and every export with its row count (REQ-RPT-058 AC3)
    ("report.settings_changed", AuditCategory.CONFIGURATION, "analytics"),
    ("report.exported", AuditCategory.DATA, "analytics"),
    ("report.export_downloaded", AuditCategory.DATA, "analytics"),
    # dashboards (WP-036): a role's home dashboard (what every holder of the role lands on)
    ("dashboard.role_home_set", AuditCategory.CONFIGURATION, "analytics"),
    # knowledge (WP-033 s2, REQ-KB-080): publishing, withdrawing, the trash and settings
    ("knowledge.article_approved", AuditCategory.RECORDS, "knowledge"),
    ("knowledge.article_withdrawn", AuditCategory.RECORDS, "knowledge"),
    ("knowledge.article_deleted", AuditCategory.RECORDS, "knowledge"),
    ("knowledge.article_restored", AuditCategory.RECORDS, "knowledge"),
    ("knowledge.settings_changed", AuditCategory.CONFIGURATION, "knowledge"),
    ("knowledge.type_created", AuditCategory.CONFIGURATION, "knowledge"),
    ("knowledge.type_changed", AuditCategory.CONFIGURATION, "knowledge"),
    # assets (WP-049a s1): the catalogue and the asset settings
    ("asset.settings_changed", AuditCategory.CONFIGURATION, "assets"),
    # Assets (WP-049a s2, REQ-AST-001 AC: privileged record actions).
    ("asset.created", AuditCategory.RECORDS, "assets"),
    ("asset.updated", AuditCategory.RECORDS, "assets"),
    ("asset.deleted", AuditCategory.RECORDS, "assets"),
    ("asset.restored", AuditCategory.RECORDS, "assets"),
    ("asset.moved", AuditCategory.RECORDS, "assets"),
    ("asset.disposed", AuditCategory.RECORDS, "assets"),
    ("asset.assigned", AuditCategory.RECORDS, "assets"),
    ("asset.unassigned", AuditCategory.RECORDS, "assets"),
    ("asset.linked", AuditCategory.RECORDS, "assets"),
    ("asset.unlinked", AuditCategory.RECORDS, "assets"),
    ("asset.loanable_set", AuditCategory.RECORDS, "assets"),
    ("asset_loan.created", AuditCategory.RECORDS, "assets"),
    ("asset_loan.returned", AuditCategory.RECORDS, "assets"),
    # WP-049b s1: consumable stock (REQ-AST-033, 034), minimum stock (035), bookings (032)
    ("asset_consumable.created", AuditCategory.RECORDS, "assets"),
    ("asset_consumable.updated", AuditCategory.RECORDS, "assets"),
    ("asset_consumable.deleted", AuditCategory.RECORDS, "assets"),
    ("asset_consumable.received", AuditCategory.RECORDS, "assets"),
    ("asset_consumable.allocated", AuditCategory.RECORDS, "assets"),
    ("asset_consumable.adjusted", AuditCategory.RECORDS, "assets"),
    ("asset_consumable.returned", AuditCategory.RECORDS, "assets"),
    ("asset_stock_rule.created", AuditCategory.CONFIGURATION, "assets"),
    ("asset_stock_rule.updated", AuditCategory.CONFIGURATION, "assets"),
    ("asset_stock_rule.deleted", AuditCategory.CONFIGURATION, "assets"),
    ("asset_booking.created", AuditCategory.RECORDS, "assets"),
    ("asset_booking.cancelled", AuditCategory.RECORDS, "assets"),
    ("asset_booking.handed_over", AuditCategory.RECORDS, "assets"),
    # WP-049b s2: an asset's cost lines (REQ-AST-036) and notes (REQ-AST-050).
    ("asset_cost.created", AuditCategory.RECORDS, "assets"),
    ("asset_cost.updated", AuditCategory.RECORDS, "assets"),
    ("asset_cost.deleted", AuditCategory.RECORDS, "assets"),
    ("asset_note.created", AuditCategory.RECORDS, "assets"),
    ("asset_note.updated", AuditCategory.RECORDS, "assets"),
    ("asset_note.deleted", AuditCategory.RECORDS, "assets"),
    # WP-049b s3: labels (REQ-AST-039), audits (042, 043), scan history (054), the overdue rule
    ("asset_label.requested", AuditCategory.RECORDS, "assets"),
    ("asset_label.reprinted", AuditCategory.RECORDS, "assets"),
    ("asset_label.downloaded", AuditCategory.DATA, "assets"),
    ("asset_audit.created", AuditCategory.RECORDS, "assets"),
    ("asset_audit.updated", AuditCategory.RECORDS, "assets"),
    ("asset_audit.started", AuditCategory.RECORDS, "assets"),
    ("asset_audit.closed", AuditCategory.RECORDS, "assets"),
    ("asset_audit.item_marked", AuditCategory.RECORDS, "assets"),
    ("asset_audit.fixes_applied", AuditCategory.RECORDS, "assets"),
    ("asset_overdue_rule.changed", AuditCategory.CONFIGURATION, "assets"),
    ("asset_overdue_rule.ran", AuditCategory.RECORDS, "assets"),
    ("asset_scan.cleaned_up", AuditCategory.DATA, "assets"),
    ("asset_group.created", AuditCategory.RECORDS, "assets"),
    ("asset_group.updated", AuditCategory.RECORDS, "assets"),
    ("asset_group.deleted", AuditCategory.RECORDS, "assets"),
    ("asset_group.members_added", AuditCategory.RECORDS, "assets"),
    ("asset_group.member_removed", AuditCategory.RECORDS, "assets"),
    ("asset.copied", AuditCategory.RECORDS, "assets"),
    # a save's lifecycle events that no route names (WP-064, domain/lifecycle.py)
    ("asset.relocated", AuditCategory.RECORDS, "assets"),
    ("asset.product_changed", AuditCategory.RECORDS, "assets"),
    # Vendors (REQ-PUR-001, WP-049a s2).
    ("vendor.created", AuditCategory.CONFIGURATION, "procurement"),
    ("vendor.updated", AuditCategory.CONFIGURATION, "procurement"),
    ("vendor.deleted", AuditCategory.CONFIGURATION, "procurement"),
    ("asset.state_saved", AuditCategory.CONFIGURATION, "assets"),
    ("asset.state_deleted", AuditCategory.CONFIGURATION, "assets"),
    ("asset.life_cycle_saved", AuditCategory.CONFIGURATION, "assets"),
    ("asset.life_cycle_deleted", AuditCategory.CONFIGURATION, "assets"),
    ("asset.product_type_saved", AuditCategory.CONFIGURATION, "assets"),
    ("asset.product_type_deleted", AuditCategory.CONFIGURATION, "assets"),
    ("asset.product_saved", AuditCategory.CONFIGURATION, "assets"),
    ("asset.product_deleted", AuditCategory.CONFIGURATION, "assets"),
    # ai (WP-037)
    ("ai.settings_changed", AuditCategory.CONFIGURATION, "ai"),
    # D-131: every deletion of AI conversation text is audited (retention purge, erasure)
    ("ai.calls_purged", AuditCategory.DATA, "ai"),
    ("ai.calls_erased", AuditCategory.DATA, "ai"),
    ("ai.summaries_erased", AuditCategory.DATA, "ai"),
    ("ai.embeddings_purged", AuditCategory.DATA, "ai"),
    # licence
    ("licence.read_only_entered", AuditCategory.LICENCE, "licensing"),
    # sensitive reads (REQ-AUD-004): one action per read category
    ("read.audit_log", AuditCategory.READS, "audit"),
    ("read.access_information", AuditCategory.READS, "identity_access"),
    ("read.security_settings", AuditCategory.READS, "identity_access"),
    ("read.secrets", AuditCategory.READS, "integrations"),
    ("read.exports", AuditCategory.READS, "audit"),
)

# A save's lifecycle events (WP-064, domain/lifecycle.py): every code the event table can produce
# is a records action of the table's module. Codes written by hand above keep their entries.
for _spec in RECORD_TYPES.values():
    for _code in sorted(_spec.events()):
        ACTIONS.setdefault(_code, Action(_code, AuditCategory.RECORDS, _spec.module))


def action(code: str) -> Action:
    """The registered action, or KeyError (a programming error: register it above)."""
    return ACTIONS[code]


def read_action(category: ReadCategory) -> Action:
    """The action logged for a read of `category`."""
    return ACTIONS[f"read.{category.value}"]
