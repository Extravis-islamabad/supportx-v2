"""The real worker entry points (make worker-relay / worker-consumers) and the operator CLI.

Runs both workers' `main()` in-process, configured only through SUPPORTX_* environment variables
exactly as `make` runs them, then watches the result through the same heartbeats /ready reads.
"""

import asyncio
import io
import json
import uuid
from typing import Any

import pytest

from app.core.config import Settings
from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.identity_access.events import UserLoggedIn
from app.shared.events import record_event
from tests.events.conftest import wait_for
from workers import bus, runtime
from workers.consumers import __main__ as consumers_main
from workers.events_cli import COMMANDS, build_parser, heartbeats, tail
from workers.metrics import RelayMetrics
from workers.outbox_relay import __main__ as relay_main

pytestmark = [pytest.mark.db, pytest.mark.nats]


@pytest.fixture
def worker_env(monkeypatch: pytest.MonkeyPatch, bus_settings: Settings) -> None:
    """Environment for the workers: the test's database, NATS and namespace."""

    def secret(value: Any) -> str:  # noqa: ANN401 - SecretStr | None from the fixture
        return str(value.get_secret_value())

    for name, value in {
        "SUPPORTX_PROFILE": "test",
        "SUPPORTX_LOG_LEVEL": "warning",
        "SUPPORTX_NATS_URL": secret(bus_settings.nats_url),
        "SUPPORTX_DATABASE_URL": secret(bus_settings.database_url),
        "SUPPORTX_RELAY_DATABASE_URL": secret(bus_settings.relay_database_url),
        "SUPPORTX_EVENTS_NAMESPACE": bus_settings.events_namespace,
        "SUPPORTX_DEV_EVENT_LOGGER": "true",
        "SUPPORTX_HEARTBEAT_INTERVAL_SECONDS": "0.2",
        "SUPPORTX_RELAY_POLL_INTERVAL_SECONDS": "0.5",
        # Audit schedules would seal other tests' entries and add stream messages (WP-018).
        "SUPPORTX_WORKER_SCHEDULES_ENABLED": "false",
    }.items():
        monkeypatch.setenv(name, value)


async def test_workers_relay_and_consume_and_report_heartbeats(
    worker_env: None,
    clean_outbox: None,
    event_bus: bus.Bus,
    app_db: Database,
    tenant: uuid.UUID,
) -> None:
    del worker_env, clean_outbox
    stop = asyncio.Event()
    workers = [
        asyncio.create_task(relay_main.main(stop)),
        asyncio.create_task(consumers_main.main(stop)),
    ]
    printed = io.StringIO()
    tail_stop = asyncio.Event()
    tailing = asyncio.create_task(
        tail(
            event_bus.js,
            event_bus.names,
            tenant=str(tenant),
            pattern="identity_access.>",
            since="all",
            out=printed,
            stop=tail_stop,
        )
    )
    try:

        async def both_alive() -> bool:
            beats = await heartbeats(event_bus.heartbeats)
            return {key.split(".", 1)[0] for key in beats} == {"relay", "consumers"}

        await wait_for(both_alive, within=15)
        async with app_db.tenant_session(TenantContext(tenant)) as session:
            user = uuid.uuid4()
            await record_event(
                session, UserLoggedIn(user_id=user, client="portal"), aggregate_id=user
            )

        async def flowed() -> bool:
            beats = await heartbeats(event_bus.heartbeats)
            stats = {key.split(".", 1)[0]: beat["stats"] for key, beat in beats.items()}
            relay_stats: Any = stats.get("relay", {})
            consumer_stats: Any = stats.get("consumers", {})
            return (
                relay_stats.get("published_total", 0) >= 1
                and consumer_stats.get("processed", {}).get("system__dev_event_logger", 0) >= 1
                and "identity_access.user.logged_in" in printed.getvalue()
            )

        await wait_for(flowed, within=15)
    finally:
        stop.set()
        tail_stop.set()
        results = await asyncio.gather(*workers, tailing, return_exceptions=True)
    assert [r for r in results if isinstance(r, BaseException)] == []
    assert f'"user_id":"{user}"' in printed.getvalue()

    stats_out = io.StringIO()
    await COMMANDS["stats"](build_parser().parse_args(["stats"]), event_bus, stats_out)
    assert f"stream {event_bus.names.events_stream}: 1 messages" in stats_out.getvalue()
    # Stopped workers delete their heartbeat key at once, so /ready stops counting them.
    assert await heartbeats(event_bus.heartbeats) == {}


def test_runtime_run_returns_when_main_returns() -> None:
    seen: list[bool] = []

    async def main(stop: asyncio.Event) -> None:
        seen.append(stop.is_set())

    assert runtime.run(main) == 0
    assert seen == [False]


async def test_relay_requires_its_database_url(event_bus: bus.Bus, bus_settings: Settings) -> None:
    settings = bus_settings.model_copy(update={"relay_database_url": None})
    with pytest.raises(RuntimeError, match="SUPPORTX_RELAY_DATABASE_URL"):
        relay_main.build_relay(settings, event_bus, RelayMetrics())


async def test_cli_replays_everything_for_one_consumer(
    event_bus: bus.Bus, tenant: uuid.UUID
) -> None:

    envelope_json = json.dumps(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "identity_access.user.logged_out",
            "schema_version": 1,
            "tenant_id": str(tenant),
            "actor": {"type": "system", "id": "tests"},
            "occurred_at": "2026-10-23T00:00:00Z",
            "aggregate_type": "user",
            "aggregate_id": "u",
            "payload": {"user_id": str(uuid.uuid4()), "client": "console"},
        }
    ).encode()
    for consumer in ("a__one", "a__one", "b__two"):
        await event_bus.js.publish(
            event_bus.names.dlq_subject(consumer, tenant, "identity_access.user.logged_out"),
            envelope_json,
            stream=event_bus.names.dlq_stream,
            headers={"Supportx-Consumer": consumer, "Nats-Msg-Id": str(uuid.uuid4())},
        )
    out = io.StringIO()
    args = build_parser().parse_args(["dlq-replay", "--all", "--consumer", "a__one"])
    assert await COMMANDS["dlq-replay"](args, event_bus, out) == 0
    assert "2 replayed" in out.getvalue()
    args = build_parser().parse_args(["dlq-list"])
    await COMMANDS["dlq-list"](args, event_bus, out)
    assert "1 dead letter(s)" in out.getvalue()
    assert "consumer=b__two" in out.getvalue()
    replays = await event_bus.js.stream_info(event_bus.names.events_stream)
    assert replays.state.messages == 2
    args = build_parser().parse_args(["dlq-replay", "--seq", "999"])
    assert await COMMANDS["dlq-replay"](args, event_bus, out) == 1  # nothing with that number
