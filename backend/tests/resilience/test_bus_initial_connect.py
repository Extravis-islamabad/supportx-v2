"""A worker's first NATS connect is bounded: it logs, backs off, retries and gives up, never hangs.

nats-py's first `connect` neither raises nor returns while no server answers: it keeps
reconnecting inside the call. `connect_until_ready` then never logged, backed off or gave up, and
a worker hung silently (the fan-out after a node loss, #566's Cluster run 45217683176). Each
first connect now gives up after `bus.initial_connect_seconds`, so the outage is visible:
readiness says not connected, attempts are counted, and `worker_give_up_seconds` ends the
process.

Own throwaway NATS container on a random port (never the dev stack's), and a port nobody
listens on. Runs with SUPPORTX_RESILIENCE_TESTS=1 (CI job "worker resilience"); needs Docker.
"""

import asyncio
import os
import secrets
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from conftest import make_settings
from workers import bus
from workers.resilience import Connectivity, WorkerUnrecoverable

pytestmark = pytest.mark.resilience

NATS_IMAGE = "nats:2.15.1-alpine"
GIVE_UP = 8.0

if os.environ.get("SUPPORTX_RESILIENCE_TESTS") != "1" or shutil.which("docker") is None:
    pytest.skip("set SUPPORTX_RESILIENCE_TESTS=1 (needs Docker)", allow_module_level=True)


def _docker(*args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed docker arguments
        ["docker", *args],  # noqa: S607 - docker from PATH, as the developer runs it
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _logs(name: str) -> str:
    """The container's log, stdout and stderr together (NATS logs to stderr)."""
    return subprocess.run(  # noqa: S603 - fixed docker arguments
        ["docker", "logs", name],  # noqa: S607 - docker from PATH
        capture_output=True,
        text=True,
        check=False,
    ).stderr


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _settings(port: int) -> Settings:
    return make_settings(
        nats_url=SecretStr(f"nats://127.0.0.1:{port}"),
        readiness_timeout_seconds=1.0,
        worker_give_up_seconds=GIVE_UP,
        events_namespace=f"busconnect{secrets.token_hex(3)}",
    )


def _others() -> set[asyncio.Task[object]]:
    """The tasks still running besides the test's own."""
    return {t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()}


@pytest.fixture
def paused_nats() -> Iterator[tuple[str, int]]:
    """A NATS JetStream container, paused: it accepts TCP but never says hello."""
    name = f"supportx-test-busconnect-{secrets.token_hex(4)}"
    port = _free_port()
    _docker("run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:4222", NATS_IMAGE, "-js")
    try:
        deadline = time.monotonic() + 30
        while "Server is ready" not in _logs(name):
            if time.monotonic() > deadline:
                pytest.fail("NATS did not start within 30 s")
            time.sleep(0.5)
        _docker("pause", name)
        yield name, port
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)  # noqa: S603, S607


async def test_with_no_server_each_attempt_is_bounded_and_the_worker_gives_up() -> None:
    """No listener at all: attempts are counted, readiness is down, and it gives up in time."""
    settings = _settings(_free_port())
    connectivity = Connectivity(give_up_after=GIVE_UP)
    bound = bus.initial_connect_seconds(1)
    started = time.monotonic()
    with pytest.raises(WorkerUnrecoverable, match="bus unavailable"):
        await bus.connect_until_ready(settings, "test", connectivity, asyncio.Event())
    took = time.monotonic() - started
    # It gives up after GIVE_UP, at most one attempt and one backoff later: never a hang.
    assert GIVE_UP < took < GIVE_UP + bound + 16, took
    assert connectivity.snapshot()["connected"] is False
    assert connectivity.snapshot()["unavailable"] == ["bus"]
    await asyncio.sleep(0.2)
    assert _others() == set(), _others()  # no reconnect task left behind


async def test_a_paused_server_times_out_each_attempt_then_connects_when_it_answers(
    paused_nats: tuple[str, int],
) -> None:
    """A server that accepts TCP but never answers: bounded tries, then connected once it wakes."""
    name, port = paused_nats
    settings = _settings(port)
    connectivity = Connectivity(give_up_after=120)
    bound = bus.initial_connect_seconds(1)

    async def wake_later() -> None:
        await asyncio.sleep(bound * 2 + 1)  # at least two bounded attempts first
        await asyncio.to_thread(_docker, "unpause", name)

    waker = asyncio.create_task(wake_later())
    started = time.monotonic()
    states: list[object] = []

    async def watch() -> None:
        while True:
            states.append(connectivity.snapshot()["connected"])
            await asyncio.sleep(0.5)

    watcher = asyncio.create_task(watch())
    try:
        connected = await asyncio.wait_for(
            bus.connect_until_ready(settings, "test", connectivity, asyncio.Event()), 90
        )
    finally:
        watcher.cancel()
        await waker
    assert connected is not None
    try:
        assert connected.client.is_connected
        assert connectivity.connected
        assert False in states, "readiness never said not connected while it waited"
        assert time.monotonic() - started < bound * 2 + 1 + bound + 20
    finally:
        await connected.client.close()
    await asyncio.sleep(0.2)
    assert _others() == set(), _others()
