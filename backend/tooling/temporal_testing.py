"""Temporal's time-skipping test server for tests, downloaded once and kept (CI cache).

`WorkflowEnvironment.start_time_skipping()` downloads the test-server binary on every run when
nothing is cached. GitHub's runners share an address, so the download host answered "429 Too
Many Requests" and failed unrelated PRs (2026-11-04). Tests start it through `time_skipping()`:
- the binary goes to SUPPORTX_TEMPORAL_TEST_SERVER_DIR when set (CI caches that directory,
  keyed on the temporalio version); otherwise the system's temporary folder, as before;
- a failed download is tried again, a few times with growing pauses, before the test fails.

Dev tooling only, never imported by the app.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from temporalio.testing import WorkflowEnvironment

ATTEMPTS = 4
FIRST_PAUSE_SECONDS = 5.0

Start = Callable[..., Awaitable[WorkflowEnvironment]]


def download_dir() -> str | None:
    """Where the binary is kept, if a directory is configured (created when missing)."""
    found = os.environ.get("SUPPORTX_TEMPORAL_TEST_SERVER_DIR", "").strip()
    if not found:
        return None
    Path(found).mkdir(parents=True, exist_ok=True)
    return found


async def time_skipping(
    start: Start = WorkflowEnvironment.start_time_skipping,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> WorkflowEnvironment:
    """A started time-skipping environment, its binary downloaded at most once per cache."""
    pause = FIRST_PAUSE_SECONDS
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return await start(download_dest_dir=download_dir())
        except RuntimeError as error:  # the SDK's core reports a failed download this way
            if attempt == ATTEMPTS or "download" not in str(error).lower():
                raise
            await sleep(pause)
            pause *= 2
    msg = "unreachable: the last attempt returns or raises"
    raise AssertionError(msg)
