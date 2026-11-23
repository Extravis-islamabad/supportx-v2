"""Asset audits (REQ-AST-042, 043): states, results and discrepancies. Pure, no I/O.

- **States:** draft -> running -> closed. A draft is planned (scope, dates, auditors); starting
  freezes the expected items; a closed audit is read-only.
- **Results:** found, missing, wrong place, damaged. An asset recorded at another site than the
  audit expects it at is in the wrong place (043 AC1), whatever the auditor pressed.
- **Discrepancies:** every item that is not simply found: missing, wrong place, damaged,
  unexpected, or (once closed) never marked.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

NAME_MAX = 200
NOTE_MAX = 500
FIX_MAX = 1000  # items per fix (two bulk moves' worth; each goes through the asset service)


class AuditKind(StrEnum):
    """Who audits: technicians walking the floor, or each holder confirming their own."""

    TECHNICIAN = "technician"
    SELF = "self"


class AuditState(StrEnum):
    """Where an audit stands."""

    DRAFT = "draft"
    RUNNING = "running"
    CLOSED = "closed"


class AuditItemKind(StrEnum):
    """Expected (in scope when the audit started) or found unexpectedly."""

    EXPECTED = "expected"
    UNEXPECTED = "unexpected"


class AuditItemResult(StrEnum):
    """What the auditor found."""

    FOUND = "found"
    MISSING = "missing"
    WRONG_PLACE = "wrong_place"
    DAMAGED = "damaged"


class AuditMarkMethod(StrEnum):
    """How an item was marked."""

    SCANNED = "scanned"
    MANUAL = "manual"


class AuditFix(StrEnum):
    """A fix applied from the discrepancy list (043 AC2): through the normal asset service."""

    MOVE_SITE = "move_site"
    CHANGE_STATE = "change_state"
    ASSIGN = "assign"


@dataclass(frozen=True, slots=True)
class Progress:
    """Found and marked out of expected (043 AC3)."""

    expected: int
    marked: int
    found: int
    unexpected: int
    discrepancies: int


def result_of(
    wanted: AuditItemResult, *, expected_site: uuid.UUID | None, seen_site: uuid.UUID | None
) -> AuditItemResult:
    """The result kept: "found" somewhere else than expected is the wrong place (043 AC1).

    Missing and damaged stay as the auditor said: a damaged asset at the wrong site is first of
    all damaged, and the site seen is kept with it for the fix.
    """
    if (
        wanted is AuditItemResult.FOUND
        and seen_site is not None
        and expected_site is not None
        and seen_site != expected_site
    ):
        return AuditItemResult.WRONG_PLACE
    return wanted


def is_discrepancy(kind: AuditItemKind, result: AuditItemResult | None, *, closed: bool) -> bool:
    """Whether an item belongs on the discrepancy list."""
    if kind is AuditItemKind.UNEXPECTED:
        return True
    if result is None:
        return closed  # not marked: only a gap once the audit is over
    return result is not AuditItemResult.FOUND


def plan_problems(
    name: str | None, planned_start: date | None, planned_end: date | None
) -> list[tuple[str, str]]:
    """(field, code) for a plan that cannot be saved."""
    problems: list[tuple[str, str]] = []
    if name is not None and not name.strip():
        problems.append(("name", "required"))
    elif name is not None and len(name.strip()) > NAME_MAX:
        problems.append(("name", "value_too_long"))
    if planned_start is not None and planned_end is not None and planned_end < planned_start:
        problems.append(("planned_end", "end_before_start"))
    return problems
