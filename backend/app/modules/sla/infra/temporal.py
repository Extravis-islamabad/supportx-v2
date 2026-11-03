"""The SLA waker on Temporal (WP-025 session 3; wp-025-plan.md §3.5, ADR-004, ADR-037).

Temporal is only the alarm clock; PostgreSQL holds every due moment. One workflow per record,
`sla:<tenant>:<record>` on task queue `sla`:

1. activity `sla_next_wake`: the earliest pending moment (a warning, a due moment, a level);
2. wait for that moment, or for the `changed` signal (a save moved the clocks);
3. at the moment, activity `sla_fire` fires what is due (exactly once: `timers.fire`);
4. again, until nothing is pending; after `HISTORY_LIMIT` turns it continues as new.

The workflow does no I/O and reads no clock but `workflow.now()` (determinism; every change to
it needs `workflow.patched` and the replay test). A save never talks to Temporal: the outbox
event reaches the `sla__scheduler` consumer, which signals (or starts) the workflow. The
activities themselves run in `workers/sla_timers` (they call the sla service).
"""

import contextlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

WORKFLOW = "SlaClock"
SLA_NEXT_WAKE = "sla_next_wake"  # activity names (workers/sla_timers)
SLA_FIRE = "sla_fire"
CHANGED = "changed"
HISTORY_LIMIT = 100  # turns before continue-as-new (each turn adds ~6 events: under 1,000)
ACTIVITY_TIMEOUT = timedelta(seconds=30)
RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)


@dataclass(frozen=True)
class ClockRef:
    """Which record's clocks: its tenant and its ID (as text, for the payload converter)."""

    tenant_id: str
    record_id: str


def workflow_id(tenant_id: uuid.UUID, record_id: uuid.UUID) -> str:
    """One workflow per record (ADR-004)."""
    return f"sla:{tenant_id}:{record_id}"


@workflow.defn(name=WORKFLOW)
class SlaClockWorkflow:
    """Wake at each pending moment of one record; plan again when signalled."""

    def __init__(self) -> None:
        """No signal yet."""
        self._changed = False

    @workflow.signal(name=CHANGED)
    def changed(self) -> None:
        """A save moved the record's clocks: plan again (idempotent: it only means "look")."""
        self._changed = True

    @workflow.run
    async def run(self, ref: ClockRef) -> None:
        """The loop of §3.5; ends when nothing is pending."""
        for _ in range(HISTORY_LIMIT):
            self._changed = False
            wake: str | None = await workflow.execute_activity(
                SLA_NEXT_WAKE, ref, start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=RETRY
            )
            if wake is None:
                if self._changed:
                    continue  # a save came while asking: ask again
                return  # met, resolved, closed or canceled: a save starts it again
            delay = (datetime.fromisoformat(wake) - workflow.now()).total_seconds()
            if delay > 0:
                with contextlib.suppress(TimeoutError):  # the moment came
                    await workflow.wait_condition(lambda: self._changed, timeout=delay)
                if self._changed:
                    continue  # planned again before the moment came
            await workflow.execute_activity(
                SLA_FIRE, ref, start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=RETRY
            )
        workflow.continue_as_new(ref)


def workflow_runner() -> SandboxedWorkflowRunner:
    """Temporal's sandbox, with the app's own modules passed through.

    The workflow module lives in the app package, whose import loads the whole app (routes,
    models, IDs with randomness). Passing `app` through imports it once, outside the sandbox;
    the workflow's own code still runs sandboxed and does no I/O.
    """
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules("app")
    )


async def connect(address: str, namespace: str) -> Client:
    """A Temporal client (the worker's and the scheduler's)."""
    return await Client.connect(address, namespace=namespace)


class TemporalWaker:
    """Signals a record's workflow, starting it if it is not running (the scheduler's port)."""

    def __init__(self, client: Client, task_queue: str) -> None:
        """With a connected client."""
        self.client = client
        self.task_queue = task_queue

    async def changed(self, tenant_id: uuid.UUID, record_id: uuid.UUID) -> None:
        """Plan the record's clocks again (idempotent)."""
        await self.client.start_workflow(
            WORKFLOW,
            ClockRef(str(tenant_id), str(record_id)),
            id=workflow_id(tenant_id, record_id),
            task_queue=self.task_queue,
            start_signal=CHANGED,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )


__all__ = [
    "CHANGED",
    "SLA_FIRE",
    "SLA_NEXT_WAKE",
    "WORKFLOW",
    "ClockRef",
    "SlaClockWorkflow",
    "TemporalWaker",
    "connect",
    "workflow_id",
    "workflow_runner",
]
