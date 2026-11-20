"""Streaming audit and sign-in entries to a SIEM (REQ-AUD-011, WP-057 S5a), on real PostgreSQL.

A real TLS syslog receiver (a throwaway CA and certificate, made here) and a real HTTPS-free
webhook check through the service's own path:

- AC1: an audit entry sealed now reaches the receiver at the next delivery tick.
- AC2: the receiver down, entries wait (the cursor holds, the error is a code, a backoff is set);
  back up, they arrive in order, none lost, none twice.
- Nothing personal leaves: an entry whose `audit_personal` is full sends none of it.
- A lapsed licence pauses delivery and keeps the cursor (the coordinator's condition 4).
- The API: audit.manage only (404 otherwise), the webhook secret shown once (not in a replay),
  never read back; RLS keeps one tenant's destinations from another (lane A (5)).
"""

import asyncio
import datetime as dt
import ipaddress
import json
import ssl
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from app.modules.audit.domain import siem as domain
from app.modules.audit.domain.catalogue import AuditClient
from app.modules.audit.infra.models import SiemDestination
from app.modules.audit.service import siem
from app.modules.audit.service.integrity import seal
from app.modules.audit.service.recording import RequestFacts, record
from app.shared.files.keyring import KeyRing
from conftest import make_settings
from tests.db.test_access_api import fake_session
from tests.db.test_incidents_api import World, make_org
from tests.db.test_rate_limit import valkey_url
from tooling.db_testing import ThrowawayDatabase

if TYPE_CHECKING:
    from app.core.database import Database

pytestmark = pytest.mark.db

BASE = "/audit/siem/destinations"


# --- a TLS syslog receiver -----------------------------------------------------------------------


