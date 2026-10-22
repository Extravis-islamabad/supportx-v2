import asyncio
import time

import pytest

from app.modules.system.domain.readiness import (
    CheckStatus,
    FailureReason,
    ProbeFailedError,
    ReadinessReport,
)
from app.modules.system.service.readiness import ReadinessService


class FakeProbe:
    def __init__(self, name: str, outcome: BaseException | float | None = None) -> None:
        self.name = name
        self._outcome = outcome
        self.timeouts: list[float] = []

    async def check(self, timeout_s: float) -> None:
        self.timeouts.append(timeout_s)
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        if isinstance(self._outcome, float):
            await asyncio.sleep(self._outcome)


async def test_all_ok_means_ready() -> None:
    service = ReadinessService([FakeProbe("postgres"), FakeProbe("nats")], timeout=1.0)
    report = await service.check()
    assert report.ready
    assert report.failed == []
    assert [r.status for r in report.checks.values()] == [CheckStatus.OK, CheckStatus.OK]
    assert all(r.latency_ms is not None for r in report.checks.values())


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (ProbeFailedError(FailureReason.AUTH_FAILED), FailureReason.AUTH_FAILED),
        (ConnectionRefusedError(), FailureReason.UNREACHABLE),
        (TimeoutError(), FailureReason.TIMEOUT),
        (RuntimeError("driver bug"), FailureReason.ERROR),
    ],
)
async def test_failures_are_reported_with_a_reason_code(
    outcome: BaseException, reason: FailureReason
) -> None:
    service = ReadinessService([FakeProbe("postgres"), FakeProbe("valkey", outcome)], timeout=1.0)
    report = await service.check()
    assert not report.ready
    assert report.failed == ["valkey"]
    assert report.checks["valkey"].status is CheckStatus.FAILED
    assert report.checks["valkey"].reason is reason


async def test_hanging_probe_is_cut_off_and_probes_run_concurrently() -> None:
    probes = [FakeProbe("postgres", 5.0), FakeProbe("valkey", 5.0), FakeProbe("nats")]
    service = ReadinessService(probes, timeout=0.1)
    started = time.perf_counter()
    report = await service.check()
    elapsed = time.perf_counter() - started
    assert elapsed < 1.5  # one shared deadline (0.1 s + 0.5 s grace), not one per probe
    assert report.checks["postgres"].reason is FailureReason.TIMEOUT
    assert report.checks["valkey"].reason is FailureReason.TIMEOUT
    assert report.checks["nats"].status is CheckStatus.OK
    assert probes[2].timeouts == [0.1]


async def test_unconfigured_dependencies_make_the_process_not_ready() -> None:
    service = ReadinessService([FakeProbe("postgres")], not_configured=["valkey"], timeout=1.0)
    report = await service.check()
    assert not report.ready
    assert report.failed == ["valkey"]
    assert report.checks["valkey"].status is CheckStatus.NOT_CONFIGURED


def test_empty_report_is_ready() -> None:
    assert ReadinessReport.of([]).ready


async def test_informational_checks_are_reported_but_never_block_readiness() -> None:
    service = ReadinessService(
        [FakeProbe("postgres")],
        informational=[FakeProbe("outbox_relay", ProbeFailedError(FailureReason.NOT_RUNNING))],
        timeout=1.0,
    )
    report = await service.check()
    assert report.ready
    assert report.failed == []
    assert report.degraded == ["outbox_relay"]
    relay = report.checks["outbox_relay"]
    assert (relay.status, relay.reason, relay.critical) == (
        CheckStatus.FAILED,
        FailureReason.NOT_RUNNING,
        False,
    )
