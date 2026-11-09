"""Which change advisory board reviews a change (WP-045b S2; REQ-CHG-040, -041). Pure.

A board's mapping names the changes it reviews: change types, risk levels, sites and templates,
each optional (an empty or missing list matches anything). Boards are tried in their order; the
tenant says whether the first match reviews or every match does. When nothing matches, the
default board reviews, and the change says so (AC2). The reason is kept for history ("the
mapping of <board> on its risk", AC1).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Appendix A's two boards, seeded per tenant with no members (REQ-CHG-040).
DEFAULT_BOARD = "cab"
EMERGENCY_BOARD = "emergency_cab"
SEEDED = (DEFAULT_BOARD, EMERGENCY_BOARD)


class BoardRule(StrEnum):
    """How a board decides (REQ-CHG-042).

    Anyone, everyone, a majority, or a majority whose ties the chair breaks (D-146).
    """

    ANY = "any"
    ALL = "all"
    MAJORITY = "majority"
    MAJORITY_WITH_CHAIR = "majority_with_chair"


RULES = tuple(rule.value for rule in BoardRule)


class BoardChoice(StrEnum):
    """Why a board reviews a change (REQ-CHG-041 AC1, AC2)."""

    MAPPED = "mapped"  # its mapping matched the change
    DEFAULT = "default"  # nothing matched: the default board


MAPPING_KEYS = ("change_types", "risk_levels", "site_ids", "template_ids")
# The field codes a board's checks give (labels: errors.field.*).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        "value_too_long",
        "duplicate_name",
        "duplicate_value",
        "invalid_value",
        "invalid_choice",
        "not_a_field",
        "out_of_range",
        "too_many_items",
        "user_not_found",
        "group_not_found",
        "site_not_found",
        "template_not_found",
        "board_not_found",
    }
)


@dataclass(frozen=True)
class BoardFacts:
    """A board as the choice sees it."""

    id: str
    code: str | None
    position: int
    is_default: bool
    mapping: Mapping[str, Sequence[str]] | None
    has_members: bool


@dataclass(frozen=True)
class ChangeFacts:
    """What of a change a mapping can name."""

    change_type: str | None
    risk: str | None
    site_id: str | None
    template_id: str | None


@dataclass(frozen=True)
class Choice:
    """The boards that review, and why: `mapped` (by their mapping) or `default`."""

    board_ids: tuple[str, ...]
    reason: str
    without_members: tuple[str, ...] = ()


def mapping_problems(raw: Any) -> list[tuple[str, str]]:  # noqa: ANN401 - the request's JSON
    """(field, code) pairs of a mapping: known keys, each a list of strings."""
    if raw is None:
        return []
    if not isinstance(raw, Mapping):
        return [("mapping", "invalid_value")]
    problems = [(f"mapping.{k}", "not_a_field") for k in raw if k not in MAPPING_KEYS]
    for key in MAPPING_KEYS:
        value = raw.get(key)
        if value is not None and (
            not isinstance(value, list) or not all(isinstance(v, str) for v in value)
        ):
            problems.append((f"mapping.{key}", "invalid_value"))
    return problems


def matches(mapping: Mapping[str, Sequence[str]] | None, change: ChangeFacts) -> bool:
    """Whether a board's mapping names this change (an empty mapping names none)."""
    if not mapping or not any(mapping.get(k) for k in MAPPING_KEYS):
        return False
    pairs = (
        ("change_types", change.change_type),
        ("risk_levels", change.risk),
        ("site_ids", change.site_id),
        ("template_ids", change.template_id),
    )
    return all(not mapping.get(key) or value in mapping[key] for key, value in pairs)


def choose(
    boards: Sequence[BoardFacts], change: ChangeFacts, *, every_match: bool = False
) -> Choice:
    """The reviewing boards (REQ-CHG-041): mapped ones in order, else the default board."""
    ordered = sorted(boards, key=lambda b: (b.position, b.code or "", b.id))
    mapped = [b for b in ordered if not b.is_default and matches(b.mapping, change)]
    if mapped:
        chosen = mapped if every_match else mapped[:1]
        reason = "mapped"
    else:
        chosen = [b for b in ordered if b.is_default][:1]
        reason = "default"
    return Choice(
        tuple(b.id for b in chosen),
        reason,
        tuple(b.id for b in chosen if not b.has_members),
    )
