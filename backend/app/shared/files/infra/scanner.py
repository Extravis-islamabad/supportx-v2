"""Malware scanning (D-082 D3, ADR-028 item 3): clamd over TCP, or no scanner at all.

`ClamdScanner` speaks clamd's INSTREAM protocol (length-prefixed chunks, then a zero length) and
asks VERSION for the signature date. `NoScanner` says scanning is not available, so files wait
(or show "not scanned" when the installation does not require scanning) and administrators are
warned. `FakeScanner` (tests) treats the EICAR test string as malware, like real ClamAV does.
"""

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

_INSTREAM_PIECE = 64 << 10
# The EICAR test file, the industry-standard harmless "virus" every scanner flags. Built at run time
# so this source file itself does not trip a developer's virus scanner.
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
_FOUND = re.compile(r"^stream: (?P<signature>.+) FOUND$")
_VERSION = re.compile(r"^ClamAV (?P<engine>[^/]+)/(?P<signatures>\d+)/(?P<date>.+)$")


class ScannerUnavailableError(Exception):
    """The scanner could not be reached or gave no verdict (the scan is retried)."""


@dataclass(frozen=True)
class Verdict:
    """Clean, or infected with a named signature."""

    infected: bool
    signature: str | None = None


@dataclass(frozen=True)
class ScannerVersion:
    """Engine, signature database number and its date (for the staleness alert)."""

    engine: str
    signatures: int
    signature_date: datetime | None


class Scanner(Protocol):
    """What the files service needs from a scanner."""

    @property
    def available(self) -> bool:
        """Whether a scanner is installed at all."""
        ...

    async def scan(self, data: AsyncIterator[bytes]) -> Verdict:
        """The verdict for the streamed file, or ScannerUnavailableError."""
        ...

    async def version(self) -> ScannerVersion:
        """The engine and signature date, or ScannerUnavailableError."""
        ...


class NoScanner:
    """No scanner installed: nothing is scanned, and everyone is told so."""

    available = False

    async def scan(self, data: AsyncIterator[bytes]) -> Verdict:
        """Never called: files are not sent to a scanner that does not exist."""
        del data
        raise ScannerUnavailableError

    async def version(self) -> ScannerVersion:
        """No scanner, no version."""
        raise ScannerUnavailableError


@dataclass
class FakeScanner:
    """Tests: EICAR is malware, everything else is clean; `down` simulates an outage."""

    down: bool = False
    signature_date: datetime | None = None
    available: bool = True

    async def scan(self, data: AsyncIterator[bytes]) -> Verdict:
        """EICAR found, or clean."""
        if self.down:
            raise ScannerUnavailableError
        if EICAR in b"".join([piece async for piece in data]):
            return Verdict(infected=True, signature="Eicar-Test-Signature")
        return Verdict(infected=False)

    async def version(self) -> ScannerVersion:
        """A fixed engine with the configured signature date."""
        if self.down:
            raise ScannerUnavailableError
        return ScannerVersion("1.5.4", 27800, self.signature_date or datetime.now(UTC))


def parse_version(reply: str) -> ScannerVersion:
    """Parse the VERSION reply of clamd, e.g. `ClamAV 1.5.4/27801/Sun Oct 25 08:24:12 2026`."""
    match = _VERSION.match(reply.strip().rstrip("\x00"))  # clamd ends z-replies with NUL
    if match is None:
        raise ScannerUnavailableError
    try:
        date = datetime.strptime(match["date"].strip(), "%a %b %d %H:%M:%S %Y").replace(tzinfo=UTC)
    except ValueError:
        date = None
    return ScannerVersion(match["engine"], int(match["signatures"]), date)


def parse_verdict(reply: str) -> Verdict:
    """Parse the INSTREAM reply of clamd: `stream: OK`, `stream: <name> FOUND`, or an error."""
    text = reply.strip().rstrip("\x00")
    if text == "stream: OK":
        return Verdict(infected=False)
    found = _FOUND.match(text)
    if found is not None:
        return Verdict(infected=True, signature=found["signature"][:200])
    raise ScannerUnavailableError  # "INSTREAM size limit exceeded. ERROR" and the like


@dataclass(frozen=True)
class ClamdScanner:
    """clamd at host:port."""

    host: str
    port: int
    timeout: float
    available: bool = True

    @classmethod
    def from_address(cls, address: str, timeout: float) -> "ClamdScanner":
        """From "host:port" (the `files_clamd_address` setting)."""
        host, _, port = address.rpartition(":")
        return cls(host, int(port), timeout)

    async def _exchange(
        self, command: bytes, body: Callable[[asyncio.StreamWriter], Awaitable[None]]
    ) -> str:
        try:
            async with asyncio.timeout(self.timeout):
                reader, writer = await asyncio.open_connection(self.host, self.port)
                try:
                    writer.write(command)
                    await body(writer)
                    await writer.drain()
                    reply = await reader.read(4096)
                finally:
                    writer.close()
        except (OSError, TimeoutError) as error:
            raise ScannerUnavailableError from error
        return reply.decode("utf-8", errors="replace")

    async def scan(self, data: AsyncIterator[bytes]) -> Verdict:
        """Stream the file to clamd piece by piece (never whole in memory) and read its verdict."""

        async def send(writer: asyncio.StreamWriter) -> None:
            async for chunk in data:
                for offset in range(0, len(chunk), _INSTREAM_PIECE):
                    piece = chunk[offset : offset + _INSTREAM_PIECE]
                    writer.write(len(piece).to_bytes(4, "big") + piece)
                    await writer.drain()
            writer.write(b"\x00\x00\x00\x00")

        return parse_verdict(await self._exchange(b"zINSTREAM\x00", send))

    async def version(self) -> ScannerVersion:
        """Engine and signature date."""

        async def nothing(writer: asyncio.StreamWriter) -> None:
            del writer

        return parse_version(await self._exchange(b"zVERSION\x00", nothing))
