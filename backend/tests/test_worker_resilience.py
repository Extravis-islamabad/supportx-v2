"""Workers ride out PostgreSQL and NATS restarts, without containers (must-fix before pilot).

The shared stack's relay and fan-out died at 14:37 on 2026-10-28 with "the database system is
shutting down" (asyncpg CannotConnectNowError, which the relay did not count as an outage) and
NATS ServiceUnavailable. These pin the decisions; tests/resilience restarts real containers.
"""

import asyncio
from datetime import timedelta
from typing import Any

import asyncpg
import nats.errors
import nats.js.errors
import pytest
import sqlalchemy.exc

from app.shared.events import Actor, BusNames, ConsumerSpec, EventEnvelope
from workers import runtime
from workers.consumers.runner import ConsumerRunner, RetryPolicy
from workers.outbox_relay.relay import OutboxRelay
from workers.resilience import Connectivity, WorkerUnrecoverable, unavailable

SHUTTING_DOWN = "the database system is shutting down"
BUG = "a handler bug"
GAVE_UP = "database unavailable for more than 300 s"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            asyncpg.exceptions.CannotConnectNowError("the database system is shutting down"),
            "database",
        ),
        (asyncpg.exceptions.AdminShutdownError("terminating connection"), "database"),
        (asyncpg.exceptions.ConnectionDoesNotExistError("closed"), "database"),
        (asyncpg.exceptions.TooManyConnectionsError("too many"), "database"),
        (nats.js.errors.ServiceUnavailableError(), "bus"),
        (nats.errors.NoServersError(), "bus"),
        (ValueError("a handler bug"), None),
        (OSError("an SMTP server refused"), None),  # ambiguous: the runner asks the database
    ],
)
def test_outages_are_told_from_ordinary_failures(
    error: BaseException, expected: str | None
) -> None:
    assert unavailable(error) == expected


def test_a_wrapped_database_outage_is_still_an_outage() -> None:
    inner = asyncpg.exceptions.CannotConnectNowError(SHUTTING_DOWN)
    wrapped = sqlalchemy.exc.DBAPIError("SELECT 1", {}, inner)
    wrapped.__cause__ = inner
    assert unavailable(wrapped) == "database"


def test_connectivity_reports_and_gives_up_in_time() -> None:
    clock = Clock()
    connectivity = Connectivity(give_up_after=30, clock=clock)
    assert connectivity.snapshot() == {"connected": True, "unavailable": [], "stalled_seconds": 0}
    connectivity.down("database")
    clock.now = 29
    connectivity.check()
    assert connectivity.snapshot()["connected"] is False
    assert connectivity.snapshot()["unavailable"] == ["database"]
    assert 0.4 < connectivity.delay("database") < 0.7
    connectivity.down("database")
    assert 0.8 < connectivity.delay("database") < 1.3  # backs off
    clock.now = 31
    with pytest.raises(WorkerUnrecoverable, match="database unavailable"):
        connectivity.check()
    connectivity.up("database")
    connectivity.check()
    assert connectivity.connected


class FakeMessage:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def in_progress(self) -> None:
        self.calls.append("in_progress")

    async def nak(self, delay: float | None = None) -> None:
        self.calls.append(f"nak {delay}")


def _envelope() -> EventEnvelope:
    import uuid  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415 - local fixture

    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type="probe.item.happened",
        schema_version=1,
        tenant_id=uuid.uuid4(),
        actor=Actor.system("test"),
        occurred_at=datetime.now(UTC),
        aggregate_type="probe",
        aggregate_id="1",
        payload={},
    )


