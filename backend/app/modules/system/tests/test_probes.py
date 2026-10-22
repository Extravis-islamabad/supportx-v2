"""Probe behaviour against real sockets on localhost, without the dev stack.

A closed port proves "unreachable"; a server that accepts but never answers proves the timeout is
honoured. Successful probing against the real services is covered by
tests/integration/test_ready_dev_stack.py.
"""

import asyncio
import socket
from collections.abc import AsyncIterator, Callable

import pytest

from app.core.config import Settings
from app.modules.system import build_readiness_service
from app.modules.system.domain.readiness import (
    CheckStatus,
    DependencyProbe,
    FailureReason,
    ProbeFailedError,
)
from app.modules.system.infra.probes import NatsProbe, PostgresProbe, ValkeyProbe
from app.modules.system.service.readiness import ReadinessService


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


@pytest.fixture
async def silent_port() -> AsyncIterator[int]:
    """A server that accepts connections and never sends a byte."""
    held: list[asyncio.StreamWriter] = []

    async def accept(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        held.append(writer)

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    port: int = server.sockets[0].getsockname()[1]
    yield port
    for writer in held:
        writer.close()
    server.close()
    await server.wait_closed()


def probes_for(port: int) -> list[DependencyProbe]:
    return [
        PostgresProbe(f"postgresql://app:pw@127.0.0.1:{port}/supportx"),
        ValkeyProbe(f"valkey://:pw@127.0.0.1:{port}/0"),
        NatsProbe(f"nats://127.0.0.1:{port}"),
    ]


async def test_closed_port_is_unreachable() -> None:
    report = await ReadinessService(probes_for(closed_port()), timeout=1.0).check()
    for name in ("postgres", "valkey", "nats"):
        assert report.checks[name].status is CheckStatus.FAILED, name
        assert report.checks[name].reason is FailureReason.UNREACHABLE, name


async def test_silent_server_times_out(silent_port: int) -> None:
    report = await ReadinessService(probes_for(silent_port), timeout=0.3).check()
    for name in ("postgres", "valkey", "nats"):
        assert report.checks[name].status is CheckStatus.FAILED, name
        assert report.checks[name].reason in {FailureReason.TIMEOUT, FailureReason.UNREACHABLE}


async def test_probe_failure_carries_reason() -> None:
    with pytest.raises(ProbeFailedError) as raised:
        await ValkeyProbe(f"valkey://127.0.0.1:{closed_port()}/0").check(0.5)
    assert raised.value.reason is FailureReason.UNREACHABLE


def test_service_probes_only_configured_dependencies(
    settings_factory: Callable[..., Settings],
) -> None:
    service = build_readiness_service(
        settings_factory(nats_url="nats://127.0.0.1:4222", readiness_timeout_seconds=0.7)
    )
    assert [p.name for p in service._probes] == ["nats"]  # noqa: SLF001 - wiring under test
    assert service._not_configured == ("postgres", "valkey")  # noqa: SLF001
    assert service._timeout == 0.7  # noqa: SLF001
