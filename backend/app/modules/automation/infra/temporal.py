"""The workflow instance waker on Temporal (WP-048b S1, ADR-043 §5; ADR-004, ADR-037).

Temporal is only the alarm clock; PostgreSQL holds every instance's state and next wake time.
One Temporal workflow per instance, `wf:<tenant>:<instance>` on its own task queue:

1. activity `wf_next_wake`: the instance's next wake time (None: it is not waiting on a timer);
2. wait for that moment, or for the `changed` signal (the instance moved on and planned again);
3. at the moment, activity `wf_fire` runs the instance with a timer event (`run` applies only
   what is new, so a repeated wake is harmless);
4. again, until nothing is pending; after `HISTORY_LIMIT` turns it continues as new.

The workflow does no I/O and reads no clock but `workflow.now()`. Requests never talk to Temporal:
an instance's change reaches the `automation__workflow_scheduler` consumer through the outbox,
which signals (or starts) the workflow. The minute sweep (`workflow_events.wake_due`) is the net
beneath it when Temporal is down or not configured.
"""

import contextlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

WORKFLOW = "WorkflowInstanceWaker"
WF_NEXT_WAKE = "wf_next_wake"  # activity names (workers/workflow_timers)
WF_FIRE = "wf_fire"
CHANGED = "changed"
HISTORY_LIMIT = 100
ACTIVITY_TIMEOUT = timedelta(seconds=60)
RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)


@dataclass(frozen=True)
class InstanceRef:
    """Which instance: its tenant and its ID (as text, for the payload converter)."""

    tenant_id: str
    instance_id: str


def workflow_id(tenant_id: uuid.UUID, instance_id: uuid.UUID) -> str:
    """One Temporal workflow per instance (ADR-043 §5)."""
    return f"wf:{tenant_id}:{instance_id}"


@workflow.defn(name=WORKFLOW)
class WorkflowInstanceWaker:
    """Wake at the instance's next moment; plan again when signalled."""

    def __init__(self) -> None:
        """No signal yet."""
        self._changed = False

    @workflow.signal(name=CHANGED)
    def changed(self) -> None:
        """The instance moved on: plan again (idempotent: it only means "look")."""
        self._changed = True

    @workflow.run
    async def run(self, ref: InstanceRef) -> None:
        """The loop above; ends when the instance waits on no timer."""
        for _ in range(HISTORY_LIMIT):
            self._changed = False
            wake: str | None = await workflow.execute_activity(
                WF_NEXT_WAKE, ref, start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=RETRY
            )
            if wake is None:
                if self._changed:
                    continue
                return  # finished, failed, cancelled or waiting on an event only
            delay = (datetime.fromisoformat(wake) - workflow.now()).total_seconds()
            if delay > 0:
                with contextlib.suppress(TimeoutError):
                    await workflow.wait_condition(lambda: self._changed, timeout=delay)
                if self._changed:
                    continue
            await workflow.execute_activity(
                WF_FIRE, ref, start_to_close_timeout=ACTIVITY_TIMEOUT, retry_policy=RETRY
            )
        workflow.continue_as_new(ref)


def workflow_runner() -> SandboxedWorkflowRunner:
    """Temporal's sandbox, with the app passed through (imported once, outside the sandbox)."""
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules("app")
    )


async def connect(address: str, namespace: str) -> Client:
    """A Temporal client (the worker's and the scheduler's)."""
    return await Client.connect(address, namespace=namespace)


class TemporalInstanceWaker:
    """Signals an instance's Temporal workflow, starting it if it is not running."""

    def __init__(self, client: Client, task_queue: str) -> None:
        """With a connected client."""
        self.client = client
        self.task_queue = task_queue

    async def changed(self, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> None:
        """Plan the instance's next wake again (idempotent)."""
        await self.client.start_workflow(
            WORKFLOW,
            InstanceRef(str(tenant_id), str(instance_id)),
            id=workflow_id(tenant_id, instance_id),
            task_queue=self.task_queue,
            start_signal=CHANGED,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
