"""Incident templates and admin pick lists (WP-020c; REQ-INC-035, REQ-INC-007, REQ-INC-093).

Pure domain code, no I/O. A template says which fields the create form shows, which are
required, what they start with, and (for the portal, WP-028) what a requester may see and fill
in. Subject and requester are always shown and required: a record without them cannot exist
(REQ-INC-001 AC1). A configuration that could never work is refused when it is saved
(REQ-WI-009 AC4): a hidden required field without a default value would block every create.

Pick lists (levels, closure codes) hold admin-defined values with translations, an order and a
retire flag (REQ-ADM-043): a retired value is not offered for new input but still labels the
records that use it.
"""

import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.modules.work_items.domain.lifecycle import ReasonList, WorkItemAction

IMPACT_DETAILS_MAX = 2000
TEMPLATE_GROUP_MAX = 60
TEMPLATE_DESCRIPTION_MAX = 500
LIST_VALUES_MAX = 100


class PickList(StrEnum):
    """Admin-managed value lists: the reason lists plus levels and closure codes."""

    PAUSE = ReasonList.PAUSE.value
    THIRD_PARTY = ReasonList.THIRD_PARTY.value
    CANCEL = ReasonList.CANCEL.value
    REOPEN = ReasonList.REOPEN.value
    REASSIGN = ReasonList.REASSIGN.value
    LEVEL = "level"
    CLOSURE_CODE = "closure_code"


REASON_LISTS = frozenset(PickList(r.value) for r in ReasonList)

# Appendix A has no levels or closure codes; these defaults are D-083 (WP-020c plan).
DEFAULT_LIST_VALUES: Mapping[PickList, tuple[str, ...]] = {
    PickList.LEVEL: ("tier_1", "tier_2", "tier_3", "tier_4"),
    PickList.CLOSURE_CODE: ("fixed", "workaround", "no_fault_found", "duplicate", "user_error"),
}

# Which reason list a transition asks from when an admin turns its reason prompt on.
ACTION_REASON_LIST: Mapping[WorkItemAction, ReasonList] = {
    WorkItemAction.WAIT_REQUESTER: ReasonList.PAUSE,
    WorkItemAction.WAIT_THIRD_PARTY: ReasonList.THIRD_PARTY,
    WorkItemAction.CANCEL: ReasonList.CANCEL,
    WorkItemAction.REOPEN: ReasonList.REOPEN,
}

_CODE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def new_value_code() -> str:
    """A stable code for an admin-added value; the screens show its labels, never the code."""
    return f"v_{secrets.token_hex(5)}"


def is_admin_code(code: str) -> bool:
    """Whether a value was added by an admin (it then must keep a name of its own)."""
    return code.startswith("v_")


def is_code(value: str) -> bool:
    """Lowercase stable code (the same rule as the database check)."""
    return _CODE.fullmatch(value) is not None


# --- templates ------------------------------------------------------------------------------------


class TemplateField(StrEnum):
    """Fields a template configures, in the order the form shows them."""

    SUBJECT = "subject"
    REQUESTER_ID = "requester_id"
    ON_BEHALF_OF_ID = "on_behalf_of_id"
    CHANNEL = "channel"
    SITE_ID = "site_id"
    CATEGORY_ID = "category_id"
    LEVEL = "level"
    GROUP_ID = "group_id"
    TECHNICIAN_ID = "technician_id"
    IMPACT = "impact"
    URGENCY = "urgency"
    IMPACT_DETAILS = "impact_details"
    DESCRIPTION = "description"
    TAGS = "tags"


# Always shown and required, whatever the template says.
FIXED_FIELDS = frozenset({TemplateField.SUBJECT, TemplateField.REQUESTER_ID})
# Fields a template may give a starting value (people pickers start empty: a default
# technician would assign every incident from the template to one person).
DEFAULTABLE = frozenset(
    {
        TemplateField.SUBJECT,
        TemplateField.CHANNEL,
        TemplateField.SITE_ID,
        TemplateField.CATEGORY_ID,
        TemplateField.LEVEL,
        TemplateField.GROUP_ID,
        TemplateField.IMPACT,
        TemplateField.URGENCY,
        TemplateField.IMPACT_DETAILS,
        TemplateField.DESCRIPTION,
        TemplateField.TAGS,
    }
)


