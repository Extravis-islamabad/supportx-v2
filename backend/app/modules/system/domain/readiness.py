"""Readiness model: pure domain logic, no I/O."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class CheckStatus(StrEnum):
    """Outcome of one dependency check."""

    OK = "ok"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


class FailureReason(StrEnum):
    """Why a check failed. Stable codes only: raw exception text never leaves the server."""

    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"
    AUTH_FAILED = "auth_failed"
    UNEXPECTED_RESPONSE = "unexpected_response"
    ERROR = "error"


class ProbeFailedError(Exception):
    """Raised by a probe with a stable reason code."""

    def __init__(self, reason: FailureReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


class DependencyProbe(Protocol):
    """Port implemented by infra: checks one backing service once."""

    @property
    def name(self) -> str:
        """Dependency name, e.g. `postgres`."""
        ...

    async def check(self, timeout_s: float) -> None:
        """Return if healthy; raise ProbeFailedError (or any exception) otherwise."""
        ...


@dataclass(frozen=True)
class CheckResult:
    """Result of checking one dependency."""

    name: str
    status: CheckStatus
    latency_ms: float | None = None
    reason: FailureReason | None = None


@dataclass(frozen=True)
class ReadinessReport:
    """All dependency checks.

    Ready only if every dependency is OK: an unconfigured one counts as not ready, because the
    process cannot do its job without it.
    """

    checks: Mapping[str, CheckResult]

    @property
    def ready(self) -> bool:
        """True when every check passed."""
        return all(result.status is CheckStatus.OK for result in self.checks.values())

    @property
    def failed(self) -> list[str]:
        """Names of the dependencies that are not OK."""
        return [name for name, r in self.checks.items() if r.status is not CheckStatus.OK]

    @classmethod
    def of(cls, results: Iterable[CheckResult]) -> "ReadinessReport":
        """Report keyed by dependency name, in the given order."""
        return cls(checks={r.name: r for r in results})
