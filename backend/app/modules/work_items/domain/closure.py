"""Resolving, closing and reopening: the rules, no I/O (WP-020f; REQ-INC-094..098).

* **Closure rules** (REQ-INC-094): per type, the fields required before resolve and before
  close. The resolution and the closure code are asked by the move itself; any other missing
  field is named so the user fills it on the record. Every path runs the same check.
* **Open work** (REQ-INC-095): other modules report open items (tasks, checklists, child
  incidents, approvals); each kind warns (an explicit confirmation, recorded) or blocks.
* **Auto-close** (REQ-INC-096) counts business days from when the requester was *told* of the
  resolution, never from the resolve itself (product owner, 2026-10-28).
* **Reopen window** (REQ-INC-098): a requester reply within it reopens; after it, a new record
  follows the old one.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

RESOLUTION = "resolution"
CLOSURE_CODE = "closure_code"

# Standard fields an admin can require (custom fields as "custom.<key>").
RULE_FIELDS = frozenset(
    {
        RESOLUTION,
        CLOSURE_CODE,
        "category_id",
        "site_id",
        "department_id",
        "group_id",
        "technician_id",
        "impact",
        "urgency",
        "level",
        "description",
        "tags",
    }
)
# Asked by the move dialog itself, on either move when the rules list them (a closure code
# before resolving, a resolution before closing); the rest are filled on the record.
MOVE_FIELDS = frozenset({RESOLUTION, CLOSURE_CODE})

WINDOW_MIN, WINDOW_MAX = 1, 30
AUTO_CLOSE_MIN, AUTO_CLOSE_MAX = 1, 30
DEFAULT_REOPEN_WINDOW = 7
DEFAULT_AUTO_CLOSE_DAYS = 3  # Appendix A; off until a channel can tell requesters


class OpenWorkMode(StrEnum):
    """What open work does to a resolve or close."""

    WARN = "warn"  # list it; the user confirms explicitly (recorded in history)
    BLOCK = "block"  # refused while it is open


class OpenWorkKind(StrEnum):
    """Kinds of open work other modules report (registered as their packages land)."""

    TASKS = "tasks"  # WP-020e
    CHECKLISTS = "checklists"  # WP-020e
    CHILD_INCIDENTS = "child_incidents"  # WP-020e links
    APPROVALS = "approvals"  # WP-030


OPEN_WORK_DEFAULTS: Mapping[OpenWorkKind, OpenWorkMode] = {
    OpenWorkKind.TASKS: OpenWorkMode.WARN,
    OpenWorkKind.CHECKLISTS: OpenWorkMode.WARN,
    OpenWorkKind.CHILD_INCIDENTS: OpenWorkMode.WARN,
    OpenWorkKind.APPROVALS: OpenWorkMode.BLOCK,
}


def open_work_modes(saved: Mapping[str, str]) -> dict[OpenWorkKind, OpenWorkMode]:
    """The tenant's choices over the defaults (unknown kinds and modes ignored)."""
    modes = dict(OPEN_WORK_DEFAULTS)
    for kind, mode in saved.items():
        if kind in OpenWorkKind.__members__.values() and mode in OpenWorkMode.__members__.values():
            modes[OpenWorkKind(kind)] = OpenWorkMode(mode)
    return modes


def rule_field_problems(fields: Iterable[str], custom_keys: Iterable[str]) -> list[str]:
    """Fields an admin may not require: unknown standard fields or custom fields."""
    custom = {f"custom.{key}" for key in custom_keys}
    return [f for f in fields if f not in RULE_FIELDS and f not in custom]


def is_empty(value: Any) -> bool:  # noqa: ANN401 - any field value
    """No value: None, blank text, an empty list or rich text with no words."""
    if value is None:
        return True
    if isinstance(value, str):
        return _plain(value) == ""
    if isinstance(value, list | tuple | set | dict):
        return len(value) == 0
    return False


def _plain(text: str) -> str:
    """Text without tags and spaces (an empty editor saves "<p></p>")."""
    out: list[str] = []
    inside = False
    for ch in text:
        if ch == "<":
            inside = True
        elif ch == ">":
            inside = False
        elif not inside:
            out.append(ch)
    return "".join(out).replace("&nbsp;", "").strip()


def missing_fields(
    required: Sequence[str], values: Mapping[str, Any], custom: Mapping[str, Any]
) -> list[str]:
    """The required fields that have no value, in the admin's order."""
    missing: list[str] = []
    for name in required:
        value = (
            custom.get(name.removeprefix("custom."))
            if name.startswith("custom.")
            else values.get(name)
        )
        if is_empty(value):
            missing.append(name)
    return missing


@dataclass(frozen=True)
class OpenItem:
    """One piece of open work, named for the user (a task's title, an approval ...)."""

    kind: OpenWorkKind
    title: str


@dataclass(frozen=True)
class OpenWorkDecision:
    """What open work means for this move."""

    blocking: list[OpenItem] = field(default_factory=list)
    to_confirm: list[OpenItem] = field(default_factory=list)

    @property
    def needs_confirmation(self) -> bool:
        """Open items the user must confirm before the move runs."""
        return bool(self.to_confirm)


def decide_open_work(
    items: Iterable[OpenItem], modes: Mapping[OpenWorkKind, OpenWorkMode]
) -> OpenWorkDecision:
    """Split open items into those that block and those the user must confirm."""
    decision = OpenWorkDecision()
    for item in items:
        mode = modes.get(item.kind, OpenWorkMode.WARN)
        (decision.blocking if mode == OpenWorkMode.BLOCK else decision.to_confirm).append(item)
    return decision


def add_business_days(start: datetime, days: int) -> datetime:
    """`days` business days (Monday to Friday) after `start`, same time of day.

    D4 (WP-020f): Monday to Friday until working calendars arrive with WP-025.
    """
    moment = start
    left = days
    while left > 0:
        moment += timedelta(days=1)
        if moment.weekday() < 5:  # noqa: PLR2004 - Saturday is 5
            left -= 1
    return moment


def auto_close_due(notified_at: datetime | None, days: int | None) -> datetime | None:
    """When a resolved record auto-closes; None when off or the requester was never told."""
    if notified_at is None or days is None:
        return None
    return add_business_days(notified_at, days)


def within_reopen_window(done_at: datetime | None, now: datetime, days: int) -> bool:
    """Whether a reply at `now` is within `days` after resolution or closure."""
    return done_at is not None and now <= done_at + timedelta(days=days)
