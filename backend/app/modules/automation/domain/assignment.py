"""Routing and auto-assignment without I/O (WP-029; REQ-ASG-001..004, 006, 011).

Routing picks the group: the first matching routing rule, else the category's suggested group,
else the tenant's fallback group. Auto-assignment picks a technician **inside the record's group
only**, among available members, by round robin or load balancing. Both say why, so history can
name the rule, the method and (for load balancing) the loads compared.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from app.modules.automation.domain.rules import JsonValue, matches

# Load weights per priority (Appendix A): P1 = 4, P2 = 3, P3 = 2, P4 = 1.
LOAD_WEIGHTS: Mapping[str, int] = {"p1": 4, "p2": 3, "p3": 2, "p4": 1}
DEFAULT_WEIGHT = 1


class AssignMethod(StrEnum):
    """How a group spreads its new work (REQ-ASG-002..004)."""

    ROUND_ROBIN = "round_robin"
    LOAD_BALANCING = "load_balancing"


class Availability(StrEnum):
    """A technician's own state (REQ-ASG-006): away people are never auto-assigned."""

    AVAILABLE = "available"
    AWAY = "away"


@dataclass(frozen=True)
class RoutingRuleDef:
    """An enabled routing rule, in order."""

    id: str
    name: str
    conditions: Mapping[str, object] | None
    group_id: str
    overwrite: bool = False
    site_id: str | None = None


@dataclass(frozen=True)
class RoutingChoice:
    """The group to set, and why (for history)."""

    group_id: str
    reason: str  # rule | category | fallback
    rule_id: str | None = None
    rule: str | None = None


def route(  # noqa: PLR0911 - one return per routing outcome
    rules: Sequence[RoutingRuleDef],
    record: Mapping[str, JsonValue],
    *,
    category_group: str | None,
    fallback_group: str | None,
    entry_group: str | None = None,
) -> RoutingChoice | None:
    """The group for a record (REQ-ASG-001).

    A group a person chose is kept, unless a matching rule says "overwrite". After the rules,
    the group of the way the record came in (a mailbox, WP-024) comes before the category's.
    """
    has_group = record.get("group_id") is not None
    for rule in rules:
        if rule.site_id is not None and record.get("site_id") != rule.site_id:
            continue
        if not matches(rule.conditions, None, record):
            continue
        if has_group and not rule.overwrite:
            return None
        if record.get("group_id") == rule.group_id:
            return None
        return RoutingChoice(rule.group_id, "rule", rule.id, rule.name)
    if has_group:
        return None
    if entry_group is not None:
        return RoutingChoice(entry_group, "entry")
    if category_group is not None:
        return RoutingChoice(category_group, "category")
    if fallback_group is not None:
        return RoutingChoice(fallback_group, "fallback")
    return None


@dataclass(frozen=True)
class Candidate:
    """A member of the group who may be assigned the record, with what the choice needs."""

    user_id: str
    available: bool
    load: int  # weighted open load (LOAD_WEIGHTS)
    open_count: int  # open records, for the load cap
    last_assigned_at: datetime | None  # by auto-assignment in this group


@dataclass(frozen=True)
class AssignmentChoice:
    """Who gets the record, by which method, with the loads compared (REQ-ASG-004 AC3)."""

    user_id: str | None
    method: AssignMethod
    reason: str  # assigned | nobody_available | all_at_cap | no_members
    loads: dict[str, int] = field(default_factory=dict)


def choose(
    method: AssignMethod, candidates: Sequence[Candidate], *, load_cap: int | None = None
) -> AssignmentChoice:
    """Pick one available member under the cap (REQ-ASG-003, 004, 006, 011).

    Round robin: whoever was auto-assigned least recently (never first). Load balancing: the
    lowest weighted load, ties to whoever was assigned least recently. Nobody: the record stays
    in the group queue, with the reason.
    """
    if not candidates:
        return AssignmentChoice(None, method, "no_members")
    available = [c for c in candidates if c.available]
    if not available:
        return AssignmentChoice(None, method, "nobody_available")
    under_cap = [c for c in available if load_cap is None or c.open_count < load_cap]
    if not under_cap:
        return AssignmentChoice(None, method, "all_at_cap")

    def turn(candidate: Candidate) -> tuple[bool, datetime, str]:
        # Never auto-assigned first, then the oldest turn, then a stable order by ID. (Within a
        # group of equal first elements every time is aware, or every one is the sentinel.)
        last = candidate.last_assigned_at
        return (last is not None, last or datetime.min.replace(tzinfo=UTC), candidate.user_id)

    if method == AssignMethod.ROUND_ROBIN:
        chosen = min(under_cap, key=turn)
        return AssignmentChoice(chosen.user_id, method, "assigned")
    loads = {c.user_id: c.load for c in under_cap}
    chosen = min(under_cap, key=lambda c: (c.load, *turn(c)))
    return AssignmentChoice(chosen.user_id, method, "assigned", loads)


def weighted_load(priorities: Sequence[str]) -> int:
    """The load of a technician's open records (REQ-ASG-004)."""
    return sum(LOAD_WEIGHTS.get(priority, DEFAULT_WEIGHT) for priority in priorities)