def _tls_material() -> tuple[str, Path, Path]:
    """A CA (its PEM) and a localhost certificate signed by it (files for the server)."""
    now = dt.datetime.now(dt.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "QA-2026-11-20 SIEM CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    folder = Path(tempfile.mkdtemp(prefix="siem-test-"))
    cert_file, key_file = folder / "cert.pem", folder / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca.public_bytes(serialization.Encoding.PEM).decode(), cert_file, key_file


class Receiver:
    """A TLS syslog receiver reading RFC 6587 octet-counted frames."""

    def __init__(self, cert: Path, key: Path) -> None:
        self.context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self.context.load_cert_chain(cert, key)
        self.messages: list[str] = []
        self.server: asyncio.Server | None = None
        self.port = 0

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                length = b""
                while not length.endswith(b" "):
                    char = await reader.read(1)
                    if not char:
                        return
                    length += char
                data = await reader.readexactly(int(length))
                self.messages.append(data.decode())
        except (asyncio.IncompleteReadError, ConnectionError):
            return
        finally:
            writer.close()

    async def start(self, port: int = 0) -> None:
        self.server = await asyncio.start_server(self._client, "127.0.0.1", port, ssl=self.context)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        assert self.server is not None
        self.server.close()
        await self.server.wait_closed()


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    url = valkey_url()
    if url is None:
        pytest.skip("Valkey is not configured")
    app = create_app(
        make_settings(
            database_url=migrated_db.app_url,
            valkey_url=url,
            files_keys=SecretStr(KeyRing.generate()),
            # The receivers run on this machine: loopback, which only the test profile may open.
            egress_allow=["127.0.0.1/32", "::1/128"],
            centrifugo_token_secret="siem-test-secret-" + "x" * 16,
        )
    )
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            w = World(client, migrated_db, app, a=None, b=None)  # type: ignore[arg-type]  # set below
            w.a = await make_org(w, "QA-2026-11-20 Alpha")
            w.b = await make_org(w, "QA-2026-11-20 Beta")
            yield w


async def _seal(world: World, tenant: uuid.UUID) -> None:
    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        await seal(session, 500)


async def _write(world: World, tenant: uuid.UUID, user: uuid.UUID, n: int) -> list[str]:
    """`n` audit entries with personal values (an address, a device, a reason), then sealed."""
    ids: list[str] = []
    for i in range(n):
        async with world.app.state.db.tenant_session(TenantContext(tenant, user)) as session:
            entry = await record(
                session,
                action_code="audit.settings_changed",
                facts=RequestFacts(
                    AuditClient.CONSOLE, None, "203.0.113.77", "QA-Device/9.9 secret-ua"
                ),
                object_type="audit_settings",
                object_id=f"qa-{i}",
                reason="QA-2026-11-20 a personal reason",
            )
            ids.append(str(entry))
    await _seal(world, tenant)
    return ids


async def _destination(world: World, tenant: uuid.UUID, port: int, ca_pem: str) -> uuid.UUID:
    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        made = await siem.add_destination(
            session,
            _Admin(tenant),
            world.app.state.settings,
            siem.DestinationInput(
                name="QA-2026-11-20 receiver",
                kind=domain.SiemKind.SYSLOG,
                format=domain.SiemFormat.JSON,
                host="localhost",
                port=port,
                streams=(domain.SiemStream.AUDIT,),
                ca_pem=ca_pem,
            ),
        )
        return made.row.id


class _Admin:
    def __init__(self, tenant: uuid.UUID) -> None:
        self.tenant_id = tenant
        self.user_id = uuid.uuid4()


async def _row(world: World, tenant: uuid.UUID, destination: uuid.UUID) -> SiemDestination:
    database: Database = world.app.state.db
    async with database.tenant_session(TenantContext(tenant)) as session:
        row = await session.get(SiemDestination, destination)
        assert row is not None
        session.expunge(row)
        return row


async def test_entries_arrive_in_order_and_survive_an_outage(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    ca, cert, key = _tls_material()
    receiver = Receiver(cert, key)
    await receiver.start()
    monkeypatch.setattr(siem, "SYSLOG_PORTS", frozenset({receiver.port}))
    a = world.a
    destination = await _destination(world, a.tenant, receiver.port, ca)
    db, settings = world.app.state.db, world.app.state.settings
    # AC1: written and sealed now, sent at the next tick.
    first = await _write(world, a.tenant, a.admin, 3)
    await siem.deliver_tenant(db, settings, a.tenant)
    await asyncio.sleep(0.2)
    sent = [json.loads(m.split(" - audit - ", 1)[1]) for m in receiver.messages]
    assert [m["id"] for m in sent if m["id"] in first] == first
    seqs = [m["seq"] for m in sent]
    assert seqs == sorted(seqs)
    # Nothing personal left (lane A (6)): the address, the device, the reason.
    dump = "\n".join(receiver.messages)
    for personal in ("203.0.113.77", "secret-ua", "a personal reason", "personal_commitments"):
        assert personal not in dump, personal
    # AC2: the receiver goes down; entries wait, the cursor holds, the error is a code.
    held = (await _row(world, a.tenant, destination)).audit_seq_sent
    port = receiver.port
    await receiver.stop()
    second = await _write(world, a.tenant, a.admin, 4)
    await siem.deliver_tenant(db, settings, a.tenant)
    down = await _row(world, a.tenant, destination)
    assert down.audit_seq_sent == held
    assert down.last_error_code is not None
    assert down.next_attempt_at is not None
    # Back up on the same port: everything after the cursor arrives, in order, once.
    receiver.messages.clear()
    await receiver.start(port)
    async with db.tenant_session(TenantContext(a.tenant)) as session:
        row = await session.get(SiemDestination, destination)
        assert row is not None
        row.next_attempt_at = None  # the backoff's wait, skipped by the test
    await siem.deliver_tenant(db, settings, a.tenant)
    await asyncio.sleep(0.2)
    resent = [json.loads(m.split(" - audit - ", 1)[1])["id"] for m in receiver.messages]
    assert [i for i in resent if i in second] == second
    assert len(resent) == len(set(resent))  # none twice
    assert not set(resent) & set(first)  # nothing already acknowledged again
    healthy = await _row(world, a.tenant, destination)
    assert healthy.last_success_at is not None
    assert healthy.failing_since is None
    await receiver.stop()


async def test_a_lapsed_licence_pauses_and_keeps_the_cursor(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    ca, cert, key = _tls_material()
    receiver = Receiver(cert, key)
    await receiver.start()
    monkeypatch.setattr(siem, "SYSLOG_PORTS", frozenset({receiver.port}))
    a = world.a
    destination = await _destination(world, a.tenant, receiver.port, ca)
    await _write(world, a.tenant, a.admin, 2)

    async def lapsed(_tenant: uuid.UUID, _feature: object) -> bool:
        return False

    monkeypatch.setattr(siem, "has_feature", lapsed)
    held = (await _row(world, a.tenant, destination)).audit_seq_sent
    await siem.deliver_tenant(world.app.state.db, world.app.state.settings, a.tenant)
    assert receiver.messages == []
    assert (await _row(world, a.tenant, destination)).audit_seq_sent == held
    await receiver.stop()


async def test_the_api_is_admins_only_and_never_shows_a_secret_twice(world: World) -> None:
    a, b = world.a, world.b
    body: dict[str, Any] = {
        "name": "QA-2026-11-20 hook",
        "kind": "webhook",
        "url": "https://siem.example.test/ingest",
        "streams": ["audit", "sign_ins"],
    }
    key = {"Idempotency-Key": str(uuid.uuid4())}
    made = await world.call("POST", BASE, a, a.admin, json=body, headers=key)
    assert made.status_code == 201, made.text
    secret = made.json()["secret"]
    assert secret
    assert made.headers["cache-control"] == "no-store"
    again = await world.call("POST", BASE, a, a.admin, json=body, headers=key)
    assert again.status_code == 201, again.text
    assert again.json()["secret"] is None  # a replay never carries it
    listed = await world.call("GET", BASE, a, a.admin)
    assert listed.status_code == 200, listed.text
    assert secret not in listed.text
    assert listed.json()[0]["has_secret"] is True
    # Not audit.manage: the feature does not exist for them (404, lane A (4)).
    assert (await world.call("GET", BASE, a, a.tech_a)).status_code == 404
    # RLS (lane A (5)): the other tenant sees none of it.
    other = await world.call("GET", BASE, b, b.admin)
    assert other.status_code == 200, other.text
    assert other.json() == []
    # A plain-HTTP webhook and a non-TLS syslog port are refused.
    plain = await world.call(
        "POST", BASE, a, a.admin, json={**body, "name": "x", "url": "http://siem.example.test"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )  # fmt: skip
    assert plain.status_code == 422, plain.text
    udp = await world.call(
        "POST", BASE, a, a.admin,
        json={"name": "y", "kind": "syslog", "host": "siem.example.test", "port": 514},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )  # fmt: skip
    assert udp.status_code == 422, udp.text
