"""The timing report survives parallel test workers and never fails a test (#303's flake)."""

import json
import multiprocessing
import warnings
from pathlib import Path

import pytest

from tooling import timing


def _write(path: str, index: int) -> None:
    import os  # noqa: PLC0415 - a fresh process

    os.environ["SUPPORTX_PERF_REPORT"] = path
    for round_ in range(20):
        timing.record(f"worker{index}.{round_}", {"ms": index})


def test_parallel_workers_never_break_the_report(tmp_path: Path) -> None:
    report = tmp_path / "perf.json"
    context = multiprocessing.get_context("spawn")
    workers = [context.Process(target=_write, args=(str(report), i)) for i in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
        assert worker.exitcode == 0
    found = json.loads(report.read_text())
    assert len(found) == 8 * 20  # every write kept, none lost to a race


def test_a_broken_report_is_a_warning_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "perf.json"
    report.write_text('{"a": 1}{"b": 2}')  # "Extra data", as on #303
    monkeypatch.setenv("SUPPORTX_PERF_REPORT", str(report))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        timing.record("x", 1)
    assert any("timing report not written" in str(w.message) for w in caught)
