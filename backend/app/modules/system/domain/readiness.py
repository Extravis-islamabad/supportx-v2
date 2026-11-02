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
    NOT_RUNNING = "not_running"  # a worker that should send heartbeats sent none
    STALE_HEARTBEAT = "stale_heartbeat"  # its last heartbeat is too old
    DISCONNECTED = "disconnected"  # the worker runs but cannot reach PostgreSQL or NATS
    BACKLOG = "backlog"  # events wait to be published for longer than they should
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
    # Informational checks (the event workers) are reported but never make the API unready:
    # taking API pods out of service because the relay is down would turn a delay into an outage.
    critical: bool = True


@dataclass(frozen=True)
class ReadinessReport:
    """All dependency checks.

    Ready only if every critical dependency is OK: an unconfigured one counts as not ready,
    because the process cannot do its job without it.
    """

    checks: Mapping[str, CheckResult]

    @property
    def ready(self) -> bool:
        """True when every critical check passed."""
        return all(r.status is CheckStatus.OK for r in self.checks.values() if r.critical)

    @property
    def failed(self) -> list[str]:
        """Names of the critical dependencies that are not OK."""
        return [
            name for name, r in self.checks.items() if r.critical and r.status is not CheckStatus.OK
        ]

    @property
    def degraded(self) -> list[str]:
        """Names of informational checks that are not OK (e.g. the outbox relay is down)."""
        return [
            name
            for name, r in self.checks.items()
            if not r.critical and r.status is not CheckStatus.OK
        ]

    @classmethod
    def of(cls, results: Iterable[CheckResult]) -> "ReadinessReport":
        """Report keyed by dependency name, in the given order."""
        return cls(checks={r.name: r for r in results})
