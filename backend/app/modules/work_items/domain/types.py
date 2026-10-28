"""Work item types and the fields every type shares (WP-020; ADR-026, architecture.md §6.2).

Pure domain code, no I/O. One engine serves every ticket-like record: a type is a registry entry
(its prefix, licence feature, permission namespace, default life cycle and allowed fields), never
a fork of the engine. WP-020 registers incidents; service requests, problems, changes and
releases register themselves here with their own seed data (and an extension table for fields
only they have).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.modules.work_items.domain.lifecycle import (
    DEFAULT_STATUSES,
    DEFAULT_TRANSITIONS,
    StatusDef,
    TransitionDef,
)

SUBJECT_MAX = 250
DESCRIPTION_MAX = 100_000  # sanitised HTML, characters
TAG_MAX = 40
TAGS_MAX = 20
_TAG = re.compile(r"^[\w][\w .\-]{0,39}$", re.UNICODE)
PREFIX_PATTERN = r"^[A-Z]{2,6}$"
_PREFIX = re.compile(PREFIX_PATTERN)


class WorkItemTypeCode(StrEnum):
    """Every ticket-like type (only those in TYPES are built)."""

    INCIDENT = "incident"
    SERVICE_REQUEST = "service_request"
    PROBLEM = "problem"
    CHANGE = "change"
    RELEASE = "release"


class Channel(StrEnum):
    """Where a work item came from (REQ-INC-005). Set by the entry point, not by hand."""

    PHONE = "phone"
    WALK_UP = "walk_up"
    EMAIL = "email"
    PORTAL = "portal"
    CHAT = "chat"
    VIRTUAL_AGENT = "virtual_agent"
    TEAMS = "teams"
    SLACK = "slack"
    WHATSAPP = "whatsapp"
    MOBILE_APP = "mobile_app"
    API = "api"
    MONETX = "monetx"
    ALERT_WEBHOOK = "alert_webhook"


# The only channels a person chooses: the rest are set by the entry point that created it.
CHOSEN_CHANNELS = frozenset({Channel.PHONE, Channel.WALK_UP})


@dataclass(frozen=True)
class WorkItemType:
    """One registered type."""

    code: WorkItemTypeCode
    path: str  # API path segment: /api/v1/<path>
    default_prefix: str  # display ID prefix until a tenant renames it
    feature: str  # licence feature (entitlement interface)
    permission_prefix: str  # <prefix>.view, <prefix>.edit ...
    statuses: Sequence[StatusDef] = DEFAULT_STATUSES
    transitions: Sequence[TransitionDef] = DEFAULT_TRANSITIONS
    fields: frozenset[str] = field(default_factory=frozenset)

    @property
    def counter_key(self) -> str:
        """The display-ID counter, by type so a renamed prefix keeps counting (ADR-026)."""
        return f"WI_{self.code.upper()}"

    def permission(self, action: str) -> str:
        """`incidents.view` for action `view`."""
        return f"{self.permission_prefix}.{action}"


COMMON_FIELDS = frozenset(
    {
        "subject",
        "description",
        "requester_id",
        "on_behalf_of_id",
        "channel",
        "site_id",
        "department_id",
        "group_id",
        "technician_id",
        "category_id",
        "impact",
        "urgency",
        "priority",
        "tags",
    }
)

INCIDENT = WorkItemType(
    code=WorkItemTypeCode.INCIDENT,
    path="incidents",
    default_prefix="INC",
    feature="incident",
    permission_prefix="incidents",
    fields=COMMON_FIELDS,
)

TYPES: Mapping[WorkItemTypeCode, WorkItemType] = {INCIDENT.code: INCIDENT}


# --- value rules shared by every type -------------------------------------------------------------


def prefix_problems(prefix: str) -> list[str]:
    """Codes for an invalid display prefix (2-6 capital letters)."""
    return [] if _PREFIX.fullmatch(prefix) else ["invalid_prefix"]


def clean_subject(value: str) -> tuple[str, list[str]]:
    """Trimmed subject, plus problem codes."""
    text = " ".join(value.split())
    if not text:
        return text, ["required"]
    if len(text) > SUBJECT_MAX:
        return text, ["value_too_long"]
    return text, []


def clean_tags(values: Sequence[str]) -> tuple[list[str], list[str]]:
    """Unique tags in first-seen order (case-insensitive), plus problem codes."""
    seen: dict[str, str] = {}
    for raw in values:
        tag = " ".join(raw.split())
        if not tag:
            continue
        if not _TAG.fullmatch(tag):
            return [], ["invalid_tag"]
        seen.setdefault(tag.casefold(), tag)
    tags = list(seen.values())
    if len(tags) > TAGS_MAX:
        return tags, ["too_many_items"]
    return tags, []


def channel_problems(channel: str | None) -> list[str]:
    """A client may only choose the phone or walk-up channel (REQ-INC-005 AC3)."""
    if channel is None or channel in CHOSEN_CHANNELS:
        return []
    return ["channel_reserved"]


def parse_display_id(value: str, prefix: str) -> tuple[str | None, int | None]:
    """`INC-12`, `inc-12` or `12` → (prefix or None, number); (None, None) when not an ID."""
    text = value.strip().upper()
    match = re.fullmatch(r"(?:([A-Z]{2,6})-)?(\d{1,18})", text)
    if match is None:
        return None, None
    del prefix  # the caller compares the prefix; kept in the signature for clarity of use
    return match.group(1), int(match.group(2))


# Every field problem code this module returns (errors.field.<code> labels, checked in CI by
# tests/test_error_labels.py, which reads FIELD_PROBLEMS sets).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        # WP-020f: closure rules and closing settings.
        "required_to_resolve",
        "required_to_close",
        "auto_close_needs_notifications",
        "not_for_this_status",
        "out_of_range",
        "invalid_value",
        "value_too_long",
        "invalid_choice",
        "not_allowed",
        "invalid_tag",
        "too_many_items",
        "channel_reserved",
        "user_not_found",
        "category_not_found",
        "category_disabled",
        "site_not_found",
        "department_not_found",
        "group_not_found",
        "technician_not_allowed",
        "technician_not_in_group",
        "group_not_yours",
        "group_required",
        "invalid_prefix",
        "english_label_required",
        "unknown_language",
        "too_deep",
        # WP-020b: conversation, followers, reply templates
        "not_allowed_for_notes",
        "invalid_email",
        "too_many",
        "replies_are_public",
        "cannot_see_record",
        "duplicate_name",
        # WP-020c: settings, pick lists, numbering and templates
        "invalid_colour",
        "matrix_incomplete",
        "value_required_by_system",
        "last_value",
        "order_must_list_every_value",
        "number_already_used",
        "template_not_found",
        "template_disabled",
        "default_required",
        "default_cannot_be_disabled",
        "disabled_cannot_be_default",
        "unknown_field",
        "field_always_required",
        "hidden_required_needs_default",
        "fill_needs_see",
        "no_default_allowed",
        # WP-020c-FIX (D-086)
        "requester_always_needed",
    }
)


# --- default categories (a starting tree; tenants edit it in WP-020c) -----------------------------

DEFAULT_CATEGORIES: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "hardware": {"laptop_or_desktop": (), "printer": (), "phone_or_mobile": (), "peripheral": ()},
    "software": {"email": (), "office_apps": (), "business_app": (), "operating_system": ()},
    "network": {"wifi": (), "vpn": (), "internet": (), "wired_network": ()},
    "access": {"account": (), "password": (), "permissions": ()},
    "other": {},
}
