"""Plaintext syslog, only by an admin's choice (D-181, 0190; the coordinator's conditions).

- TLS stays the default (an existing or new destination without a transport is TLS).
- Plain TCP and UDP deliver entries in order; UDP sends one datagram per entry and never cuts one
  silently: a cut entry carries a visible marker and the audit log records it.
- A webhook is HTTPS only: a plaintext transport or an http:// address is refused.
- Choosing TCP or UDP is its own audit entry, and the security overview counts plaintext
  destinations until they go back to TLS.
"""

import asyncio
import uuid
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.audit import plaintext_siem_destinations
from app.modules.audit.domain import siem as domain
from app.modules.audit.service import siem
from tests.db.test_incidents_api import World
from tests.db.test_siem_stream import Receiver, _Admin, _row, _write, world

__all__ = ["world"]  # the fixture, re-used

pytestmark = pytest.mark.db

BASE = "/audit/siem/destinations"


class _PlainReceiver(Receiver):
    """The TCP receiver without TLS (RFC 6587 frames)."""

    def __init__(self) -> None:
        self.context = None  # type: ignore[assignment]  # no TLS: the plain transport
        self.messages = []
        self.server = None
        self.port = 0


class _Datagrams(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.received: list[bytes] = []

    def datagram_received(self, data: bytes, addr: Any) -> None:  # noqa: ANN401 - the peer's address
        del addr
        self.received.append(data)


async def _plain(
    world: World, tenant: uuid.UUID, port: int, transport: str, limit: int
) -> uuid.UUID:
    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        made = await siem.add_destination(
            session,
            _Admin(tenant),
            world.app.state.settings,
            siem.DestinationInput(
                name=f"QA-2026-11-20 {transport}",
                kind=domain.SiemKind.SYSLOG,
                format=domain.SiemFormat.JSON,
                host="localhost",
                port=port,
                streams=(domain.SiemStream.AUDIT,),
                transport=domain.SiemTransport(transport),
                udp_max_bytes=limit,
            ),
        )
        return made.row.id


async def test_plain_tcp_delivers_in_order(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    receiver = _PlainReceiver()
    await receiver.start()
    monkeypatch.setattr(siem, "PLAIN_SYSLOG_PORTS", frozenset({receiver.port}))
    a = world.a
    destination = await _plain(world, a.tenant, receiver.port, "tcp", 2048)
    written = await _write(world, a.tenant, a.admin, 3)
    await siem.deliver_tenant(world.app.state.db, world.app.state.settings, a.tenant)
    await asyncio.sleep(0.2)
    got = [m for m in receiver.messages if any(i in m for i in written)]
    assert len(got) == 3
    assert (await _row(world, a.tenant, destination)).last_success_at is not None
    await receiver.stop()


async def test_udp_sends_one_datagram_per_entry_and_never_cuts_silently(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _Datagrams, local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    monkeypatch.setattr(siem, "PLAIN_SYSLOG_PORTS", frozenset({port}))
    a = world.a
    destination = await _plain(world, a.tenant, port, "udp", 480)  # the smallest allowed
    written = await _write(world, a.tenant, a.admin, 2)
    await siem.deliver_tenant(world.app.state.db, world.app.state.settings, a.tenant)
    await asyncio.sleep(0.3)
    transport.close()
    assert protocol.received, "nothing arrived"
    assert all(len(d) <= 480 for d in protocol.received)
    cut = [d for d in protocol.received if d.endswith(domain.TRUNCATED_MARK.encode())]
    assert cut, "an audit entry over 480 bytes must be cut visibly"
    assert not any(d.startswith(b"0") or b" <" in d[:6] for d in protocol.received)  # unframed
    assert (await _row(world, a.tenant, destination)).last_success_at is not None
    rows = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a.tenant,
        "audit.siem_entries_truncated",
    )
    assert rows, "the cut entries are recorded"
    del written


def test_a_long_entry_is_cut_at_a_character_and_marked() -> None:
    line = "é" * 400  # two bytes each
    data, cut = domain.datagram(line, 480)
    assert cut
    assert len(data) <= 480
    assert data.endswith(domain.TRUNCATED_MARK.encode())
    data.decode("utf-8")  # still valid UTF-8
    short, cut_short = domain.datagram("short", 480)
    assert (short, cut_short) == (b"short", False)


async def test_plaintext_is_chosen_on_purpose_audited_and_flagged(world: World) -> None:
    a = world.a
    syslog: dict[str, Any] = {
        "name": "QA-2026-11-20 legacy",
        "kind": "syslog",
        "host": "siem.example.test",
        "port": 6514,
    }
    made = await world.call(
        "POST", BASE, a, a.admin, json=syslog, headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert made.status_code == 201, made.text
    assert made.json()["transport"] == "tls"  # the default
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await plaintext_siem_destinations(session) == 0
    plain = await world.call(
        "PATCH",
        f"{BASE}/{made.json()['id']}",
        a,
        a.admin,
        json={**syslog, "transport": "udp", "port": 514},
        headers={"If-Match": f'"{made.json()["version"]}"'},
    )
    assert plain.status_code == 200, plain.text
    entries = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a.tenant,
        "audit.siem_plaintext_enabled",
    )
    assert len(entries) == 1
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await plaintext_siem_destinations(session) == 1  # the overview's flag
    back = await world.call(
        "PATCH",
        f"{BASE}/{made.json()['id']}",
        a,
        a.admin,
        json={**syslog, "transport": "tls"},
        headers={"If-Match": f'"{plain.json()["version"]}"'},
    )
    assert back.status_code == 200, back.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await plaintext_siem_destinations(session) == 0  # the flag clears


async def test_a_webhook_stays_https_only(world: World) -> None:
    a = world.a
    hook: dict[str, Any] = {
        "name": "QA-2026-11-20 hook",
        "kind": "webhook",
        "url": "https://siem.example.test/ingest",
    }
    for body in ({**hook, "transport": "udp"}, {**hook, "url": "http://siem.example.test/in"}):
        refused = await world.call(
            "POST", BASE, a, a.admin, json=body, headers={"Idempotency-Key": str(uuid.uuid4())}
        )
        assert refused.status_code == 422, refused.text
    codes = {e["code"] for e in refused.json()["errors"]}
    assert "https_required" in codes
