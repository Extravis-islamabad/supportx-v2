"""The TXT lookup against a local fake DNS server (D-183): never the internet or a public resolver.

The server answers on 127.0.0.1 (UDP and TCP, a random port) from a table of names; the lookup is
pointed at it exactly as at an installation's own resolver. Lane B blocks this (egress, identity).
"""

import asyncio
import contextlib
import struct
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path

import dns.asyncresolver
import dns.flags
import dns.message
import dns.rcode
import dns.rdata
import dns.rdataclass
import dns.rdatatype
import dns.resolver
import dns.rrset
import pytest

from app.modules.identity_access.domain.verified_domains import (
    DnsCheckUnavailable,
    DnsUnreachable,
)
from app.modules.identity_access.infra import dns_txt


@dataclass
class Zone:
    """TXT records by name (each record a tuple of strings); `refuse` and `silent` misbehave."""

    records: dict[str, list[tuple[bytes, ...]]] = field(default_factory=dict)
    refuse: bool = False
    silent: bool = False
    asked: list[str] = field(default_factory=list)

    def answer(self, wire: bytes) -> bytes | None:
        query = dns.message.from_wire(wire)
        question = query.question[0]
        name = question.name.to_text()
        self.asked.append(name)
        if self.silent:
            return None
        response = dns.message.make_response(query)
        if self.refuse:
            response.set_rcode(dns.rcode.REFUSED)
            return response.to_wire()
        if name not in self.records:
            response.set_rcode(dns.rcode.NXDOMAIN)
            return response.to_wire()
        rrset = dns.rrset.RRset(question.name, dns.rdataclass.IN, dns.rdatatype.TXT)
        for strings in self.records[name]:
            text = " ".join('"' + s.decode() + '"' for s in strings)
            rrset.add(dns.rdata.from_text(dns.rdataclass.IN, dns.rdatatype.TXT, text), ttl=60)
        if rrset:
            response.answer.append(rrset)
        return response.to_wire()


class _Udp(asyncio.DatagramProtocol):
    def __init__(self, zone: Zone) -> None:
        self.zone = zone
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]  # a datagram endpoint's transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        reply = self.zone.answer(data)
        if reply is not None and self.transport is not None:
            if len(reply) > 512:  # as a real server: too big for UDP, so the client retries on TCP
                query = dns.message.from_wire(data)
                truncated = dns.message.make_response(query)
                truncated.flags |= dns.flags.TC
                reply = truncated.to_wire()
            self.transport.sendto(reply, addr)


@contextlib.asynccontextmanager
async def fake_dns(zone: Zone) -> AsyncIterator[int]:
    """A DNS server on 127.0.0.1 (UDP and TCP on one port); yields the port."""
    loop = asyncio.get_running_loop()

    async def on_tcp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(asyncio.IncompleteReadError, ConnectionError):
            (length,) = struct.unpack("!H", await reader.readexactly(2))
            reply = zone.answer(await reader.readexactly(length))
            if reply is not None:
                writer.write(struct.pack("!H", len(reply)) + reply)
                await writer.drain()
        writer.close()

    tcp = await asyncio.start_server(on_tcp, "127.0.0.1", 0)
    port = tcp.sockets[0].getsockname()[1]
    udp, _ = await loop.create_datagram_endpoint(lambda: _Udp(zone), local_addr=("127.0.0.1", port))
    try:
        yield port
    finally:
        udp.close()
        tcp.close()
        await tcp.wait_closed()


def _pointed_at(port: int) -> Callable[[], dns.asyncresolver.Resolver]:
    """A resolver like the installation's (no resolv.conf read here), on the fake server."""

    def make() -> dns.asyncresolver.Resolver:
        resolver = dns.asyncresolver.Resolver(configure=False)
        resolver.nameservers = ["127.0.0.1"]
        resolver.port = port
        resolver.timeout = dns_txt.QUERY_TIMEOUT_SECONDS
        resolver.lifetime = dns_txt.LIFETIME_SECONDS
        return resolver

    return make


NAME = "_supportx.example.test."


async def test_a_record_is_read_with_its_split_strings_joined() -> None:
    zone = Zone({NAME: [(b"supportx-verify=", b"abc123"), (b"v=spf1 -all",)]})
    async with fake_dns(zone) as port:
        found = await dns_txt.lookup_with(_pointed_at(port))(NAME)
    assert sorted(found) == ["supportx-verify=abc123", "v=spf1 -all"]  # DNS keeps no order
    assert zone.asked == [NAME]  # one question, to the configured server only


async def test_a_name_that_does_not_exist_or_has_no_txt_is_an_empty_answer() -> None:
    zone = Zone({"_supportx.empty.test.": []})
    async with fake_dns(zone) as port:
        lookup = dns_txt.lookup_with(_pointed_at(port))
        assert await lookup(NAME) == []  # NXDOMAIN
        assert await lookup("_supportx.empty.test.") == []  # the name, no TXT


async def test_an_oversized_record_is_skipped_never_cut_into_a_match() -> None:
    long = (b"supportx-verify=abc123" + b"x" * 230,) + (b"x" * 250,) * 4  # 1252 bytes, 255 a string
    zone = Zone({NAME: [long, (b"short-one",), (b"short-two",)]})
    async with fake_dns(zone) as port:  # too big for UDP: the client goes on to TCP
        found = await dns_txt.lookup_with(_pointed_at(port))(NAME)
    assert sorted(found) == ["short-one", "short-two"]


async def test_at_most_twenty_answers_are_read() -> None:
    zone = Zone({NAME: [(f"r{n:02d}".encode(),) for n in range(30)]})
    async with fake_dns(zone) as port:
        found = await dns_txt.lookup_with(_pointed_at(port))(NAME)
    assert len(found) == dns_txt.ANSWERS_MAX


async def test_a_refusal_is_unreachable_never_not_found() -> None:
    async with fake_dns(Zone(refuse=True)) as port:
        with pytest.raises(DnsUnreachable) as refused:
            await dns_txt.lookup_with(_pointed_at(port))(NAME)
    assert not isinstance(refused.value, DnsCheckUnavailable)


async def test_a_server_that_never_answers_is_unreachable_within_the_bound() -> None:
    zone = Zone(silent=True)
    async with fake_dns(zone) as port:
        started = time.monotonic()
        with pytest.raises(DnsUnreachable):
            await dns_txt.lookup_with(_pointed_at(port))(NAME)
    took = time.monotonic() - started
    assert took < dns_txt.LIFETIME_SECONDS + 1.0, took  # bounded: never a hang
    assert zone.asked  # it did ask the configured server


def test_no_resolver_configured_is_unavailable_never_a_network_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An air-gapped host with no resolv.conf: unavailable (never counts towards a lapse)."""

    def no_configuration(*_args: object, **_kwargs: object) -> None:
        raise dns.resolver.NoResolverConfiguration

    monkeypatch.setattr(dns.asyncresolver, "Resolver", no_configuration)
    with pytest.raises(DnsCheckUnavailable):
        dns_txt.system_resolver()


def test_the_system_resolver_is_bounded_and_names_no_public_server() -> None:
    """The installation's own resolv.conf, with this module's timeouts; nothing hard-coded."""
    source = Path(dns_txt.__file__).read_text(encoding="utf-8")
    for public in ("8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9", "208.67.222.222"):
        assert public not in source
    try:
        resolver = dns_txt.system_resolver()
    except DnsCheckUnavailable:
        pytest.skip("this host has no resolver configured")
    assert resolver.timeout == dns_txt.QUERY_TIMEOUT_SECONDS
    assert resolver.lifetime == dns_txt.LIFETIME_SECONDS
