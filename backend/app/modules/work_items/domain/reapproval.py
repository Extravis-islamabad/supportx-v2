"""Re-approval when an approved change changes (WP-045b S4; REQ-CHG-053). Pure.

When a stage's approvals complete as approved, the watched values are kept (a snapshot). A later
save compares the change with each approved stage's snapshot: what changed is listed field by
field (AC3), and the tenant's policy says per field whether it restarts that stage's approval or
only notifies. By default the window restarts approval when either end moves by more than the
tolerance (AC1), the risk only when it rises (AC2), and the plans only notify.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.modules.work_items.domain.change_risk import RiskLevel, rank


class Watched(StrEnum):
    """The values a snapshot keeps."""

    WINDOW = "window"  # the implementation stage's scheduled start and end
    RISK = "risk"  # the effective risk (the override, else the calculated one)
    PLANS = "plans"  # the plan sections' versions


class OnChange(StrEnum):
    """What a change to a watched value does to an approval."""

    RESTART = "restart"
    NOTIFY = "notify"
    IGNORE = "ignore"


DEFAULT_TOLERANCE_MINUTES = 60
MAX_TOLERANCE_MINUTES = 7 * 24 * 60


@dataclass(frozen=True)
class Policy:
    """The tenant's re-approval policy."""

    on_change: Mapping[Watched, OnChange] = field(
        default_factory=lambda: {
            Watched.WINDOW: OnChange.RESTART,
            Watched.RISK: OnChange.RESTART,
            Watched.PLANS: OnChange.NOTIFY,
        }
    )
    tolerance_minutes: int = DEFAULT_TOLERANCE_MINUTES


DEFAULT_POLICY = Policy()


def policy_from(raw: Any) -> Policy:  # noqa: ANN401 - the stored JSON, checked here
    """The stored policy, else the default; unknown or broken parts take the default."""
    if not isinstance(raw, Mapping):
        return DEFAULT_POLICY
    chosen = dict(DEFAULT_POLICY.on_change)
    for key, value in (raw.get("on_change") or {}).items():
        try:
            chosen[Watched(key)] = OnChange(value)
        except ValueError:
            continue
    tolerance = raw.get("tolerance_minutes", DEFAULT_TOLERANCE_MINUTES)
    if not isinstance(tolerance, int) or not 0 <= tolerance <= MAX_TOLERANCE_MINUTES:
        tolerance = DEFAULT_TOLERANCE_MINUTES
    return Policy(chosen, tolerance)


def policy_problems(raw: Any) -> list[tuple[str, str]]:  # noqa: ANN401 - the request's JSON
    """(field, code) pairs of a policy an admin sends."""
    if not isinstance(raw, Mapping) or set(raw) - {"on_change", "tolerance_minutes"}:
        return [("reapproval", "invalid_value")]
    problems: list[tuple[str, str]] = []
    on_change = raw.get("on_change") or {}
    if not isinstance(on_change, Mapping):
        return [("reapproval.on_change", "invalid_value")]
    for key, value in on_change.items():
        if key not in set(Watched):
            problems.append((f"reapproval.on_change.{key}", "not_a_field"))
        elif value not in set(OnChange):
            problems.append((f"reapproval.on_change.{key}", "invalid_choice"))
    tolerance = raw.get("tolerance_minutes", DEFAULT_TOLERANCE_MINUTES)
    if not isinstance(tolerance, int) or not 0 <= tolerance <= MAX_TOLERANCE_MINUTES:
        problems.append(("reapproval.tolerance_minutes", "out_of_range"))
    return problems


def policy_json(policy: Policy) -> dict[str, object]:
    """A policy as stored and shown."""
    return {
        "on_change": {k.value: v.value for k, v in policy.on_change.items()},
        "tolerance_minutes": policy.tolerance_minutes,
    }


@dataclass(frozen=True)
class Snapshot:
    """The watched values at one moment."""

    window_start: datetime | None
    window_end: datetime | None
    risk: RiskLevel | None
    plans: Mapping[str, int]  # section -> its version

    def to_json(self) -> dict[str, object]:
        """As stored."""
        return {
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "risk": self.risk.value if self.risk else None,
            "plans": dict(self.plans),
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "Snapshot":
        """From the stored form."""

        def when(value: object) -> datetime | None:
            return datetime.fromisoformat(value) if isinstance(value, str) else None

        risk = raw.get("risk")
        return cls(
            when(raw.get("window_start")),
            when(raw.get("window_end")),
            RiskLevel(risk) if isinstance(risk, str) else None,
            {str(k): int(v) for k, v in (raw.get("plans") or {}).items()},
        )


@dataclass(frozen=True)
class FieldChange:
    """One watched value that changed since approval, and what it does."""

    field: str  # window_start, window_end, risk, plans.<section>
    before: object
    after: object
    watched: Watched
    effect: OnChange


def _minutes_apart(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None if a is b else float("inf")
    return abs((a - b).total_seconds()) / 60


def compare(approved: Snapshot, now: Snapshot, policy: Policy) -> list[FieldChange]:
    """What changed since approval, field by field, with each change's effect (AC3).

    A window end moved within the tolerance is listed but only notifies; the risk restarts only
    when it rises (AC2), a lower risk notifies.
    """
    found: list[FieldChange] = []
    on = policy.on_change
    for name, before, after in (
        ("window_start", approved.window_start, now.window_start),
        ("window_end", approved.window_end, now.window_end),
    ):
        apart = _minutes_apart(before, after)
        if apart is None or apart == 0:
            continue
        effect = on[Watched.WINDOW]
        if effect is OnChange.RESTART and apart <= policy.tolerance_minutes:
            effect = OnChange.NOTIFY
        found.append(FieldChange(name, before, after, Watched.WINDOW, effect))
    if approved.risk != now.risk:
        effect = on[Watched.RISK]
        raised = now.risk is not None and (
            approved.risk is None or rank(now.risk) > rank(approved.risk)
        )
        if effect is OnChange.RESTART and not raised:
            effect = OnChange.NOTIFY
        found.append(FieldChange("risk", approved.risk, now.risk, Watched.RISK, effect))
    for section in sorted(set(approved.plans) | set(now.plans)):
        before_v, after_v = approved.plans.get(section, 0), now.plans.get(section, 0)
        if before_v != after_v:
            found.append(
                FieldChange(f"plans.{section}", before_v, after_v, Watched.PLANS, on[Watched.PLANS])
            )
    return [c for c in found if c.effect is not OnChange.IGNORE]


def restarts(changes: list[FieldChange]) -> bool:
    """Whether any change restarts the stage's approval."""
    return any(c.effect is OnChange.RESTART for c in changes)
