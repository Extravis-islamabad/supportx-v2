"""Riding out PostgreSQL and NATS restarts (must-fix before the pilot, product owner 2026-10-28).

A worker keeps running while the database or the bus is away: it retries with backoff, says so
in its heartbeat and its readiness endpoint ("event delivery stalled" in /ready and the admins'
banner), and carries on where it stopped when the dependency is back. Nothing is lost or applied
twice: the outbox keeps unpublished rows, JetStream keeps unacknowledged messages, and consumers
claim each event once (docs/architecture/events.md).

If a dependency stays away longer than `worker_give_up_seconds`, the worker stops with a
non-zero exit (`WorkerUnrecoverable`) so the orchestrator restarts it, rather than looking alive
while doing nothing.

What counts as "the dependency is away" (and must never be charged to an event as a failed
attempt) is decided here once, by walking the exception chain: SQLAlchemy wraps asyncpg errors.
"""

import asyncio
import contextlib
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import asyncpg
import nats.errors
import nats.js.errors
import sqlalchemy.exc
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.logging import get_logger

log = get_logger(__name__)

Dependency = Literal["database", "bus"]
CHAIN_LIMIT = 10  # links of __cause__ / __context__ looked at

# asyncpg: the server is starting, shutting down, restarting, or the connection broke.
_DATABASE_ERRORS: tuple[type[BaseException], ...] = (
    asyncpg.PostgresConnectionError,  # includes ConnectionDoesNotExistError, CannotConnectNow…
    asyncpg.InterfaceError,
    asyncpg.exceptions.CannotConnectNowError,
    asyncpg.exceptions.AdminShutdownError,
    asyncpg.exceptions.CrashShutdownError,
    asyncpg.exceptions.TooManyConnectionsError,
    asyncpg.exceptions.ConnectionFailureError,
)
_BUS_ERRORS: tuple[type[BaseException], ...] = (
    nats.errors.ConnectionClosedError,
    nats.errors.ConnectionDrainingError,
    nats.errors.ConnectionReconnectingError,
    nats.errors.NoServersError,
    nats.errors.StaleConnectionError,
    nats.errors.OutboundBufferLimitError,
    nats.errors.NoRespondersError,
    nats.errors.TimeoutError,
    nats.js.errors.ServiceUnavailableError,
)


def _chain(error: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in seen and len(seen) < CHAIN_LIMIT:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return seen


def unavailable(error: BaseException) -> Dependency | None:
    """Which dependency an error clearly says is away, or None (ordinary, or ambiguous).

    A bare OSError or TimeoutError can also come from a handler's own call to another system, so
    it is not taken as an outage here: callers that need to know ask the dependency itself
    (`database_reachable`, the bus client's `is_connected`).
    """
    for link in _chain(error):
        if isinstance(link, _BUS_ERRORS):
            return "bus"
        if isinstance(link, _DATABASE_ERRORS):
            return "database"
        if isinstance(link, sqlalchemy.exc.DBAPIError) and link.connection_invalidated:
            return "database"
    return None


async def database_reachable(engine: AsyncEngine, within: float = 3.0) -> bool:
    """Whether the database answers `SELECT 1` now (decides ambiguous failures)."""
    try:
        async with asyncio.timeout(within), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure here means "not reachable"
        return False
    return True


class WorkerUnrecoverable(RuntimeError):
    """A dependency stayed away too long: exit non-zero and let the orchestrator restart us."""


@dataclass
class Connectivity:
    """What this worker can reach now. Drives readiness, the heartbeat and giving up."""

    give_up_after: float
    clock: Callable[[], float] = time.monotonic
    _down_since: dict[Dependency, float] = field(default_factory=dict)
    _attempts: dict[Dependency, int] = field(default_factory=dict)

    @property
    def connected(self) -> bool:
        """Both dependencies answered at the last try."""
        return not self._down_since

    def down(self, dependency: Dependency, error: BaseException | None = None) -> None:
        """A call failed because `dependency` is away (first time: logged)."""
        if dependency not in self._down_since:
            self._down_since[dependency] = self.clock()
            log.warning(
                "worker_dependency_unavailable",
                dependency=dependency,
                error_type=type(error).__name__ if error is not None else None,
            )
        self._attempts[dependency] = self._attempts.get(dependency, 0) + 1

    def up(self, dependency: Dependency) -> None:
        """`dependency` answered again."""
        since = self._down_since.pop(dependency, None)
        self._attempts.pop(dependency, None)
        if since is not None:
            log.info(
                "worker_dependency_back",
                dependency=dependency,
                down_seconds=round(self.clock() - since, 1),
            )

    def stalled_seconds(self) -> float:
        """How long the longest current outage has lasted (0 when connected)."""
        if not self._down_since:
            return 0.0
        return self.clock() - min(self._down_since.values())

    def check(self) -> None:
        """Raise WorkerUnrecoverable once an outage has lasted past `give_up_after`."""
        if self._down_since and self.stalled_seconds() > self.give_up_after:
            down = sorted(self._down_since)
            msg = f"{', '.join(down)} unavailable for more than {self.give_up_after:.0f} s"
            raise WorkerUnrecoverable(msg)

    def delay(self, dependency: Dependency) -> float:
        """Backoff before the next try: 0.5, 1, 2, 4 … 15 s, with jitter."""
        attempt = self._attempts.get(dependency, 1)
        base = min(0.5 * 2.0 ** max(attempt - 1, 0), 15.0)
        jitter: float = random.uniform(0.8, 1.2)  # noqa: S311 - jitter, not security
        return base * jitter

    def snapshot(self) -> dict[str, object]:
        """For the heartbeat: /ready reads `connected` to say event delivery is stalled."""
        return {
            "connected": self.connected,
            "unavailable": sorted(self._down_since),
            "stalled_seconds": round(self.stalled_seconds(), 1),
        }

    async def wait(self, dependency: Dependency, stop: asyncio.Event) -> None:
        """Back off before retrying (or less, if stopping), giving up when it is time."""
        self.check()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), self.delay(dependency))
