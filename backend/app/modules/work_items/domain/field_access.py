"""Field access on work items (ADR-047 §1, §4, §8; slice b1). Pure, no I/O.

The person's compiled access (identity_access, `Subject.field_access`) says, per record type and
field, read_only, masked or hidden. Here it meets the record:

- `Unseen`: the fields whose values a person never gets back, split into hidden and masked.
  Both come back as null with their names listed (never a sentinel in a typed field, §4).
- Built-in fields an admin may restrict (`BUILTIN`), beside the custom fields
  (`custom.<key>`). Core fields (subject, description, status, priority, requester, group,
  assignee) are never offered: lists, search, notices and SLAs need them.
- The older per-permission gates (the root cause without `view_root_cause`, D-140 Q7) are
  applied after the role rules and cannot be outvoted by them (lane B's slice a note 2).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

CUSTOM = "custom."

# Built-in fields per record type: field -> label key. Each is enforced on every read path.
_PROBLEM_TEXT = {
    "root_cause": "work_item.field.root_cause",
    "symptoms": "work_item.field.symptoms",
    "workaround": "work_item.field.workaround",
    "review_summary": "work_item.field.review_summary",
    "review_lessons": "work_item.field.review_lessons",
    "review_actions": "work_item.field.review_actions",
}
_EVERY_TYPE = {"impact_details": "work_item.field.impact_details"}
BUILTIN: Mapping[str, Mapping[str, str]] = {
    "incident": _EVERY_TYPE,
    "service_request": _EVERY_TYPE,
    "problem": {**_EVERY_TYPE, **_PROBLEM_TEXT},
    "change": _EVERY_TYPE,
    "release": _EVERY_TYPE,
}


@dataclass(frozen=True)
class Unseen:
    """What a person may not read on one record: hidden, and masked (shown as masked)."""

    hidden: frozenset[str] = frozenset()
    masked: frozenset[str] = frozenset()

    @property
    def all(self) -> frozenset[str]:
        """Every field whose value is withheld."""
        return self.hidden | self.masked

    def custom_keys(self) -> frozenset[str]:
        """The withheld custom fields' keys (without the `custom.` prefix)."""
        return frozenset(f[len(CUSTOM) :] for f in self.all if f.startswith(CUSTOM))


def unseen(
    access: Mapping[str, Mapping[str, str]], record_type: str, *, also_hidden: Iterable[str] = ()
) -> Unseen:
    """The record type's withheld fields for a person: role rules, then the older gates.

    `also_hidden` (a permission gate the person fails on this record) always hides: a role rule
    that would merely mask, or nothing at all, never shows it (lane B's note 2).
    """
    fields = access.get(record_type, {})
    forced = frozenset(also_hidden)
    hidden = frozenset(f for f, m in fields.items() if m == "hidden") | forced
    masked = frozenset(f for f, m in fields.items() if m == "masked") - hidden
    return Unseen(hidden, masked)


def read_only(access: Mapping[str, Mapping[str, str]], record_type: str) -> frozenset[str]:
    """Fields the person may not change: any rule (masked and hidden imply read-only, §1)."""
    return frozenset(access.get(record_type, {}))


def without(custom: Mapping[str, Any] | None, keys: frozenset[str]) -> dict[str, Any]:
    """A record's custom values with the withheld keys taken out."""
    return {k: v for k, v in (custom or {}).items() if k not in keys}


def refused(changed: Iterable[str], locked: frozenset[str]) -> list[str]:
    """The changed fields (`custom.<key>` for custom ones) the person may not change."""
    return sorted(f for f in changed if f in locked)
