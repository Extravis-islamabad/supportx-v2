"""Impact, urgency, priority and the priority matrix (WP-020; REQ-INC-008..011).

Pure domain code, no I/O. Impact (how widely it is felt) and urgency (how fast it must be fixed)
are two single, ordered scales, never mixed with each other (ServiceDesk Plus puts "affects
user" next to "high" in one list). Priority comes from the matrix, which ships filled in; a
record never silently has no priority: with neither impact nor urgency known it gets the
tenant's default priority and says so.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

PRIORITY_REASON_MAX = 500


class Scale(StrEnum):
    """The three ordered value lists of a work item type."""

    IMPACT = "impact"
    URGENCY = "urgency"
    PRIORITY = "priority"


class Impact(StrEnum):
    """How widely it is felt, lowest first."""

    ONE_PERSON = "one_person"
    TEAM = "team"
    DEPARTMENT_OR_SITE = "department_or_site"
    ORGANISATION = "organisation"


class Urgency(StrEnum):
    """How fast it must be fixed, lowest first."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Priority(StrEnum):
    """P1 is the highest."""

    P1 = "p1"
    P2 = "p2"
    P3 = "p3"
    P4 = "p4"


class PrioritySource(StrEnum):
    """Where the current priority came from (shown as a marker, REQ-INC-010/011)."""

    MATRIX = "matrix"
    MANUAL = "manual"  # set by hand, with a reason
    DEFAULT = "default"  # neither impact nor urgency known: the tenant default
    RULE = "rule"  # set by a business rule (WP-029; history names the rule)


SCALE_CODES: Mapping[Scale, tuple[str, ...]] = {
    Scale.IMPACT: tuple(Impact),
    Scale.URGENCY: tuple(Urgency),
    Scale.PRIORITY: tuple(Priority),
}

DEFAULT_COLOURS: Mapping[str, str] = {
    Priority.P1: "#cf1322",
    Priority.P2: "#fa541c",
    Priority.P3: "#faad14",
    Priority.P4: "#8c8c8c",
}

# Appendix A of the parity file: rows impact, columns urgency (low, medium, high, critical).
_ROWS: Mapping[Impact, tuple[Priority, Priority, Priority, Priority]] = {
    Impact.ONE_PERSON: (Priority.P4, Priority.P4, Priority.P3, Priority.P3),
    Impact.TEAM: (Priority.P4, Priority.P3, Priority.P3, Priority.P2),
    Impact.DEPARTMENT_OR_SITE: (Priority.P3, Priority.P3, Priority.P2, Priority.P1),
    Impact.ORGANISATION: (Priority.P3, Priority.P2, Priority.P1, Priority.P1),
}
DEFAULT_MATRIX: Mapping[tuple[str, str], str] = {
    (impact.value, urgency.value): priority.value
    for impact, row in _ROWS.items()
    for urgency, priority in zip(Urgency, row, strict=True)
}
DEFAULT_PRIORITY = Priority.P3


class MatrixError(ValueError):
    """A matrix with an empty or unknown cell (REQ-INC-009 AC4)."""


def check_matrix(matrix: Mapping[tuple[str, str], str]) -> None:
    """Every impact x urgency cell filled with a known priority."""
    for impact in Impact:
        for urgency in Urgency:
            value = matrix.get((impact.value, urgency.value))
            if value not in set(Priority):
                msg = f"matrix cell {impact}/{urgency} is empty or unknown ({value!r})"
                raise MatrixError(msg)


@dataclass(frozen=True)
class Computed:
    """A computed priority and where it came from."""

    priority: str
    source: PrioritySource


def compute_priority(
    impact: str | None,
    urgency: str | None,
    matrix: Mapping[tuple[str, str], str],
    default: str = DEFAULT_PRIORITY,
) -> Computed:
    """Priority from the matrix (REQ-INC-009).

    Both unknown: the tenant default, marked `default`. One unknown: the lowest value of that
    scale stands in for it (an unknown impact is treated as one person), so a critical urgency
    still raises the priority without anyone claiming a wide impact.
    """
    if impact is None and urgency is None:
        return Computed(default, PrioritySource.DEFAULT)
    row = impact or Impact.ONE_PERSON.value
    column = urgency or Urgency.LOW.value
    return Computed(matrix[(row, column)], PrioritySource.MATRIX)
