"""The /ready check of ClamAV's signature age (WP-014b): informational, cached, a stable code."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.system.domain.readiness import FailureReason, ProbeFailedError
from app.modules.system.infra.probes import MalwareSignaturesProbe
from app.shared.files.infra.scanner import ScannerUnavailableError, ScannerVersion, Verdict


class FakeScanner:
    available = True

    def __init__(self, age: timedelta | None, *, down: bool = False) -> None:
        self.age = age
        self.down = down
        self.asked = 0

    async def scan(self, data: AsyncIterator[bytes]) -> Verdict:
        del data
        raise AssertionError  # never scans here

    async def version(self) -> ScannerVersion:
        self.asked += 1
        if self.down:
            raise ScannerUnavailableError
        date = None if self.age is None else datetime.now(UTC) - self.age
        return ScannerVersion("1.5.4", 27800, date)


def probe(scanner: FakeScanner, cache_seconds: float = 60.0) -> MalwareSignaturesProbe:
    return MalwareSignaturesProbe(
        scanner, stale_after=timedelta(hours=48), cache_seconds=cache_seconds
    )


async def test_fresh_signatures_pass() -> None:
    await probe(FakeScanner(timedelta(hours=3))).check(1.0)


async def test_signatures_older_than_the_limit_are_reported_stale() -> None:
    with pytest.raises(ProbeFailedError) as failed:
        await probe(FakeScanner(timedelta(hours=49))).check(1.0)
    assert failed.value.reason is FailureReason.STALE_SIGNATURES


async def test_an_unreachable_scanner_is_reported_unreachable() -> None:
    with pytest.raises(ProbeFailedError) as failed:
        await probe(FakeScanner(None, down=True)).check(1.0)
    assert failed.value.reason is FailureReason.UNREACHABLE


async def test_an_engine_without_a_date_is_not_judged() -> None:
    await probe(FakeScanner(None)).check(1.0)


async def test_clamd_is_asked_at_most_once_per_cache_period() -> None:
    scanner = FakeScanner(timedelta(hours=49))
    checking = probe(scanner)
    for _ in range(3):
        with pytest.raises(ProbeFailedError):
            await checking.check(1.0)
    assert scanner.asked == 1
    fresh = FakeScanner(timedelta(hours=1))
    uncached = probe(fresh, cache_seconds=0)
    await uncached.check(1.0)
    await uncached.check(1.0)
    assert fresh.asked == 2
