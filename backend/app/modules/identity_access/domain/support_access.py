"""What a vendor support account may do: one decision per permission (WP-057 S4c-2, D-173).

A support account's permissions come from this table only, for its grant's access level: never
from a role, a group or a default (#552 fails closed; this is what it then opens). Every
permission in the catalogue has a decision; a new one without a decision fails CI (the guard
test), and at runtime a permission missing here is denied, never defaulted (lane B (1)).

- `VIEW`: given at both levels (read rights on records, knowledge, CMDB, assets, SLAs, reports).
- `CHANGE`: given at "view and change" only (the records and desk configuration).
- `DRAFT`: given at "view and change", for a save that can never publish (workflows: their
  versions are drafts until a tenant admin publishes; the publish routes refuse support).
- `Never(reason)`: never given. D-173's list, lane B's (6), the coordinator's draft decision
  (rules and notification templates have no draft state yet) and D-178 (support never speaks
  for the tenant: replies, announcements, mail).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from app.modules.identity_access.domain import field_access as field_rules


class Grantable(StrEnum):
    """A permission support may hold, and from which access level."""

    VIEW = "view"
    CHANGE = "change"
    DRAFT = "draft"


@dataclass(frozen=True)
class Never:
    """A permission support never holds, and why (a reason code, for the guard and the docs)."""

    reason: str


Decision = Grantable | Never

# Reasons a permission is never given (each used below; the guard test checks they're known).
REASONS = frozenset(
    {
        "people_and_roles",  # D-173: users, roles, groups' membership, departments, sites
        "sign_in_security",  # identity, sessions, break-glass, impersonation (lane B (6))
        "secrets_integrations",  # integrations, mailboxes, connectors, Runs-as
        "licence",
        "audit",
        "erasure_legal_hold",
        "branding",
        "exports_bulk",  # exports, scheduled reports (mail), bulk
        "api_keys",
        "ai_admin",
        "speaks_for_tenant",  # replies, announcements, notices (D-178)
        "tenant_decision",  # approvals, overrides, declaring a major incident, deletes
        "costs",  # costs and financials (D-164: admin rights only)
        "no_draft_path",  # business rules, notification templates (the coordinator, S4c-2 Q3)
        "sharing",  # views and dashboards shared with others
        "not_desk",  # outside the desk: procurement, files, personal profile
        "no_private_path",  # a note is private-capable: it opens private notes (lane B)
    }
)

_V, _C, _D = Grantable.VIEW, Grantable.CHANGE, Grantable.DRAFT


def _never(reason: str, *keys: str) -> dict[str, Decision]:
    return dict.fromkeys(keys, Never(reason))


def _record_type(path: str, extra: Iterable[str] = ()) -> dict[str, Decision]:
    """One work-item type's permissions: work it, never decide, reply, delete or share for it."""
    decided: dict[str, Decision] = {
        f"{path}.view": _V,
        **{
            f"{path}.{action}": _C
            for action in (
                "assign",
                "change_priority",
                "close",
                "create",
                "edit",
                "edit_due_dates",
                "manage_followers",
                "reopen",
                "resolve",
                "take",
                "cancel",
                *extra,
            )
        },
        **_never("speaks_for_tenant", f"{path}.reply"),
        # add_note also opens private notes, their files and the full notices (lane B, S4c-2 Q1).
        **_never("no_private_path", f"{path}.add_note"),
        **_never("tenant_decision", f"{path}.approve", f"{path}.delete"),
        **_never("sharing", f"{path}.share_views", f"{path}.share_views_wide"),
        **_never("costs", f"{path}.view_costs"),
    }
    return decided


