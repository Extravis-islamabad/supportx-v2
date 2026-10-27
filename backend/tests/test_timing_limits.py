"""Timing limits (tooling/timing.py): the target at night, ten times it in pull requests."""

from pathlib import Path

import pytest

from tooling import timing


def test_pull_requests_get_ten_times_the_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPPORTX_PERF_STRICT", raising=False)
    assert timing.limit(5) == 50


def test_the_nightly_run_asserts_the_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPPORTX_PERF_STRICT", "1")
    assert timing.limit(5) == 5


def test_measurements_go_to_the_report_when_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "perf.json"
    monkeypatch.setenv("SUPPORTX_PERF_REPORT", str(report))
    timing.record("a", {"p95_ms": 1.5})
    timing.record("b", 2)
    assert report.read_text().count('"p95_ms"') == 1
    monkeypatch.delenv("SUPPORTX_PERF_REPORT")
    timing.record("c", 3)  # nothing asked: nothing written, no error
