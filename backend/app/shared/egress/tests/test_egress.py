"""The guarded outbound HTTP client (ADR-043 §8; lane B's constraints). No network but loopback.

Addresses: every closed range, IPv6 forms that carry an IPv4 address, and what only the
installation may open. Calls: a single resolve whose answers are all checked (rebinding never
works), the connection pinned to the checked IP, no redirects, the size cap, refused headers,
ports, and a real round trip to a loopback server that the installation opened.
"""

import asyncio
import ipaddress
from collections.abc import AsyncIterator

import httpcore
import pytest
import structlog
from structlog.testing import capture_logs

from app.shared.egress import (
    Allowance,
    AllowanceError,
    EgressError,
    OutboundRequest,
    allowed,
    send,
)
from app.shared.egress.addresses import IPAddress
from app.shared.egress.client import PinnedBackend

PUBLIC = ipaddress.ip_address("93.184.216.34")
NOBODY = Allowance()


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "169.254.169.254",  # cloud metadata
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "100.64.0.1",  # CGNAT
        "0.1.2.3",
        "224.0.0.1",
        "255.255.255.255",
        "240.0.0.1",  # reserved
        "::1",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "::ffff:10.0.0.1",  # IPv4-mapped
        "::ffff:169.254.169.254",
        "2002:a00:1::",  # 6to4 of 10.0.0.1
        "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254
    ],
)
def test_closed_addresses_are_never_reached(address: str) -> None:
    assert allowed(ipaddress.ip_address(address), "hooks.example.com", NOBODY) is False


def test_public_addresses_are_reached() -> None:
    assert allowed(PUBLIC, "hooks.example.com", NOBODY) is True
    assert allowed(ipaddress.ip_address("2606:4700::1111"), "x.example", NOBODY) is True
    assert allowed(ipaddress.ip_address("::ffff:93.184.216.34"), "x.example", NOBODY) is True


def test_only_the_installation_opens_private_ranges_and_never_link_local() -> None:
    opened = Allowance.from_config(["10.20.0.0/16", "erp.internal", "169.254.0.0/16"], [8443])
    assert allowed(ipaddress.ip_address("10.20.5.5"), "x", opened) is True
    assert allowed(ipaddress.ip_address("10.21.5.5"), "x", opened) is False
    assert allowed(ipaddress.ip_address("192.168.9.9"), "ERP.internal.", opened) is True
    assert allowed(ipaddress.ip_address("169.254.169.254"), "x", opened) is False  # never
    assert opened.ports is not None
    assert 8443 in opened.ports
    assert {80, 443} <= opened.ports
    assert opened.any_port().ports is None  # the same networks and hosts, any port
    assert opened.any_port().networks == opened.networks


class Resolver:
    """A fake DNS that counts its lookups and answers what the test says."""

    def __init__(self, *answers: str) -> None:
        self.answers = [ipaddress.ip_address(a) for a in answers]
        self.calls = 0

    async def __call__(self, host: str, port: int) -> list[IPAddress]:
        del host, port
        self.calls += 1
        return list(self.answers)


def _http(status: int, body: bytes = b"ok", extra: bytes = b"") -> list[bytes]:
    return [
        f"HTTP/1.1 {status} X\r\n".encode()
        + extra
        + f"Content-Length: {len(body)}\r\n\r\n".encode(),
        body,
    ]


async def _send(
    url: str, resolver: Resolver, backend: httpcore.AsyncNetworkBackend, **kwargs: object
) -> object:
    request = OutboundRequest(
        "POST", url, headers={"Content-Type": "application/json"}, body=b'{"a":1}'
    )
    return await send(
        request,
        allowance=kwargs.pop("allowance", NOBODY),  # type: ignore[arg-type]  # test shorthand
        module="tests",
        tenant_id=None,
        resolver=resolver,
        backend=backend,
        **kwargs,  # type: ignore[arg-type]  # test shorthand
    )


async def test_one_private_answer_blocks_the_call_and_nothing_connects() -> None:
    backend = httpcore.AsyncMockBackend(_http(200))
    resolver = Resolver("93.184.216.34", "10.0.0.5")
    with pytest.raises(EgressError) as raised:
        await _send("http://hooks.example.com/x", resolver, backend)
    assert raised.value.code == "blocked"


async def test_the_name_is_resolved_once_and_the_connection_goes_to_the_checked_ip() -> None:
    inner = httpcore.AsyncMockBackend(_http(200, b"done"))
    resolver = Resolver("93.184.216.34")
    pinned = PinnedBackend(PUBLIC, inner)

    response = await _send("http://hooks.example.com/x", resolver, inner)
    assert response.body == b"done"  # type: ignore[attr-defined]
    assert resolver.calls == 1  # a rebinding answer later is never asked for
    await pinned.connect_tcp("evil.example", 80)
    assert pinned.connected == [("93.184.216.34", 80)]  # whatever host httpcore names


