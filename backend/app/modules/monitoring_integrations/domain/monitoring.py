"""The pure rules of reading MonetX (WP-053 S6; ADR-017: SupportX reads, never monitors). No I/O.

- **Health** is one of five codes per CI. MonetX's own status words are mapped onto them, and
  anything unknown reads `unknown`, never an error.
- **The breaker** opens after a run of failures for a connection and closes after a quiet
  period. While open, health is `unknown` with the reason `monitoring_unreachable`, and MonetX
  isn't asked again.
- **Topology** marks a device not seen in a run `stale`, and after `ENDED_AFTER` runs in a row
  `ended`. Seen again, it's `seen` with the count reset. Nothing is ever deleted.
- **The site map** turns a MonetX group into a SupportX site, by the admin's map.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


class HealthState(StrEnum):
    """A CI's monitoring health (`monitoring_health.<code>`)."""

    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"
    UNMONITORED = "unmonitored"


class DeviceState(StrEnum):
    """A mapped device's topology state (`monitoring_device_state.<code>`)."""

    SEEN = "seen"
    STALE = "stale"
    ENDED = "ended"


class RunState(StrEnum):
    """A topology run (`monitoring_run_state.<code>`)."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# Reasons (`errors.<code>`): codes only, never MonetX's own text.
UNREACHABLE = "monitoring_unreachable"
NOT_REACHABLE_FROM_SAAS = "monitoring_not_reachable_from_saas"
NO_SECRET = "monitoring_secret_missing"  # noqa: S105 - a reason code
REFUSED = "monitoring_refused"
INVALID_ANSWER = "monitoring_invalid_answer"
TOO_LARGE = "monitoring_too_large"  # more items than one import holds (lane C, #640)

ENDED_AFTER = 3  # missed runs in a row before a device is ended
HEALTH_IDS_MAX = 200
CACHE_SECONDS = 15

_STATUS: Mapping[str, HealthState] = {
    "up": HealthState.UP,
    "ok": HealthState.UP,
    "healthy": HealthState.UP,
    "warning": HealthState.DEGRADED,
    "degraded": HealthState.DEGRADED,
    "down": HealthState.DOWN,
    "critical": HealthState.DOWN,
    "unreachable": HealthState.DOWN,
}


def health_of(status: object) -> HealthState:
    """MonetX's status word as a health code (anything unknown: `unknown`)."""
    return _STATUS.get(str(status).strip().lower(), HealthState.UNKNOWN)


@dataclass(frozen=True)
class Breaker:
    """A connection's circuit breaker (no I/O: the caller keeps it and passes the time)."""

    failures: int = 0
    opened_at: datetime | None = None
    threshold: int = 3
    cool_down: timedelta = timedelta(seconds=60)

    def is_open(self, now: datetime) -> bool:
        """Open: MonetX isn't asked; health reads `unknown` until the cool-down passes."""
        return self.opened_at is not None and now - self.opened_at < self.cool_down

    def failed(self, now: datetime) -> "Breaker":
        """One more failure; open at the threshold."""
        failures = self.failures + 1
        opened = now if failures >= self.threshold else self.opened_at
        return replace(self, failures=failures, opened_at=opened)

    def succeeded(self) -> "Breaker":
        """A good answer closes it."""
        return replace(self, failures=0, opened_at=None)


@dataclass(frozen=True)
class DeviceAfterRun:
    """A device's topology state after a run, and whether to retire its CI now."""

    state: DeviceState
    missed_runs: int
    retire: bool


def after_run(*, seen: bool, missed_runs: int, state: DeviceState) -> DeviceAfterRun:
    """Seen resets it; missed once makes it stale; missed `ENDED_AFTER` times in a row ends it."""
    if seen:
        return DeviceAfterRun(DeviceState.SEEN, 0, retire=False)
    missed = missed_runs + 1
    if missed >= ENDED_AFTER:
        return DeviceAfterRun(DeviceState.ENDED, missed, retire=state is not DeviceState.ENDED)
    return DeviceAfterRun(DeviceState.STALE, missed, retire=False)


def site_for(site_map: Mapping[str, Any], group: object) -> str | None:
    """The SupportX site ID a MonetX group maps to (the admin's map), or None."""
    if group is None:
        return None
    found = site_map.get(str(group))
    return str(found) if isinstance(found, str) and found else None


# MonetX device kinds onto the CMDB's built-in CI types (by API name); others are hardware.
_KINDS: Mapping[str, str] = {
    "server": "server",
    "host": "server",
    "vm": "server",
    "router": "network_device",
    "switch": "network_device",
    "firewall": "network_device",
    "access_point": "network_device",
}


def ci_type_for(kind: object) -> str:
    """The CI type API name a MonetX device kind becomes."""
    return _KINDS.get(str(kind).strip().lower(), "hardware")
