"""Severity gate for pip-audit reports (WP-003, `make audit` and security.yml).

pip-audit lists every known vulnerability but carries no severity, so it cannot "fail only on
high/critical" by itself. This gate reads pip-audit's JSON report, looks up each finding's GitHub
advisory (GHSA) severity, prints all findings, and exits non-zero only for high or critical ones.
A finding with no GHSA alias, or whose severity cannot be fetched, is treated as high: an unknown
risk must not pass silently.

Usage: python -m tooling.vuln_gate <pip-audit-report.json>
"""

import json
import os
import sys
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

BLOCKING = frozenset({"high", "critical"})
UNKNOWN = "unknown"
ADVISORY_URL = "https://api.github.com/advisories/{ghsa}"

SeverityLookup = Callable[[str], str | None]


@dataclass(frozen=True)
class Finding:
    """One vulnerability affecting one installed package version."""

    package: str
    version: str
    vuln_id: str
    ghsa: str | None
    severity: str
    fix_versions: tuple[str, ...]

    @property
    def blocking(self) -> bool:
        """High, critical and unknown severities fail the gate."""
        return self.severity in BLOCKING or self.severity == UNKNOWN


def ghsa_of(vuln: Mapping[str, object]) -> str | None:
    """Return the GHSA identifier of a pip-audit vulnerability entry, if it has one."""
    aliases = vuln.get("aliases")
    candidates = [vuln.get("id"), *(aliases if isinstance(aliases, list) else [])]
    return next((c for c in candidates if isinstance(c, str) and c.startswith("GHSA-")), None)


def classify(report: Mapping[str, object], lookup: SeverityLookup) -> list[Finding]:
    """Turn a pip-audit JSON report into findings with severities (one per package+advisory)."""
    findings: dict[tuple[str, str], Finding] = {}
    dependencies = report.get("dependencies")
    for dep in dependencies if isinstance(dependencies, list) else []:
        for vuln in dep.get("vulns", []):
            ghsa = ghsa_of(vuln)
            key = (dep["name"], ghsa or vuln["id"])
            if key in findings:
                continue
            severity = (lookup(ghsa) if ghsa else None) or UNKNOWN
            findings[key] = Finding(
                package=dep["name"],
                version=dep.get("version", "?"),
                vuln_id=vuln["id"],
                ghsa=ghsa,
                severity=severity.lower(),
                fix_versions=tuple(vuln.get("fix_versions", [])),
            )
    return sorted(findings.values(), key=lambda f: (not f.blocking, f.package, f.vuln_id))


def render(findings: list[Finding]) -> str:
    """Markdown summary: readable in a terminal and in a GitHub job summary."""
    if not findings:
        return "pip-audit: no known vulnerabilities.\n"
    lines = [
        "| package | version | advisory | severity | fixed in | blocks |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {f.package} | {f.version} | {f.ghsa or f.vuln_id} | {f.severity} "
        f"| {', '.join(f.fix_versions) or '-'} | {'yes' if f.blocking else 'no'} |"
        for f in findings
    ]
    return "\n".join(lines) + "\n"


def github_severity(ghsa: str) -> str | None:
    """Fetch an advisory's severity from the GitHub advisory database (None if unavailable)."""
    request = urllib.request.Request(  # noqa: S310 - fixed https URL, not user-controlled
        ADVISORY_URL.format(ghsa=ghsa),
        headers={"Accept": "application/vnd.github+json"},
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - as above
            severity = json.load(response).get("severity")
    except (OSError, ValueError):
        return None
    return severity if isinstance(severity, str) else None


def main(argv: list[str], lookup: SeverityLookup = github_severity) -> int:
    """Print the findings table; return 1 if anything high, critical or unknown was found."""
    if len(argv) != 1:
        sys.stderr.write("usage: python -m tooling.vuln_gate <pip-audit-report.json>\n")
        return 2
    report = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    findings = classify(report, lookup)
    summary = render(findings)
    sys.stdout.write(summary)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(step_summary).open("a", encoding="utf-8") as fh:
            fh.write("### Backend dependencies (pip-audit)\n\n" + summary)
    blocking = [f for f in findings if f.blocking]
    if blocking:
        sys.stdout.write(f"{len(blocking)} high/critical (or unknown) finding(s): failing.\n")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv[1:]))
