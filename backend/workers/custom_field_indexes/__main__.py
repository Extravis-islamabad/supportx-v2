"""`python -m workers.custom_field_indexes` (make worker-indexes): the index worker until stopped.

Every `index_worker_interval_seconds` it builds the custom field indexes admins asked for
(D-088). Needs SUPPORTX_MIGRATION_DATABASE_URL: only the table owner may create an index.
"""

import asyncio
import sys

from app.core.database import Database, create_engine
from app.core.logging import get_logger
from app.core.modules import discover_modules
from workers import runtime
from workers.custom_field_indexes.indexer import run_pass

log = get_logger("workers.custom_field_indexes")


async def main(stop: asyncio.Event) -> None:
    """Passes until `stop`; a failing pass is logged and the next one tries again."""
    settings = runtime.load_settings("supportx-index-worker")
    if settings.migration_database_url is None:
        msg = "SUPPORTX_MIGRATION_DATABASE_URL is not set (make backend-env)"
        raise RuntimeError(msg)
    discover_modules()
    started = asyncio.Event()
    ops = await runtime.start_ops(settings, ready=lambda: started.is_set() and not stop.is_set())
    database = Database(
        create_engine(
            settings.migration_database_url.get_secret_value(),
            application_name="supportx-index-worker",
            pool_size=2,
            max_overflow=1,
        )
    )
    started.set()
    try:
        while not stop.is_set():
            try:
                await run_pass(
                    database,
                    lock_timeout=settings.index_lock_timeout_seconds,
                    build_timeout=settings.index_build_timeout_seconds,
                )
            except Exception:
                log.exception("custom_field_index_pass_failed")
            await runtime.pause(stop, settings.index_worker_interval_seconds)
    finally:
        await database.dispose()
        await runtime.stop_ops(ops)


if __name__ == "__main__":
    sys.exit(runtime.run(main))
