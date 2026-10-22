"""Readiness service: runs every dependency probe concurrently with a hard timeout."""

import asyncio
import time
from collections.abc import Sequence

from app.core.logging import get_logger
from app.modules.system.domain.readiness import (
    CheckResult,
    CheckStatus,
    DependencyProbe,
    FailureReason,
    ProbeFailedError,
    ReadinessReport,
)

log = get_logger(__name__)


class ReadinessService:
    """Checks the backing services this process needs before it may receive traffic."""

    def __init__(
        self,
        probes: Sequence[DependencyProbe],
        *,
        not_configured: Sequence[str] = (),
        timeout: float,
    ) -> None:
        self._probes = tuple(probes)
        self._not_configured = tuple(not_configured)
        self._timeout = timeout

    async def check(self) -> ReadinessReport:
        """Run all probes at once; total time is bounded by the timeout, not their sum."""
        results = await asyncio.gather(*(self._run(probe) for probe in self._probes))
        missing = [CheckResult(name, CheckStatus.NOT_CONFIGURED) for name in self._not_configured]
        return ReadinessReport.of([*results, *missing])

    async def _run(self, probe: DependencyProbe) -> CheckResult:
        started = time.perf_counter()
        reason: FailureReason | None = None
        try:
            # Outer bound in case a client library ignores its own timeout.
            async with asyncio.timeout(self._timeout + 0.5):
                await probe.check(self._timeout)
        except TimeoutError:
            reason = FailureReason.TIMEOUT
        except ProbeFailedError as exc:
            reason = exc.reason
        except OSError:
            reason = FailureReason.UNREACHABLE
        except Exception:  # any probe failure means "not ready", never a 500
            reason = FailureReason.ERROR
            log.warning("readiness_probe_error", dependency=probe.name, exc_info=True)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        if reason is not None:
            log.warning("readiness_probe_failed", dependency=probe.name, reason=reason.value)
            return CheckResult(probe.name, CheckStatus.FAILED, latency_ms, reason)
        return CheckResult(probe.name, CheckStatus.OK, latency_ms)