SUPPORT_ACCESS: Mapping[str, Decision] = MappingProxyType(
    {
        # --- the desk's records --------------------------------------------------------------
        **_record_type("incidents", ("edit_closed", "undo_merge")),
        **_never("tenant_decision", "incidents.declare_major"),
        **_record_type("requests"),
        # WP-047a S2b (REQ-SR-042): who approves a request is the tenant's own decision.
        **_never("tenant_decision", "requests.modify_approvers"),
        **_record_type("problems", ("edit_analysis", "edit_solution", "mark_known_error")),
        "problems.view_root_cause": _V,
        **_record_type("changes", ("manage_windows",)),
        **_never(
            "tenant_decision",
            "changes.emergency_override",
            "changes.override_freeze",
            "changes.manage_boards",
        ),
        **_record_type("releases"),
        **_never("tenant_decision", "releases.override_freeze"),
        **_never("tenant_decision", "work_items.approve_any"),
        "work_items.view_reports": _V,
        **_never("people_and_roles", "work_items.view_department"),
        # --- knowledge, CMDB, assets --------------------------------------------------------
        "knowledge.view": _V,
        "knowledge.create": _C,
        "knowledge.edit_own": _C,
        "knowledge.edit_any": _C,
        "knowledge.submit": _C,
        "knowledge.manage_topics": _C,
        "knowledge.manage_types": _C,
        # Turns article approval off, so a draft would go live with no approver (lane B, #561).
        **_never("tenant_decision", "knowledge.manage_settings"),
        **_never("speaks_for_tenant", "knowledge.approve", "knowledge.withdraw"),
        **_never("tenant_decision", "knowledge.delete"),
        "cmdb.view": _V,
        "cmdb.add": _C,
        "cmdb.edit": _C,
        "cmdb.configure": _C,
        # Covers add, edit, delete, restore and merge: support has add and edit on their own,
        # so manage would only add the tenant decisions (delete, restore, merge; D-173; the
        # reproduction in tests/db/test_support_never_through_manage.py).
        **_never("tenant_decision", "cmdb.manage"),
        **_never("tenant_decision", "cmdb.delete"),
        "assets.view": _V,
        "assets.manage": _C,
        "assets.reinstate": _C,
        "assets.edit_disposed": _C,
        **_never("costs", "assets.view_financials"),
        # --- desk configuration -------------------------------------------------------------
        "sla.view": _V,
        "sla.manage": _C,
        # Mixes desk lists with governance: field sealing (sensitivity), approval stages, roles,
        # lifecycle publishing, change boards (lane B's #561 review). Never until it is split.
        **_never("tenant_decision", "config.service_desk"),
        "config.reports": _C,
        "config.assets": _C,
        # Publishes catalog items straight to the portal: speaks for the tenant (D-178, #561).
        **_never("speaks_for_tenant", "catalog_items.manage"),
        "reports.view": _V,
        "reports.create": _C,
        "reports.manage_folders": _C,
        **_never("exports_bulk", "reports.export", "reports.schedule"),
        "dashboards.create": _C,
        **_never("sharing", "dashboards.share", "dashboards.manage_defaults"),
        "automation.view": _V,
        **_never("no_draft_path", "automation.manage", "notifications.manage"),
        "workflows.manage": _D,
        **_never("secrets_integrations", "workflows.run"),  # Runs-as acts as another identity
        # --- organisation: read only, enough to show records ---------------------------------
        "groups.view": _V,
        "sites.view": _V,
        "departments.view": _V,
        "vendors.view": _V,
        **_never(
            "people_and_roles",
            "users.view",
            "users.manage",
            "roles.view",
            "roles.manage",
            "groups.manage",
            "groups.manage_own",
            "sites.manage",
            "departments.manage",
            "config.organisation",
        ),
        **_never("costs", "users.view_cost_rates", "users.manage_cost_rates"),
        # --- never ---------------------------------------------------------------------------
        **_never(
            "sign_in_security", "identity.manage", "identity.view_sign_ins", "settings.manage"
        ),
        **_never(
            "secrets_integrations",
            "integrations.view",
            "integrations.manage_email",
            "integrations.manage_identity",
            "mailboxes.manage",
        ),
        **_never("api_keys", "api_keys.manage"),
        **_never("licence", "licence.manage"),
        **_never(
            "audit",
            "audit.view",
            "audit.export",
            "audit.manage",
            "audit.verify",
            "audit.view_personal_data_access",
        ),
        **_never("erasure_legal_hold", "audit.manage_holds", "people.erase"),
        **_never("exports_bulk", "people.export"),
        **_never("branding", "branding.manage"),
        **_never("ai_admin", "ai.manage"),
        **_never(
            "speaks_for_tenant",
            "announcements.view",
            "announcements.manage",
            "announcements.publish",
            "config.announcements",
        ),
        **_never("not_desk", "vendors.create", "vendors.manage", "files.manage", "profile.edit"),
    }
)


def allowed(access: str, decision: Decision | None) -> bool:
    """Whether a grant at `access` (view, view_and_change) holds a permission with `decision`.

    No decision (a permission this table has not met yet) is never allowed (lane B (1)).
    """
    if decision is None or isinstance(decision, Never):
        return False
    if decision is Grantable.VIEW:
        return True
    return access == "view_and_change"


def permissions_for(access: str) -> frozenset[str]:
    """Every permission a grant at `access` holds (before the tenant's licence features)."""
    return frozenset(key for key, decision in SUPPORT_ACCESS.items() if allowed(access, decision))


def field_access(
    fields: Mapping[str, Iterable[tuple[str, bool, bool]]], *, unmask_personal: bool
) -> field_rules.Compiled:
    """A support subject's restricted fields (ADR-047), from each record type's rule-able ones.

    `fields` is {record type: [(field, personal_data, sensitive)]}. Sensitive fields (sealed
    custom values) are always hidden; personal-data fields are masked unless the grant unmasks
    them (D-173). Built from the field marks, never from a role, so no role can clear them.
    """
    nested: dict[str, dict[str, str]] = {}
    for record_type, found in fields.items():
        for key, personal, sensitive in found:
            if sensitive:
                nested.setdefault(record_type, {})[key] = field_rules.FieldMode.HIDDEN.value
            elif personal and not unmask_personal:
                nested.setdefault(record_type, {})[key] = field_rules.FieldMode.MASKED.value
    return MappingProxyType(
        {
            record_type: MappingProxyType(dict(sorted(f.items())))
            for record_type, f in sorted(nested.items())
        }
    )
