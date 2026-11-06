"""What the audit log records: actions, categories, outcomes, actor types (REQ-AUD-002, 003).

Every action is a stable lowercase code with labels in en/ar/ur (`audit.action.<code>`); the UI
never shows the code itself. New privileged routes add their action here and mark the route
with `audited(...)` (an architecture test fails otherwise).
"""

from dataclasses import dataclass
from enum import StrEnum


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
    ("session.signed_out", AuditCategory.SESSION, "identity_access"),
    ("session.tenant_switched", AuditCategory.SESSION, "identity_access"),
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


def action(code: str) -> Action:
    """The registered action, or KeyError (a programming error: register it above)."""
    return ACTIONS[code]


def read_action(category: ReadCategory) -> Action:
    """The action logged for a read of `category`."""
    return ACTIONS[f"read.{category.value}"]