@pytest.mark.parametrize(
    ("status", "code"), [(302, "redirect"), (500, "http_status"), (404, "http_status")]
)
async def test_redirects_are_never_followed_and_errors_keep_their_status(
    status: int, code: str
) -> None:
    backend = httpcore.AsyncMockBackend(_http(status, b"", b"Location: http://10.0.0.1/\r\n"))
    with pytest.raises(EgressError) as raised:
        await _send("http://hooks.example.com/x", Resolver("93.184.216.34"), backend)
    assert (raised.value.code, raised.value.status) == (code, status)


async def test_a_response_over_the_cap_is_refused() -> None:
    backend = httpcore.AsyncMockBackend(_http(200, b"x" * 2000))
    with pytest.raises(EgressError) as raised:
        await _send("http://h.example/x", Resolver("93.184.216.34"), backend, max_bytes=1000)
    assert raised.value.code == "too_large"


@pytest.mark.parametrize(
    ("url", "headers", "code"),
    [
        ("ftp://h.example/x", {}, "invalid"),
        ("http://user:pw@h.example/x", {}, "invalid"),
        ("http://h.example:8080/x", {}, "blocked"),  # only 80 and 443 unless configured
        ("http://h.example/x", {"Host": "other.example"}, "invalid"),
        ("http://h.example/x", {"Transfer-Encoding": "chunked"}, "invalid"),
        ("http://h.example/x", {"X-Bad": "a\r\nInjected: 1"}, "invalid"),
        ("http://h.example/x", {"X-Bad": "a\x00b"}, "invalid"),  # NUL in a value
        ("http://h.example/x", {"Bad Name": "v"}, "invalid"),  # not an RFC 9110 token
        ("http://h.example/x", {"X-Ü": "v"}, "invalid"),
        ("http://:secret@h.example/x", {}, "invalid"),  # a password alone
    ],
)
async def test_refused_before_any_lookup(url: str, headers: dict[str, str], code: str) -> None:
    resolver = Resolver("93.184.216.34")
    request = OutboundRequest("POST", url, headers=headers)
    with pytest.raises(EgressError) as raised:
        await send(
            request,
            allowance=NOBODY,
            module="tests",
            tenant_id=None,
            resolver=resolver,
            backend=httpcore.AsyncMockBackend(_http(200)),
        )
    assert raised.value.code == code
    assert resolver.calls == 0


async def test_the_egress_record_never_holds_secrets_bodies_or_queries() -> None:
    backend = httpcore.AsyncMockBackend(_http(200, b"reply-body"))
    request = OutboundRequest(
        "POST",
        "https://hooks.example.com/x?token=query-secret",
        secret_headers={"Authorization": "Bearer header-secret"},
        body=b"body-secret",
    )
    structlog.reset_defaults()
    with capture_logs() as logs:
        await send(
            request,
            allowance=NOBODY,
            module="tests",
            tenant_id=None,
            resolver=Resolver("93.184.216.34"),
            backend=backend,
        )
    [entry] = [e for e in logs if e["event"] == "egress_call"]
    assert (entry["host"], entry["port"], entry["status"]) == ("hooks.example.com", 443, 200)
    text = repr(logs)
    for secret in ("query-secret", "header-secret", "body-secret", "reply-body"):
        assert secret not in text


