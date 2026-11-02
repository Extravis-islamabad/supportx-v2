"""When a connector counts as failing, and when its admins hear about it (WP-040; REQ-INT-005).

Pure rules, no I/O. Defaults approved with D-118 (Appendix A, tenant-editable later):
failing after 3 failed runs in a row, or at once when the outside system refused the credential;
errors kept 90 days; secrets reminded after 180 days; directory sync every 30 minutes.

Admins are told once when a connector turns failing and once when it recovers, never per call
(REQ-INT-005 AC2, REQ-NTF-027): fifty failed calls in an hour are one notice.
"""

from dataclasses import dataclass
from enum import StrEnum

FAILING_AFTER_RUNS = 3
ERROR_RETENTION_DAYS = 90
RUN_RETENTION_DAYS = 7  # the 24-hour counts need a day; a week helps an admin look back
ROTATION_REMINDER_DAYS = 180
SYNC_MINUTES = 30


class Notice(StrEnum):
    """What one run tells the connector's admins, if anything."""

    FAILING = "failing"
    RECOVERED = "recovered"


@dataclass(frozen=True)
class Health:
    """A connector instance's standing between runs."""

    failing: bool = False
    consecutive_failures: int = 0


def after_run(
    health: Health, *, ok: bool, auth_failure: bool, failing_after: int = FAILING_AFTER_RUNS
) -> tuple[Health, Notice | None]:
    """The standing after one run, and the notice it sends (at most one per change)."""
    if ok:
        return Health(), (Notice.RECOVERED if health.failing else None)
    failures = health.consecutive_failures + 1
    failing = health.failing or auth_failure or failures >= max(failing_after, 1)
    notice = Notice.FAILING if failing and not health.failing else None
    return Health(failing=failing, consecutive_failures=failures), notice


@dataclass(frozen=True)
class RunCounts:
    """What one run did (REQ-INT-004): read from outside, and what it made of it here."""

    read: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
