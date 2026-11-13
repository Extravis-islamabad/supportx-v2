"""`python -m workers.workflow_timers`: the workflow waker's Temporal worker until stopped.

Runs the `WorkflowInstanceWaker` workflow and its activities on the workflows task queue
(WP-048b, ADR-043 §5). Needs SUPPORTX_DATABASE_URL and SUPPORTX_TEMPORAL_ADDRESS. Several
replicas share the queue; the runtime makes a repeated task a no-op.
"""

import asyncio
import sys

from temporalio.worker import Worker

from app.core.database import Database, create_engine, database_ssl
from app.core.logging import get_logger
from app.core.modules import discover_modules
from app.modules.automation.infra.temporal import WorkflowInstanceWaker, connect, workflow_runner
from workers import runtime
from workers.workflow_timers.activities import WorkflowActivities

log = get_logger("workers.workflow_timers")


async def main(stop: asyncio.Event) -> None:
    """Poll the workflows task queue until `stop`."""
    settings = runtime.load_settings("supportx-workflow-timers")
    if settings.database_url is None or settings.temporal_address is None:
        msg = "SUPPORTX_DATABASE_URL and SUPPORTX_TEMPORAL_ADDRESS must be set (make backend-env)"
        raise RuntimeError(msg)
    discover_modules()  # record types register their facts and commands at import
    started = asyncio.Event()
    ops = await runtime.start_ops(settings, ready=lambda: started.is_set() and not stop.is_set())
    database = Database(
        create_engine(
            settings.database_url.get_secret_value(),
            application_name="supportx-workflow-timers",
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            ssl=database_ssl(settings.database_ssl_root_cert),
        ),
        settings,  # its own settings on each session (is outgoing mail set up?)
    )
    client = await connect(settings.temporal_address, settings.temporal_namespace)
    activities = WorkflowActivities(database)
    worker = Worker(
        client,
        task_queue=settings.temporal_workflow_task_queue,
        workflows=[WorkflowInstanceWaker],
        activities=[activities.next_wake, activities.fire],
        workflow_runner=workflow_runner(),
    )
    started.set()
    log.info("workflow_timers_started", task_queue=settings.temporal_workflow_task_queue)
    try:
        async with worker:
            await stop.wait()
    finally:
        await database.dispose()
        await runtime.stop_ops(ops)


if __name__ == "__main__":
    sys.exit(runtime.run(main))
