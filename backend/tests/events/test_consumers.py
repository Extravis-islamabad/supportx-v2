"""Consumer framework against real PostgreSQL and NATS JetStream (WP-007)."""

import io
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.shared.events import ConsumerSpec, EventEnvelope
from tests.db.probe import ProbeItem, ProbeRepository
from tests.events.conftest import RelayFactory, RunnerFactory, emit, run_until
from workers import bus
from workers.consumers.runner import ConsumerRunner
from workers.events_cli import dead_letters, format_dead_letter, replay

pytestmark = [pytest.mark.db, pytest.mark.nats]


class SimulatedCrash(BaseException):
    """The worker process dies here (not an Exception, so nothing handles it)."""


async def publish_all(make_relay: RelayFactory) -> None:
    relay = make_relay()
    await relay.connect()
    try:
        await relay.drain()
    finally:
        await relay.close()


async def probe_titles(db: Database, tenant: uuid.UUID) -> list[str]:
    async with db.tenant_session(TenantContext(tenant)) as session:
        return [item.title for item in (await ProbeRepository(session).list(limit=200)).items]


async def processed_rows(db: Database, tenant: uuid.UUID, consumer: str) -> int:
    async with db.tenant_session(TenantContext(tenant)) as session:
        result = await session.execute(
            text("SELECT count(*) FROM processed_events WHERE consumer = :c"), {"c": consumer}
        )
        return int(result.scalar_one())


def recording_spec(name: str, seen: list[str]) -> ConsumerSpec:
    """Handler that writes a probe row per event, in the event's transaction."""

    async def apply(event: EventEnvelope, session: AsyncSession | None) -> None:
        assert session is not None
        tenant_setting = (
            await session.execute(text("SELECT current_setting('app.tenant_id', true)"))
        ).scalar_one()
        assert tenant_setting == str(event.tenant_id)  # SET LOCAL from the event, as in WP-005
        await ProbeRepository(session).add(ProbeItem(title=str(event.event_id)))
        seen.append(str(event.event_id))

    return ConsumerSpec(name=name, event_types=("probe.item.happened",), handler=apply)


async def test_handler_runs_in_the_events_tenant_with_an_idempotency_record(
    app_db: Database,
    make_relay: RelayFactory,
    make_runner: RunnerFactory,
    tenant_pair: tuple[uuid.UUID, uuid.UUID],
) -> None:
    a, b = tenant_pair
    (event_a,) = await emit(app_db, a)
    (event_b,) = await emit(app_db, b)
    await publish_all(make_relay)
    seen: list[str] = []
    runner = make_runner(recording_spec("probe__tenants", seen))

    async def both() -> bool:
        return len(seen) == 2

    await run_until([runner.run], both)
    assert await probe_titles(app_db, a) == [str(event_a.event_id)]
    assert await probe_titles(app_db, b) == [str(event_b.event_id)]
    assert await processed_rows(app_db, a, runner.name) == 1
    assert await processed_rows(app_db, b, runner.name) == 1

    # Delivering the same event again (as JetStream may) changes nothing.
    assert await runner.process(event_a) is False
    assert await probe_titles(app_db, a) == [str(event_a.event_id)]


async def test_crash_mid_handler_is_redelivered_and_applied_once(
    app_db: Database, make_relay: RelayFactory, make_runner: RunnerFactory, tenant: uuid.UUID
) -> None:
    (event,) = await emit(app_db, tenant)
    await publish_all(make_relay)
    attempts: list[int] = []

    async def crash_first_time(envelope: EventEnvelope, session: AsyncSession | None) -> None:
        assert session is not None
        await ProbeRepository(session).add(ProbeItem(title=str(envelope.event_id)))
        attempts.append(1)
        if len(attempts) == 1:
            raise SimulatedCrash  # after writing, before commit: everything rolls back

    spec = ConsumerSpec(
        name="probe__crash_mid", event_types=("probe.item.happened",), handler=crash_first_time
    )
    crashed = make_runner(spec)

    async def crashed_once() -> bool:
        return len(attempts) == 1

    (ended,) = await run_until([crashed.run], crashed_once)
    assert isinstance(ended, SimulatedCrash)
    assert await probe_titles(app_db, tenant) == []  # the crash rolled the effect back

    restarted = make_runner(spec)  # a new process binds to the same durable consumer

    async def applied() -> bool:
        return restarted.metrics.processed.get(spec.name, 0) == 1

    await run_until([restarted.run], applied)  # redelivered after ack_wait (1 s in tests)
    assert len(attempts) == 2
    assert await probe_titles(app_db, tenant) == [str(event.event_id)]
    assert await processed_rows(app_db, tenant, spec.name) == 1