async def test_a_database_outage_holds_the_message_and_never_counts_as_an_attempt() -> None:
    failures = [
        asyncpg.exceptions.CannotConnectNowError("the database system is shutting down"),
        asyncpg.exceptions.CannotConnectNowError("the database system is starting up"),
    ]
    handled: list[str] = []

    async def handler(envelope: EventEnvelope, session: Any) -> None:  # noqa: ANN401 - unused
        del envelope, session
        if failures:
            raise failures.pop(0)
        handled.append("done")

    spec = ConsumerSpec(
        name="probe__resilience",
        event_types=("probe.item.happened",),
        handler=handler,
        transactional=False,
    )
    connectivity = Connectivity(give_up_after=60)
    setattr(connectivity, "delay", lambda _dependency: 0.0)  # noqa: B010 - no real waits
    runner = ConsumerRunner(
        spec,
        js=None,  # type: ignore[arg-type]  # not used by this path
        names=BusNames(""),
        database=None,
        retry=RetryPolicy(max_attempts=1, initial=1, maximum=1),
        ack_wait=30,
        connectivity=connectivity,
    )
    message = FakeMessage()
    assert await runner._process_through_outages(message, _envelope()) is True  # type: ignore[arg-type]  # noqa: SLF001
    assert handled == ["done"]
    assert message.calls == ["in_progress", "in_progress"]  # held, never naked or dead-lettered
    assert connectivity.connected


async def test_an_ordinary_failure_still_goes_to_retries() -> None:
    async def handler(_envelope: EventEnvelope, _session: Any) -> None:  # noqa: ANN401 - unused
        raise ValueError(BUG)

    spec = ConsumerSpec(
        name="probe__bug",
        event_types=("probe.item.happened",),
        handler=handler,
        transactional=False,
    )
    runner = ConsumerRunner(
        spec,
        js=None,  # type: ignore[arg-type]
        names=BusNames(""),
        database=None,
        retry=RetryPolicy(max_attempts=3, initial=1, maximum=1),
        ack_wait=30,
    )
    with pytest.raises(ValueError, match="handler bug"):
        await runner._process_through_outages(FakeMessage(), _envelope())  # type: ignore[arg-type]  # noqa: SLF001


async def test_the_relay_rides_out_a_database_that_is_shutting_down() -> None:
    stop = asyncio.Event()
    attempts: list[int] = []
    connectivity = Connectivity(give_up_after=60)
    setattr(connectivity, "delay", lambda _dependency: 0.0)  # noqa: B010 - no real waits
    relay = OutboxRelay(
        dsn="postgresql://unused",
        js=None,  # type: ignore[arg-type]
        names=BusNames(""),
        batch_size=10,
        poll_interval=1,
        publish_timeout=1,
        retention=timedelta(hours=1),
        purge_interval=60,
        connectivity=connectivity,
    )

    async def connect() -> None:
        attempts.append(1)
        if len(attempts) == 3:
            stop.set()
        raise asyncpg.exceptions.CannotConnectNowError(SHUTTING_DOWN)

    relay.connect = connect  # type: ignore[method-assign]
    await asyncio.wait_for(relay.run(stop), 5)  # returns: no crash
    assert len(attempts) == 3
    assert connectivity.snapshot()["unavailable"] == ["database"]


class _ShuttingDownPool:
    def acquire(self) -> "_ShuttingDownPool":
        return self

    async def __aenter__(self) -> None:
        raise asyncpg.exceptions.CannotConnectNowError(SHUTTING_DOWN)

    async def __aexit__(self, *exc: object) -> None:
        return None


async def test_the_backlog_reading_rides_out_a_database_that_is_shutting_down() -> None:
    """CI run 40690884110: the heartbeat's backlog read took the relay down with the database."""
    relay = OutboxRelay(
        dsn="postgresql://unused",
        js=None,  # type: ignore[arg-type]
        names=BusNames(""),
        batch_size=10,
        poll_interval=1,
        publish_timeout=1,
        retention=timedelta(hours=1),
        purge_interval=60,
    )
    relay.metrics.oldest_unpublished_age_seconds = 4.0
    relay._pool = _ShuttingDownPool()  # type: ignore[assignment]  # noqa: SLF001
    assert await relay.refresh_backlog_age() == 4.0  # the last age, no crash


def test_a_worker_that_gives_up_exits_with_code_1() -> None:
    async def gives_up(stop: asyncio.Event) -> None:
        del stop
        raise WorkerUnrecoverable(GAVE_UP)

    async def stops(stop: asyncio.Event) -> None:
        del stop

    assert runtime.run(gives_up) == 1
    assert runtime.run(stops) == 0