@pytest.fixture
async def receiver() -> AsyncIterator[tuple[int, list[bytes]]]:
    """A real HTTP/1.1 server on loopback that records what it was sent."""
    seen: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        length = next(
            (
                int(line.split(b":")[1])
                for line in head.split(b"\r\n")
                if line.lower().startswith(b"content-length")
            ),
            0,
        )
        seen.append(head + await reader.readexactly(length))
        writer.write(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield port, seen


async def test_a_real_call_to_a_receiver_the_installation_opened(
    receiver: tuple[int, list[bytes]],
) -> None:
    port, seen = receiver
    closed = OutboundRequest("POST", f"http://127.0.0.1:{port}/hook", body=b"exact bytes")
    with pytest.raises(EgressError) as raised:
        await send(closed, allowance=Allowance(ports=frozenset({port})), module="t", tenant_id=None)
    assert raised.value.code == "blocked"  # loopback stays closed until configured
    opened = Allowance.from_config(["127.0.0.1/32"], [port], allow_loopback=True)
    response = await send(closed, allowance=opened, module="t", tenant_id=None)
    assert response.status == 204
    assert seen[0].endswith(b"\r\n\r\nexact bytes")  # the body byte for byte


def _certificate(name: str) -> tuple[str, str]:
    """A self-signed certificate for `name` and its key, as PEM."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415 - this helper only

    from cryptography import x509  # noqa: PLC0415
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
    from cryptography.x509.oid import NameOID  # noqa: PLC0415

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM).decode(),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )


async def test_tls_verifies_the_host_name_while_the_connection_is_pinned(tmp_path: object) -> None:
    import ssl  # noqa: PLC0415 - this test only
    from pathlib import Path  # noqa: PLC0415

    from app.shared.egress import Destination  # noqa: PLC0415

    cert, key = _certificate("hooks.test")
    folder = Path(str(tmp_path))
    (folder / "c.pem").write_text(cert + key)
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(folder / "c.pem")

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_tls)
    port = server.sockets[0].getsockname()[1]
    opened = Allowance.from_config(["127.0.0.1/32"], [port], allow_loopback=True)
    async with server:
        trusted = Destination(ca_pem=cert)
        good = OutboundRequest("GET", f"https://hooks.test:{port}/")
        response = await send(
            good,
            allowance=opened,
            module="t",
            tenant_id=None,
            destination=trusted,
            resolver=Resolver("127.0.0.1"),
        )
        assert response.body == b"ok"  # SNI and the check use the name; the IP was pinned
        with pytest.raises(EgressError) as untrusted:  # the system store does not know it
            await send(
                good, allowance=opened, module="t", tenant_id=None, resolver=Resolver("127.0.0.1")
            )
        assert untrusted.value.code == "tls"
        other = OutboundRequest("GET", f"https://other.test:{port}/")
        with pytest.raises(EgressError) as wrong_name:  # a certificate for another name
            await send(
                other,
                allowance=opened,
                module="t",
                tenant_id=None,
                destination=trusted,
                resolver=Resolver("127.0.0.1"),
            )
        assert wrong_name.value.code == "tls"


@pytest.mark.parametrize("method", ["CONNECT", "TRACE", "get", "PROPFIND"])
async def test_only_the_usual_methods_are_sent(method: str) -> None:
    resolver = Resolver("93.184.216.34")
    with pytest.raises(EgressError) as raised:
        await send(
            OutboundRequest(method, "https://h.example/x"),
            allowance=NOBODY,
            module="t",
            tenant_id=None,
            resolver=resolver,
            backend=httpcore.AsyncMockBackend(_http(200)),
        )
    assert raised.value.code == "invalid"
    assert resolver.calls == 0


async def test_secret_headers_never_travel_over_plain_http_unless_the_host_is_listed() -> None:
    secret = {"Authorization": "Bearer k"}
    with pytest.raises(EgressError) as raised:
        await send(
            OutboundRequest("POST", "http://h.example/x", secret_headers=secret),
            allowance=NOBODY,
            module="t",
            tenant_id=None,
            resolver=Resolver("93.184.216.34"),
            backend=httpcore.AsyncMockBackend(_http(200)),
        )
    assert raised.value.code == "insecure"
    listed = Allowance.from_config(["h.example"])
    done = await send(
        OutboundRequest("POST", "http://h.example/x", secret_headers=secret),
        allowance=listed,
        module="t",
        tenant_id=None,
        resolver=Resolver("93.184.216.34"),
        backend=httpcore.AsyncMockBackend(_http(200)),
    )
    assert done.status == 200


@pytest.mark.parametrize("entry", ["0.0.0.0/0", "10.0.0.0/7", "::/0", "fc00::/8"])
def test_an_allow_list_entry_that_opens_too_much_is_refused(entry: str) -> None:
    with pytest.raises(AllowanceError):
        Allowance.from_config([entry])


def test_loopback_is_listed_only_in_dev_and_test() -> None:
    with pytest.raises(AllowanceError):
        Allowance.from_config(["127.0.0.1/32"])
    assert Allowance.from_config(["127.0.0.1/32"], allow_loopback=True).networks


def test_the_settings_refuse_a_wide_entry_and_production_loopback_at_load() -> None:
    from pydantic import ValidationError  # noqa: PLC0415 - this test only

    from app.core.config import Settings  # noqa: PLC0415

    def make_settings(**overrides: object) -> Settings:  # never `from conftest import` (#272)
        return Settings(_env_file=None, tracing_enabled=False, **{"profile": "test", **overrides})  # type: ignore[call-arg, arg-type]  # pydantic-settings' init keyword, validated values

    with pytest.raises(ValidationError, match="wider than"):
        make_settings(egress_allow=["0.0.0.0/0"])
    with pytest.raises(ValidationError, match="opens loopback"):
        make_settings(
            profile="production",
            mobile_redirect_uri="https://sx.example.com/mobile/auth",
            egress_allow=["127.0.0.0/8"],
        )
    assert make_settings(egress_allow=["10.20.0.0/16", "erp.internal"]).egress_allow
