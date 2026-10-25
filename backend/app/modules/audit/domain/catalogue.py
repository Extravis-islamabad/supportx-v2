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
    ("user.preferences_changed", AuditCategory.ACCESS, "identity_access"),
    # organisation
    ("site.created", AuditCategory.ORGANISATION, "organization"),
    ("site.renamed", AuditCategory.ORGANISATION, "organization"),
    ("site.member_added", AuditCategory.ORGANISATION, "organization"),
    ("site.member_removed", AuditCategory.ORGANISATION, "organization"),
    ("group.created", AuditCategory.ORGANISATION, "organization"),
    ("group.renamed", AuditCategory.ORGANISATION, "organization"),
    ("group.member_added", AuditCategory.ORGANISATION, "organization"),
    ("group.member_removed", AuditCategory.ORGANISATION, "organization"),
    # configuration
    ("incident.settings_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("incident.category_created", AuditCategory.CONFIGURATION, "work_items"),
    ("incident.category_changed", AuditCategory.CONFIGURATION, "work_items"),
    ("announcement.settings_changed", AuditCategory.CONFIGURATION, "announcements"),
    # record actions (REQ-WI-021)
    ("incident.deleted", AuditCategory.RECORDS, "work_items"),
    ("incident.restored", AuditCategory.RECORDS, "work_items"),
    ("incident.closed_record_edited", AuditCategory.RECORDS, "work_items"),
    ("incident.due_date_changed", AuditCategory.RECORDS, "work_items"),
    # the audit log itself
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