class CrashBeforeAck(ConsumerRunner):
    """Commits the handler's transaction, then dies before acknowledging the message."""

    crashes = 0

    async def before_ack(self, envelope: EventEnvelope) -> None:
        del envelope
        if CrashBeforeAck.crashes == 0:
            CrashBeforeAck.crashes += 1
            raise SimulatedCrash


async def test_crash_between_commit_and_ack_skips_the_redelivery(
    app_db: Database, make_relay: RelayFactory, make_runner: RunnerFactory, tenant: uuid.UUID
) -> None:
    (event,) = await emit(app_db, tenant)
    await publish_all(make_relay)
    seen: list[str] = []
    spec = recording_spec("probe__crash_ack", seen)
    CrashBeforeAck.crashes = 0
    crashed = make_runner(spec, CrashBeforeAck)

    async def handled() -> bool:
        return len(seen) == 1

    (ended,) = await run_until([crashed.run], handled)
    assert isinstance(ended, SimulatedCrash)

    restarted = make_runner(spec)

    async def skipped() -> bool:
        return restarted.metrics.duplicates.get(spec.name, 0) == 1

    await run_until([restarted.run], skipped)
    assert seen == [str(event.event_id)]  # the handler never ran again
    assert await probe_titles(app_db, tenant) == [str(event.event_id)]


async def test_poison_message_is_retried_then_dead_lettered_and_replays_after_a_fix(
    app_db: Database,
    event_bus: bus.Bus,
    make_relay: RelayFactory,
    make_runner: RunnerFactory,
    tenant: uuid.UUID,
) -> None:
    (poison, healthy) = await emit(app_db, tenant, count=2)
    await publish_all(make_relay)
    broken = {"yes": True}
    attempts: list[str] = []

    async def fragile(envelope: EventEnvelope, session: AsyncSession | None) -> None:
        assert session is not None
        attempts.append(str(envelope.event_id))
        if broken["yes"] and envelope.event_id == poison.event_id:
            msg = "cannot handle note"
            raise ValueError(msg)
        await ProbeRepository(session).add(ProbeItem(title=str(envelope.event_id)))

    spec = ConsumerSpec(name="probe__poison", event_types=("probe.item.happened",), handler=fragile)
    runner = make_runner(spec)  # max_attempts=3 in the test settings

    async def parked() -> bool:
        return runner.metrics.dead_lettered.get(spec.name, 0) == 1

    await run_until([runner.run], parked)
    assert attempts.count(str(poison.event_id)) == 3
    assert runner.metrics.retried[spec.name] == 2
    assert await probe_titles(app_db, tenant) == [str(healthy.event_id)]  # others carry on

    (letter,) = await dead_letters(event_bus.js, event_bus.names)
    assert letter.consumer == spec.name
    assert letter.headers["Supportx-Attempts"] == "3"
    assert letter.headers["Supportx-Error-Type"] == "ValueError"
    assert letter.headers["Supportx-Error"] == "cannot handle note"
    assert str(poison.event_id) in format_dead_letter(letter)

    broken["yes"] = False  # the fix is deployed
    assert await replay(event_bus.js, event_bus.names, letter) is True
    assert await dead_letters(event_bus.js, event_bus.names) == []

    async def recovered() -> bool:
        return runner.metrics.processed.get(spec.name, 0) == 2

    await run_until([runner.run], recovered)
    assert sorted(await probe_titles(app_db, tenant)) == sorted(
        [str(healthy.event_id), str(poison.event_id)]
    )
    assert await processed_rows(app_db, tenant, spec.name) == 2


