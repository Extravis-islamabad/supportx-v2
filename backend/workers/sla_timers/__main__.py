"""`python -m workers.sla_timers` (make worker-sla): the SLA clocks' Temporal worker until stopped.

Runs the `SlaClock` workflow and its activities on task queue `sla` (wp-025-plan.md §3.5,
ADR-037). Needs SUPPORTX_DATABASE_URL and SUPPORTX_TEMPORAL_ADDRESS. Several replicas share the
queue; Temporal hands each task to one of them, and `sla.fire` makes a repeated task a no-op.
"""

import asyncio
import sys

from temporalio.worker import Worker

from app.core.database import Database, create_engine
from app.core.logging import get_logger
from app.core.modules import discover_modules
from app.modules.sla.infra.temporal import SlaClockWorkflow, connect, workflow_runner
from workers import runtime
from workers.sla_timers.activities import SlaActivities

log = get_logger("workers.sla_timers")


async def main(stop: asyncio.Event) -> None:
    """Poll the `sla` task queue until `stop`."""
    settings = runtime.load_settings("supportx-sla-timers")
    if settings.database_url is None or settings.temporal_address is None:
        msg = "SUPPORTX_DATABASE_URL and SUPPORTX_TEMPORAL_ADDRESS must be set (make backend-env)"
        raise RuntimeError(msg)
    discover_modules()  # record types (incidents) register their SLA hooks at import
    started = asyncio.Event()
    ops = await runtime.start_ops(settings, ready=lambda: started.is_set() and not stop.is_set())
    database = Database(
        create_engine(
            settings.database_url.get_secret_value(),
            application_name="supportx-sla-timers",
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
    )
    client = await connect(settings.temporal_address, settings.temporal_namespace)
    activities = SlaActivities(database)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[SlaClockWorkflow],
        activities=[activities.next_wake, activities.fire],
        workflow_runner=workflow_runner(),
    )
    started.set()
    log.info("sla_timers_started", task_queue=settings.temporal_task_queue)
    try:
        async with worker:
            await stop.wait()
    finally:
        await database.dispose()
        await runtime.stop_ops(ops)


if __name__ == "__main__":
    sys.exit(runtime.run(main))
