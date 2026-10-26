"""Chunked AES-256-GCM: how a file is stored encrypted (ADR-028 item 2).

    object = header | chunk 0 | chunk 1 | ... | chunk n-1
    header = b"SXF1" | data key id (16 bytes) | nonce prefix (8 random bytes)
    chunk i = AES-256-GCM(plaintext[i * 1 MiB : (i + 1) * 1 MiB]) with its 16-byte tag

The nonce of chunk i is the prefix followed by i (4 bytes, big-endian). The associated data is the
file ID, i and a last-chunk flag, so chunks cannot be reordered, moved to another file, or cut off
at a chunk boundary unnoticed. Every chunk but the last holds exactly 1 MiB, so the ciphertext
offset of any plaintext byte is known: ranges (PDF previews) decrypt only the chunks they touch.
An empty file is one empty last chunk.
"""

import os
import uuid
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CHUNK = 1 << 20
TAG = 16
MAGIC = b"SXF1"
PREFIX_BYTES = 8
HEADER = len(MAGIC) + 16 + PREFIX_BYTES
MAX_CHUNKS = 1 << 32


class ChunkError(ValueError):
    """The ciphertext is not a valid encrypted file (tampered, truncated or another key)."""


def chunk_count(plain_size: int) -> int:
    """How many chunks a file of this size has (at least one)."""
    return max(1, -(-plain_size // CHUNK))


def encrypted_size(plain_size: int) -> int:
    """Bytes stored for a file of `plain_size` bytes."""
    return HEADER + plain_size + TAG * chunk_count(plain_size)


def _nonce(prefix: bytes, index: int) -> bytes:
    return prefix + index.to_bytes(4, "big")


def _aad(file_id: uuid.UUID, index: int, last: bool) -> bytes:  # noqa: FBT001 - one flag of the format
    return file_id.bytes + index.to_bytes(8, "big") + (b"\x01" if last else b"\x00")


@dataclass(frozen=True)
class Header:
    """The data key a file was encrypted with, and its nonce prefix."""

    key_id: uuid.UUID
    prefix: bytes

    def to_bytes(self) -> bytes:
        """The header as stored."""
        return MAGIC + self.key_id.bytes + self.prefix

    @classmethod
    def parse(cls, data: bytes) -> "Header":
        """Read a stored header."""
        if len(data) < HEADER or not data.startswith(MAGIC):
            msg = "not an encrypted SupportX file"
            raise ChunkError(msg)
        return cls(uuid.UUID(bytes=data[4:20]), data[20:HEADER])


class Encryptor:
    """Encrypts one file chunk by chunk, in order."""

    def __init__(self, data_key: bytes, file_id: uuid.UUID, key_id: uuid.UUID) -> None:
        self._aead = AESGCM(data_key)
        self._file_id = file_id
        self.header = Header(key_id, os.urandom(PREFIX_BYTES))
        self._index = 0

    def seal(self, plaintext: bytes, *, last: bool) -> bytes:
        """The next chunk. Every chunk except the last must be exactly CHUNK bytes."""
        if (not last and len(plaintext) != CHUNK) or len(plaintext) > CHUNK:
            msg = "chunks other than the last must be exactly 1 MiB"
            raise ChunkError(msg)
        if self._index >= MAX_CHUNKS:
            msg = "file too large for one nonce prefix"
            raise ChunkError(msg)
        sealed = self._aead.encrypt(
            _nonce(self.header.prefix, self._index),
            plaintext,
            _aad(self._file_id, self._index, last),
        )
        self._index += 1
        return sealed


class Decryptor:
    """Decrypts chunks of one file, in any order (ranges)."""

    def __init__(self, data_key: bytes, file_id: uuid.UUID, header: Header) -> None:
        self._aead = AESGCM(data_key)
        self._file_id = file_id
        self._header = header

    def open(self, index: int, sealed: bytes, *, last: bool) -> bytes:
        """The plaintext of chunk `index`, or ChunkError when it was changed."""
        try:
            return self._aead.decrypt(
                _nonce(self._header.prefix, index), sealed, _aad(self._file_id, index, last)
            )
        except Exception as error:  # cryptography raises InvalidTag; anything else is corrupt too
            msg = f"chunk {index} does not decrypt"
            raise ChunkError(msg) from error


@dataclass(frozen=True)
class ChunkSpan:
    """The chunks covering a plaintext range, where they are stored, and what to keep of them."""

    first: int
    last: int
    stored_start: int  # inclusive
    stored_end: int  # inclusive
    skip: int  # plaintext bytes to drop from the first chunk
    length: int  # plaintext bytes to return


def span(plain_size: int, start: int, end: int) -> ChunkSpan:
    """Chunks for plaintext bytes start..end (inclusive), for a file of `plain_size` bytes."""
    if plain_size == 0:
        return ChunkSpan(0, 0, HEADER, HEADER + TAG - 1, 0, 0)
    if not 0 <= start <= end < plain_size:
        msg = "range outside the file"
        raise ChunkError(msg)
    first, last = start // CHUNK, end // CHUNK
    count = chunk_count(plain_size)
    stored_start = HEADER + first * (CHUNK + TAG)
    last_plain = min(CHUNK, plain_size - last * CHUNK) if last == count - 1 else CHUNK
    stored_end = HEADER + last * (CHUNK + TAG) + last_plain + TAG - 1
    return ChunkSpan(first, last, stored_start, stored_end, start - first * CHUNK, end - start + 1)


def chunk_lengths(plain_size: int, first: int, last: int) -> list[int]:
    """Stored length of each chunk first..last."""
    count = chunk_count(plain_size)
    lengths = []
    for index in range(first, last + 1):
        plain = CHUNK if index < count - 1 else plain_size - index * CHUNK
        lengths.append(plain + TAG)
    return lengths