async def test_replay_reaches_only_the_consumer_it_is_addressed_to(
    app_db: Database,
    event_bus: bus.Bus,
    make_relay: RelayFactory,
    make_runner: RunnerFactory,
    tenant: uuid.UUID,
) -> None:
    await emit(app_db, tenant)
    await publish_all(make_relay)
    failing_seen: list[str] = []

    async def always_fails(envelope: EventEnvelope, session: AsyncSession | None) -> None:
        del session
        failing_seen.append(str(envelope.event_id))
        raise RuntimeError

    failing = make_runner(
        ConsumerSpec(
            name="probe__fails", event_types=("probe.item.happened",), handler=always_fails
        )
    )
    other_seen: list[str] = []
    other = make_runner(recording_spec("probe__other", other_seen))

    async def settled() -> bool:
        return failing.metrics.dead_lettered.get(failing.name, 0) == 1 and len(other_seen) == 1

    await run_until([failing.run, other.run], settled)
    (letter,) = await dead_letters(event_bus.js, event_bus.names, consumer="probe__fails")
    await replay(event_bus.js, event_bus.names, letter)

    async def failed_again() -> bool:
        return failing.metrics.dead_lettered.get(failing.name, 0) == 2

    await run_until([failing.run, other.run], failed_again)
    assert len(other_seen) == 1  # the other consumer never saw the replay


async def test_malformed_message_goes_straight_to_the_dead_letter_stream(
    event_bus: bus.Bus, make_runner: RunnerFactory, tenant: uuid.UUID
) -> None:
    await event_bus.js.publish(
        event_bus.names.event_subject(tenant, "probe.item.happened"),
        b"{not json",
        stream=event_bus.names.events_stream,
    )

    async def nothing(_event: EventEnvelope, _session: AsyncSession | None) -> None:
        raise AssertionError

    runner = make_runner(
        ConsumerSpec(name="probe__malformed", event_types=("probe.item.happened",), handler=nothing)
    )

    async def parked() -> bool:
        return runner.metrics.dead_lettered.get(runner.name, 0) == 1

    await run_until([runner.run], parked)
    (letter,) = await dead_letters(event_bus.js, event_bus.names)
    assert letter.headers["Supportx-Attempts"] == "1"  # no retries for unparseable data
    assert letter.envelope() is None
    assert await replay(event_bus.js, event_bus.names, letter) is False  # left for a human
    assert "(unparseable message)" in format_dead_letter(letter)


async def test_non_transactional_consumer_gets_no_session(
    app_db: Database, make_relay: RelayFactory, make_runner: RunnerFactory, tenant: uuid.UUID
) -> None:
    (event,) = await emit(app_db, tenant)
    await publish_all(make_relay)
    sessions: list[AsyncSession | None] = []

    async def log_only(_event: EventEnvelope, session: AsyncSession | None) -> None:
        sessions.append(session)

    runner = make_runner(
        ConsumerSpec(name="probe__log", event_types=(">",), handler=log_only, transactional=False)
    )

    async def received() -> bool:
        return len(sessions) == 1

    await run_until([runner.run], received)
    assert sessions == [None]
    assert await processed_rows(app_db, tenant, runner.name) == 0
    del event


async def test_consumer_declaration_is_applied_idempotently(
    event_bus: bus.Bus, make_runner: RunnerFactory
) -> None:
    async def noop(_event: EventEnvelope, _session: AsyncSession | None) -> None:
        return None

    runner = make_runner(
        ConsumerSpec(name="probe__declared", event_types=("probe.item.happened",), handler=noop)
    )
    await runner.ensure()
    await runner.ensure()
    info = await event_bus.js.consumer_info(event_bus.names.events_stream, runner.name)
    assert info.config.filter_subjects == [
        event_bus.names.event_filter("probe.item.happened"),
        event_bus.names.replay_filter(runner.name),
    ]
    assert info.config.max_deliver == -1
    widened = make_runner(
        ConsumerSpec(name="probe__declared", event_types=("probe.>",), handler=noop)
    )
    await widened.ensure()  # a changed declaration updates the server-side consumer
    info = await event_bus.js.consumer_info(event_bus.names.events_stream, runner.name)
    assert info.config.filter_subjects is not None
    assert info.config.filter_subjects[0] == event_bus.names.event_filter("probe.>")


async def test_cli_formats_and_lists(event_bus: bus.Bus) -> None:
    out = io.StringIO()
    from workers.events_cli import COMMANDS, build_parser  # noqa: PLC0415 - CLI under test

    await COMMANDS["dlq-list"](build_parser().parse_args(["dlq-list"]), event_bus, out)
    await COMMANDS["stats"](build_parser().parse_args(["stats"]), event_bus, out)
    assert await COMMANDS["dlq-replay"](build_parser().parse_args(["dlq-replay"]), event_bus, out)
    text_out = out.getvalue()
    assert "0 dead letter(s)" in text_out
    assert "no worker heartbeats" in text_out
    assert "choose --seq N" in text_out
