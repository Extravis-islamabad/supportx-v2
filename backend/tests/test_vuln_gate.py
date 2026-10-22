import io
import json
import urllib.request
from pathlib import Path
from typing import Self

import pytest

from tooling.vuln_gate import classify, ghsa_of, github_severity, main, render

REPORT = {
    "dependencies": [
        {"name": "fastapi", "version": "1.0.0", "vulns": []},
        {
            "name": "jinja2",
            "version": "2.10",
            "vulns": [
                {"id": "PYSEC-1", "aliases": ["CVE-1", "GHSA-high"], "fix_versions": ["2.11"]},
                # Same advisory reported twice under another id: counted once.
                {"id": "PYSEC-1b", "aliases": ["GHSA-high"], "fix_versions": ["2.11"]},
                {"id": "GHSA-low", "aliases": [], "fix_versions": []},
            ],
        },
        {"name": "orphan", "version": "0.1", "vulns": [{"id": "PYSEC-9", "aliases": ["CVE-9"]}]},
    ],
}
SEVERITIES = {"GHSA-high": "HIGH", "GHSA-low": "low", "GHSA-mod": "moderate"}


def lookup(ghsa: str) -> str | None:
    return SEVERITIES.get(ghsa)


def test_ghsa_of_prefers_ghsa_id_or_alias() -> None:
    assert ghsa_of({"id": "GHSA-x", "aliases": []}) == "GHSA-x"
    assert ghsa_of({"id": "PYSEC-1", "aliases": ["CVE-1", "GHSA-y"]}) == "GHSA-y"
    assert ghsa_of({"id": "PYSEC-1", "aliases": ["CVE-1"]}) is None


def test_classify_dedupes_and_sorts_blocking_first() -> None:
    findings = classify(REPORT, lookup)
    assert [(f.package, f.severity, f.blocking) for f in findings] == [
        ("jinja2", "high", True),
        ("orphan", "unknown", True),
        ("jinja2", "low", False),
    ]


def test_render_lists_every_finding() -> None:
    table = render(classify(REPORT, lookup))
    assert "GHSA-high" in table
    assert "PYSEC-9" in table
    assert "| 2.11 |" in table
    assert render([]) == "pip-audit: no known vulnerabilities.\n"


def write(tmp_path: Path, report: object) -> str:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return str(path)


def test_main_fails_on_high_and_writes_step_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert main([write(tmp_path, REPORT)], lookup) == 1
    assert "failing" in capsys.readouterr().out
    assert "GHSA-high" in summary.read_text(encoding="utf-8")


def test_main_passes_on_low_and_moderate_only(tmp_path: Path) -> None:
    report = {
        "dependencies": [
            {"name": "a", "version": "1", "vulns": [{"id": "GHSA-low"}, {"id": "GHSA-mod"}]},
        ],
    }
    assert main([write(tmp_path, report)], lookup) == 0


def test_main_requires_one_argument() -> None:
    assert main([], lookup) == 2


class FakeResponse(io.BytesIO):
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def test_github_severity_reads_advisory_and_sends_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[urllib.request.Request] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> FakeResponse:
        seen.append(request)
        assert timeout > 0
        return FakeResponse(b'{"severity": "critical"}')

    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert github_severity("GHSA-abcd") == "critical"
    assert seen[0].full_url.endswith("/advisories/GHSA-abcd")
    assert seen[0].get_header("Authorization") == "Bearer t0ken"


def test_github_severity_returns_none_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_urlopen(request: urllib.request.Request, timeout: float) -> FakeResponse:
        raise OSError(request.full_url, timeout)

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)
    assert github_severity("GHSA-abcd") is None
