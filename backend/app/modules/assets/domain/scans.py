"""Scan history (REQ-AST-054) and the overdue-scan rule (REQ-AST-056). Pure, no I/O.

A scan records its time, source (agent, probe, import), type, result (a failed one with its
reason) and what changed since the previous scan, as labelled kinds:

    {"kind": "hardware_added", "category": "disk", "name": "Samsung 980", "model": "MZ-V8V1T0",
     "capacity": "1 TB"}
    {"kind": "software_removed", "name": "7-Zip", "version": "23.01", "publisher": "Igor Pavlov"}

Only these keys are kept and every value is short text: a scan never stores a blob from the
tool that sent it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

CHANGES_MAX = 2000  # changes per scan
TEXT_MAX = 200  # each value
DAYS_MAX = 3650
# Appendix A: scan history kept for 6 months; the setting is in months (asset settings).
RETENTION_MONTHS_DEFAULT = 6
OVERDUE_DAYS_DEFAULT = 60  # Appendix A: "not scanned for 60 days: move to Missing"
RUN_LIST_MAX = 5000  # assets one run lists; a bigger run goes on next time
CHANGES_FIELD = "changes"


class ScanSource(StrEnum):
    """Where a scan came from."""

    AGENT = "agent"
    PROBE = "probe"
    IMPORT = "import"


class ScanType(StrEnum):
    """What the scan looked at."""

    FULL = "full"
    HARDWARE = "hardware"
    SOFTWARE = "software"
    NETWORK = "network"


class ScanResult(StrEnum):
    """Whether the scan worked."""

    OK = "ok"
    FAILED = "failed"


class ScanFailure(StrEnum):
    """Why a scan failed (AC3)."""

    UNREACHABLE = "unreachable"
    CREDENTIALS_REFUSED = "credentials_refused"
    TIMED_OUT = "timed_out"
    AGENT_ERROR = "agent_error"
    UNSUPPORTED = "unsupported"
    OTHER = "other"


class ChangeKind(StrEnum):
    """What one scan found different from the one before."""

    HARDWARE_ADDED = "hardware_added"
    HARDWARE_REMOVED = "hardware_removed"
    SOFTWARE_INSTALLED = "software_installed"
    SOFTWARE_REMOVED = "software_removed"


class HardwareCategory(StrEnum):
    """The kind of hardware a change is about."""

    DISK = "disk"
    MEMORY = "memory"
    PROCESSOR = "processor"
    NETWORK_ADAPTER = "network_adapter"
    DISPLAY = "display"
    OTHER = "other"


class OverdueAction(StrEnum):
    """What the overdue-scan rule does: move to a state, or to the trash (never a delete)."""

    MOVE_STATE = "move_state"
    TRASH = "trash"


_HARDWARE = frozenset({ChangeKind.HARDWARE_ADDED, ChangeKind.HARDWARE_REMOVED})
_HARDWARE_KEYS = ("name", "model", "capacity", "serial")
_SOFTWARE_KEYS = ("name", "version", "publisher")


class ScanProblem(ValueError):
    """A scan the port refuses: `field` and `code` say why."""

    def __init__(self, field: str, code: str) -> None:
        """Which field and what is wrong."""
        super().__init__(f"{field}: {code}")
        self.field = field
        self.code = code


@dataclass(frozen=True, slots=True)
class ScanChange:
    """One change, cleaned."""

    kind: ChangeKind
    values: tuple[tuple[str, str], ...]
    category: HardwareCategory | None = None

    def as_json(self) -> dict[str, str]:
        """For the JSONB column."""
        out = {"kind": self.kind.value, **dict(self.values)}
        if self.category is not None:
            out["category"] = self.category.value
        return out


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) > TEXT_MAX:
        raise ScanProblem(CHANGES_FIELD, "value_too_long")
    return text


def clean_change(raw: Mapping[str, Any]) -> ScanChange:
    """One change from the port's caller; ScanProblem when it is not one we know."""
    try:
        kind = ChangeKind(str(raw.get("kind")))
    except ValueError:
        raise ScanProblem(CHANGES_FIELD, "invalid_choice") from None
    category: HardwareCategory | None = None
    keys: tuple[str, ...] = _SOFTWARE_KEYS
    if kind in _HARDWARE:
        keys = _HARDWARE_KEYS
        try:
            category = HardwareCategory(str(raw.get("category") or "other"))
        except ValueError:
            raise ScanProblem(CHANGES_FIELD, "invalid_choice") from None
    values = tuple((k, v) for k in keys if (v := _text(raw.get(k))) is not None)
    if not any(k == "name" for k, _ in values):
        raise ScanProblem(CHANGES_FIELD, "required")
    return ScanChange(kind=kind, values=values, category=category)


def clean_changes(raw: Sequence[Mapping[str, Any]]) -> list[ScanChange]:
    """Every change of one scan, cleaned (at most CHANGES_MAX)."""
    if len(raw) > CHANGES_MAX:
        raise ScanProblem(CHANGES_FIELD, "value_too_long")
    return [clean_change(item) for item in raw]


def failure_problem(result: ScanResult, reason: ScanFailure | None) -> ScanProblem | None:
    """A failed scan says why; a good one has no reason (AC3)."""
    if result is ScanResult.FAILED and reason is None:
        return ScanProblem("failure_reason", "required")
    if result is ScanResult.OK and reason is not None:
        return ScanProblem("failure_reason", "invalid_value")
    return None


def rule_problems(
    *, enabled: bool, days: int, action: OverdueAction, state_id: object | None
) -> list[tuple[str, str]]:
    """(field, code) for an overdue rule that cannot be saved."""
    problems: list[tuple[str, str]] = []
    if not 1 <= days <= DAYS_MAX:
        problems.append(("days", "out_of_range"))
    if enabled and action is OverdueAction.MOVE_STATE and state_id is None:
        problems.append(("state_id", "required"))
    return problems
