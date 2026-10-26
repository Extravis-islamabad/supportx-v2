"""Load check for uploads (WP-022 plan, risk 1): uploads stream, memory stays flat.

Opt-in: SUPPORTX_FILES_LOAD_UPLOADS=50 (and SUPPORTX_FILES_LOAD_MB=25) uploads that many files of
that size at once through the real app into real S3 storage, and measures what the Python process
allocated meanwhile (tracemalloc peak). Streaming plus the upload gate keep the peak proportional
to the uploads writing at once (8), not to the bytes uploaded or the number of people uploading.
Prints throughput and the peak.
"""

import asyncio
import os
import time
import tracemalloc
import uuid
from collections.abc import AsyncIterator

import pytest

from tests.db.test_audit_exports import storage
from tests.db.test_files_api import KEYRING, files
from tests.db.test_incidents_api import CONSOLE, World, world

__all__ = ["files", "storage", "world"]  # fixtures, re-used

pytestmark = [pytest.mark.db, pytest.mark.scale]

UPLOADS = int(os.environ.get("SUPPORTX_FILES_LOAD_UPLOADS", "0"))
MB = int(os.environ.get("SUPPORTX_FILES_LOAD_MB", "25"))
PIECE = 256 * 1024


async def _body(size: int) -> AsyncIterator[bytes]:
    """`size` bytes generated piece by piece (the client never holds the file either)."""
    piece = os.urandom(PIECE)
    sent = 0
    while sent < size:
        chunk = piece[: min(PIECE, size - sent)]
        sent += len(chunk)
        yield chunk


@pytest.mark.skipif(UPLOADS <= 0, reason="set SUPPORTX_FILES_LOAD_UPLOADS to run the load check")
async def test_parallel_uploads_stream_with_flat_memory(world: World, files: object) -> None:
    del files
    assert KEYRING is not None
    a = world.a
    item = await world.create(a, a.tech_a)
    size = MB * 1_000_000

    async def one() -> tuple[int, str]:
        response = await world.call(
            "POST",
            "/files",
            a,
            a.tech_a,
            params={"owner_type": "work_item", "owner_id": item["id"], "name": "big.bin"},
            content=_body(size),
            headers={
                "Idempotency-Key": str(uuid.uuid4()),
                "Content-Length": str(size),
                **CONSOLE,
            },
        )
        problem = response.json().get("code", "") if response.status_code != 201 else ""
        return response.status_code, problem

    tracemalloc.start()
    began = time.perf_counter()
    statuses = await asyncio.gather(*(one() for _ in range(UPLOADS)))
    seconds = time.perf_counter() - began
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    total_mb = UPLOADS * MB
    print(  # noqa: T201 - the load check's result
        f"uploads={UPLOADS} size_mb={MB} total_mb={total_mb} seconds={seconds:.1f} "
        f"mb_per_second={total_mb / seconds:.1f} python_peak_mb={peak / 1e6:.1f}",
        flush=True,
    )
    refused = [found for found in statuses if found[0] != 201]
    assert refused == [], f"{len(refused)} refused: {sorted(set(refused))}"
    # Streaming: at most `upload_concurrency` uploads (8) write at once, each holding about one
    # 5 MiB S3 part plus its encryption and the HTTP client's copies; never whole files, and never
    # more as the number of people uploading grows (the rest wait with their bodies unread).
    # Measured: about 48 MB per upload writing (both ends of the request run in this process).
    active = min(UPLOADS, 8)
    assert peak < active * 48 * 1024 * 1024 + 64 * 1024 * 1024
