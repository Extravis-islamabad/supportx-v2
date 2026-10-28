"""Adapters of the files service: clamd protocol, thumbnails under limits, encrypted blobs."""

import asyncio
import io
import struct
import uuid
import zlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from PIL import Image
from pydantic import SecretStr

from app.core.config import Settings
from app.shared.files.domain import chunks
from app.shared.files.infra import blobs, thumbnails
from app.shared.files.infra.scanner import (
    EICAR,
    ClamdScanner,
    FakeScanner,
    NoScanner,
    ScannerUnavailableError,
    parse_verdict,
    parse_version,
)
from app.shared.files.keyring import KeyRing
from app.shared.files.service.core import FileServices, FilesNotConfiguredError
from app.shared.storage import StorageNotConfigured, StorageUnavailable


def test_clamd_replies_are_read() -> None:
    assert not parse_verdict("stream: OK\x00").infected
    found = parse_verdict("stream: Win.Test.EICAR_HDB-1 FOUND\x00")
    assert (found.infected, found.signature) == (True, "Win.Test.EICAR_HDB-1")
    with pytest.raises(ScannerUnavailableError):
        parse_verdict("INSTREAM size limit exceeded. ERROR")
    version = parse_version("ClamAV 1.5.4/27801/Sun Oct 25 08:24:12 2026\x00")
    assert (version.engine, version.signatures) == ("1.5.4", 27801)
    assert version.signature_date == datetime(2026, 10, 25, 8, 24, 12, tzinfo=UTC)
    assert parse_version("ClamAV 1.5.4/1/not a date").signature_date is None
    with pytest.raises(ScannerUnavailableError):
        parse_version("garbage")


async def _pieces(data: bytes, size: int = 70_000) -> AsyncIterator[bytes]:
    for offset in range(0, len(data), size):
        yield data[offset : offset + size]


async def _fake_clamd() -> tuple[asyncio.Server, int]:
    """A clamd that speaks INSTREAM and VERSION, and flags EICAR."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        command = await reader.readuntil(b"\x00")
        if command == b"zVERSION\x00":
            writer.write(b"ClamAV 1.5.4/27801/Sun Oct 25 08:24:12 2026\x00")
        else:
            data = b""
            while True:
                (length,) = struct.unpack(">I", await reader.readexactly(4))
                if length == 0:
                    break
                data += await reader.readexactly(length)
            writer.write(
                b"stream: Eicar-Signature FOUND\x00"
                if data.startswith(EICAR)
                else b"stream: OK\x00"
            )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def test_clamd_scanner_streams_files_in_pieces() -> None:
    server, port = await _fake_clamd()
    async with server:
        scanner = ClamdScanner.from_address(f"127.0.0.1:{port}", timeout=5)
        assert scanner.available
        assert not (await scanner.scan(_pieces(b"x" * 200_000))).infected  # many 64 KiB pieces
        assert (await scanner.scan(_pieces(EICAR))).infected
        assert (await scanner.version()).signatures == 27801
    down = ClamdScanner.from_address("127.0.0.1:1", timeout=1)
    with pytest.raises(ScannerUnavailableError):
        await down.scan(_pieces(b"x"))


async def test_no_and_fake_scanners() -> None:
    assert not NoScanner().available
    with pytest.raises(ScannerUnavailableError):
        await NoScanner().scan(_pieces(b"x"))
    with pytest.raises(ScannerUnavailableError):
        await NoScanner().version()
    fake = FakeScanner(down=True)
    with pytest.raises(ScannerUnavailableError):
        await fake.scan(_pieces(b"x"))
    with pytest.raises(ScannerUnavailableError):
        await fake.version()


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "teal").save(out, "PNG")
    return out.getvalue()


def _bomb(width: int, height: int) -> bytes:
    """A tiny PNG whose header claims a huge image (a decompression bomb)."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )


async def test_thumbnails_are_small_and_bombs_are_refused() -> None:
    thumb = await thumbnails.thumbnail(_png(1600, 900))
    assert thumb is not None
    with Image.open(io.BytesIO(thumb)) as image:
        assert image.format == "WEBP"
        assert image.size == (320, 180)
    assert await thumbnails.thumbnail(_bomb(50_000, 50_000)) is None
    assert await thumbnails.thumbnail(b"not an image") is None
    assert await thumbnails.thumbnail(b"\x00" * (thumbnails.MAX_INPUT_BYTES + 1)) is None
    assert Image.MAX_IMAGE_PIXELS != thumbnails.MAX_PIXELS  # the global limit is restored


class MemoryStorage:
    """ObjectStorage in a dict (blobs tests)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        del content_type
        self.objects[key] = data

    async def get(self, key: str) -> bytes | None:
        return self.objects.get(key)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def check(self) -> None:
        return None

    async def put_stream(self, key: str, parts: AsyncIterator[bytes], content_type: str) -> int:
        del content_type
        data = b"".join([part async for part in parts])
        self.objects[key] = data
        return len(data)

    async def read_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        data = self.objects.get(key)
        if data is None:
            raise StorageUnavailable
        for offset in range(start, end + 1, 1000):
            yield data[offset : min(offset + 1000, end + 1)]


async def _source(data: bytes, piece: int = 70_000) -> AsyncIterator[bytes]:
    for offset in range(0, len(data), piece):
        yield data[offset : offset + piece]


async def test_blobs_round_trip_ranges_and_limits() -> None:
    store, key, file_id = MemoryStorage(), b"k" * 32, uuid.uuid4()
    data = bytes(i % 256 for i in range(chunks.CHUNK * 2 + 333))
    head, stream = await blobs.read_head(_source(data))
    assert head == data[:8192]
    written = await blobs.write(
        store,
        "f",
        data_key=key,
        data_key_id=uuid.uuid4(),
        file_id=file_id,
        source=stream,
        limit=10**8,
    )
    assert written.size == len(data)
    assert written.stored_size == chunks.encrypted_size(len(data))
    whole = await blobs.read_all(store, "f", data_key=key, file_id=file_id, size=len(data))
    assert whole == data
    part = b"".join(
        [
            p
            async for p in blobs.read(
                store,
                "f",
                data_key=key,
                file_id=file_id,
                size=len(data),
                start=chunks.CHUNK - 5,
                end=chunks.CHUNK + 5,
            )
        ]
    )
    assert part == data[chunks.CHUNK - 5 : chunks.CHUNK + 6]
    with pytest.raises(blobs.TooLargeError):
        await blobs.write(
            store,
            "g",
            data_key=key,
            data_key_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            source=_source(data),
            limit=100,
        )
    empty_id = uuid.uuid4()
    await blobs.write(
        store,
        "e",
        data_key=key,
        data_key_id=uuid.uuid4(),
        file_id=empty_id,
        source=_source(b""),
        limit=10,
    )
    assert await blobs.read_all(store, "e", data_key=key, file_id=empty_id, size=0) == b""
    store.objects["f"] = store.objects["f"][: chunks.HEADER + 100]  # truncated object
    with pytest.raises(chunks.ChunkError):
        await blobs.read_all(store, "f", data_key=key, file_id=file_id, size=len(data))


def test_services_from_settings() -> None:
    keys = KeyRing.generate("k9")
    settings = Settings(
        files_keys=SecretStr(keys),
        files_clamd_address="clamav:3310",
        object_storage_endpoint="http://s3:8333",
        object_storage_access_key=SecretStr("a"),
        object_storage_secret_key=SecretStr("b"),
    )
    found = FileServices.from_settings(settings)
    assert found.keyring is not None
    assert found.keyring.active_id == "k9"
    assert isinstance(found.scanner, ClamdScanner)
    assert (found.scanner.host, found.scanner.port) == ("clamav", 3310)
    found.require_storage()
    # No settings at all: a developer's backend/.env must not leak in (it names ClamAV).
    bare = FileServices.from_settings(Settings.load(env_file=None))
    assert isinstance(bare.scanner, NoScanner)
    with pytest.raises(StorageNotConfigured):
        bare.require_storage()
    no_keys = FileServices(storage=found.storage, keyring=None, scanner=NoScanner())
    with pytest.raises(FilesNotConfiguredError):
        no_keys.require_storage()