@dataclass(frozen=True)
class FieldRule:
    """How a template treats one field."""

    shown: bool = True
    required: bool = False
    requester_can_see: bool = True
    requester_can_fill: bool = False


def default_rules() -> dict[str, FieldRule]:
    """Every field shown; only subject and requester required (the seeded template)."""
    rules = {f.value: FieldRule() for f in TemplateField}
    for fixed in FIXED_FIELDS:
        rules[fixed.value] = FieldRule(required=True, requester_can_fill=True)
    rules[TemplateField.DESCRIPTION.value] = FieldRule(requester_can_fill=True)
    return rules


def rules_from_json(raw: Mapping[str, Any] | None) -> dict[str, FieldRule]:
    """Stored rules with any field the stored copy lacks filled from the defaults."""
    rules = default_rules()
    for name, value in (raw or {}).items():
        if name in rules and isinstance(value, Mapping):
            rules[name] = FieldRule(
                shown=bool(value.get("shown", True)),
                required=bool(value.get("required", False)),
                requester_can_see=bool(value.get("requester_can_see", True)),
                requester_can_fill=bool(value.get("requester_can_fill", False)),
            )
    return rules


def rules_to_json(rules: Mapping[str, FieldRule]) -> dict[str, dict[str, bool]]:
    """For the JSONB column."""
    return {
        name: {
            "shown": r.shown,
            "required": r.required,
            "requester_can_see": r.requester_can_see,
            "requester_can_fill": r.requester_can_fill,
        }
        for name, r in rules.items()
    }


def _empty(value: Any) -> bool:  # noqa: ANN401 - any default value
    return value is None or value in ("", [])


def rule_problems(
    rules: Mapping[str, FieldRule], defaults: Mapping[str, Any]
) -> list[tuple[str, str]]:
    """(field path, problem code) for rules that can never work (REQ-WI-009 AC4)."""
    problems: list[tuple[str, str]] = []
    for name, rule in rules.items():
        if name not in set(TemplateField):
            problems.append((f"fields.{name}", "unknown_field"))
            continue
        if TemplateField(name) in FIXED_FIELDS and not (rule.shown and rule.required):
            problems.append((f"fields.{name}", "field_always_required"))
        if rule.required and not rule.shown and _empty(defaults.get(name)):
            # Nobody could ever fill it in: every create would be refused.
            problems.append((f"fields.{name}", "hidden_required_needs_default"))
        if rule.requester_can_fill and not rule.requester_can_see:
            problems.append((f"fields.{name}", "fill_needs_see"))
    problems.extend(
        (f"defaults.{name}", "no_default_allowed")
        for name in defaults
        if name not in set(TemplateField) or TemplateField(name) not in DEFAULTABLE
    )
    return problems


def missing_required(
    rules: Mapping[str, FieldRule], values: Mapping[str, Any]
) -> list[tuple[str, str]]:
    """Required (non-fixed) fields left empty on a create; the fixed ones are checked anyway."""
    return [
        (name, "required")
        for name, rule in rules.items()
        if rule.required and TemplateField(name) not in FIXED_FIELDS and _empty(values.get(name))
    ]


def clean_impact_details(value: str | None) -> tuple[str | None, list[str]]:
    """Plain text, trimmed; None when blank."""
    if value is None:
        return None, []
    text = value.strip()
    if not text:
        return None, []
    if len(text) > IMPACT_DETAILS_MAX:
        return text, ["value_too_long"]
    return text, []


def order_problems(current: Iterable[str], wanted: Iterable[str]) -> list[str]:
    """A reorder must name every value of the list exactly once."""
    have, sent = list(current), list(wanted)
    if sorted(have) != sorted(sent) or len(set(sent)) != len(sent):
        return ["order_must_list_every_value"]
    return []
