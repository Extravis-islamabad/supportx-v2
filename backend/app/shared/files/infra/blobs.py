"""Encrypted file objects in object storage (ADR-028 item 2; format in domain/chunks.py).

`write` streams plaintext in, enforcing the size limit while it reads, and writes header and
chunks to the store; it returns the size, SHA-256 and first bytes (for sniffing) of the plaintext.
`read` streams plaintext back for a byte range, decrypting only the chunks it touches.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.shared.files.domain import chunks
from app.shared.files.domain.types import SNIFF_BYTES
from app.shared.storage import ObjectStorage


class TooLargeError(Exception):
    """The stream went past the size limit (the upload is aborted, nothing is kept)."""


@dataclass(frozen=True)
class Written:
    """What was stored."""

    size: int
    sha256: bytes
    stored_size: int


async def rechunk(source: AsyncIterator[bytes], size: int = chunks.CHUNK) -> AsyncIterator[bytes]:
    """The stream cut into pieces of exactly `size` bytes (the last may be shorter or empty)."""
    buffer = bytearray()
    async for piece in source:
        buffer += piece
        while len(buffer) >= size:
            yield bytes(buffer[:size])
            del buffer[:size]
    yield bytes(buffer)


async def read_head(source: AsyncIterator[bytes]) -> tuple[bytes, AsyncIterator[bytes]]:
    """The first SNIFF_BYTES of a stream, and a stream that still yields everything."""
    head = bytearray()
    iterator = aiter(source)
    async for piece in iterator:
        head += piece
        if len(head) >= SNIFF_BYTES:
            break

    async def whole() -> AsyncIterator[bytes]:
        yield bytes(head)
        async for piece in iterator:
            yield piece

    return bytes(head[:SNIFF_BYTES]), whole()


async def write(  # noqa: PLR0913 - where, with which key, what, and its limit: explicit
    storage: ObjectStorage,
    key: str,
    *,
    data_key: bytes,
    data_key_id: uuid.UUID,
    file_id: uuid.UUID,
    source: AsyncIterator[bytes],
    limit: int,
) -> Written:
    """Encrypt `source` into `key`. Raises TooLargeError past `limit` bytes (nothing is kept)."""
    encryptor = chunks.Encryptor(data_key, file_id, data_key_id)
    digest = hashlib.sha256()
    total = 0

    async def sealed() -> AsyncIterator[bytes]:
        nonlocal total
        yield encryptor.header.to_bytes()
        pending: bytes | None = None
        async for piece in rechunk(source):
            if pending is not None:
                yield encryptor.seal(pending, last=False)
            total += len(piece)
            if total > limit:
                raise TooLargeError
            digest.update(piece)
            pending = piece
        yield encryptor.seal(pending or b"", last=True)

    stored = await storage.put_stream(key, sealed(), "application/octet-stream")
    return Written(size=total, sha256=digest.digest(), stored_size=stored)


async def read(  # noqa: PLR0913 - where, with which key, and which bytes: explicit
    storage: ObjectStorage,
    key: str,
    *,
    data_key: bytes,
    file_id: uuid.UUID,
    size: int,
    start: int = 0,
    end: int | None = None,
) -> AsyncIterator[bytes]:
    """Plaintext bytes start..end (inclusive; default the whole file), decrypted chunk by chunk."""
    last_byte = size - 1 if end is None else end
    header_bytes = b""
    async for piece in storage.read_range(key, 0, chunks.HEADER - 1):
        header_bytes += piece
    decryptor = chunks.Decryptor(data_key, file_id, chunks.Header.parse(header_bytes))
    if size == 0:
        return
    found = chunks.span(size, start, last_byte)
    lengths = chunks.chunk_lengths(size, found.first, found.last)
    final = chunks.chunk_count(size) - 1
    stream = rechunk_exact(storage.read_range(key, found.stored_start, found.stored_end), lengths)
    remaining, skip = found.length, found.skip
    index = found.first
    async for sealed in stream:
        plain = decryptor.open(index, sealed, last=index == final)
        piece = plain[skip : skip + remaining]
        skip = 0
        remaining -= len(piece)
        index += 1
        if piece:
            yield piece


async def rechunk_exact(source: AsyncIterator[bytes], lengths: list[int]) -> AsyncIterator[bytes]:
    """The stream cut into pieces of the given lengths, in order (stored chunks)."""
    buffer = bytearray()
    wanted = iter(lengths)
    size = next(wanted, None)
    async for piece in source:
        buffer += piece
        while size is not None and len(buffer) >= size:
            yield bytes(buffer[:size])
            del buffer[:size]
            size = next(wanted, None)
    if size is not None:
        msg = "stored object is shorter than its file"
        raise chunks.ChunkError(msg)


async def read_all(
    storage: ObjectStorage, key: str, *, data_key: bytes, file_id: uuid.UUID, size: int
) -> bytes:
    """The whole plaintext (scanner and image processing; bounded by the file size limit)."""
    parts = [
        piece async for piece in read(storage, key, data_key=data_key, file_id=file_id, size=size)
    ]
    return b"".join(parts)
