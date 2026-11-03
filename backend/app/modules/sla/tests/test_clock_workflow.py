"""The SLA clock workflow on Temporal's time-skipping test server (WP-025 session 3).

The activities are fakes with the real names: the workflow's own logic is under test (wait for
the moment, fire, plan again on a signal, end when nothing is pending). Time skips, so an
"in four hours" moment takes milliseconds.
"""

import uuid
from datetime import datetime, timedelta

from temporalio import activity
from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from app.modules.sla.infra.temporal import (
    SLA_FIRE,
    SLA_NEXT_WAKE,
    ClockRef,
    SlaClockWorkflow,
    TemporalWaker,
    workflow_id,
    workflow_runner,
)

QUEUE = "sla-test"


class FakeClocks:
    """A record whose pending moments are a list; firing takes the first one away."""

    def __init__(self, moments: list[datetime]) -> None:
        self.moments = moments
        self.fired_at: list[datetime] = []

    @activity.defn(name=SLA_NEXT_WAKE)
    async def next_wake(self, ref: ClockRef) -> str | None:
        del ref
        return self.moments[0].isoformat() if self.moments else None

    @activity.defn(name=SLA_FIRE)
    async def fire(self, ref: ClockRef) -> int:
        del ref
        now = activity.info().scheduled_time  # the test server's (skipped) time
        due = [m for m in self.moments if m <= now + timedelta(seconds=1)]
        self.moments = [m for m in self.moments if m not in due]
        self.fired_at.append(now)
        return len(due)


async def test_the_workflow_wakes_at_each_moment_then_ends() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        start = await env.get_current_time()
        clocks = FakeClocks([start + timedelta(hours=3), start + timedelta(hours=4)])
        async with Worker(
            env.client,
            task_queue=QUEUE,
            workflows=[SlaClockWorkflow],
            activities=[clocks.next_wake, clocks.fire],
            workflow_runner=workflow_runner(),
        ):
            tenant, record = uuid.uuid4(), uuid.uuid4()
            await TemporalWaker(env.client, QUEUE).changed(tenant, record)
            handle = env.client.get_workflow_handle(workflow_id(tenant, record))
            await env.sleep(timedelta(hours=5))  # past both moments
            await handle.result()
            history = await handle.fetch_history()
    assert clocks.moments == []
    assert len(clocks.fired_at) == 2
    # Replay: a change to the workflow that breaks determinism fails here (and in CI).
    await Replayer(workflows=[SlaClockWorkflow], workflow_runner=workflow_runner()).replay_workflow(
        WorkflowHistory.from_json(history.workflow_id, history.to_json())
    )


async def test_a_signal_plans_again_before_the_moment() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        start = await env.get_current_time()
        clocks = FakeClocks([start + timedelta(hours=4)])
        async with Worker(
            env.client,
            task_queue=QUEUE,
            workflows=[SlaClockWorkflow],
            activities=[clocks.next_wake, clocks.fire],
            workflow_runner=workflow_runner(),
        ):
            tenant, record = uuid.uuid4(), uuid.uuid4()
            waker = TemporalWaker(env.client, QUEUE)
            await waker.changed(tenant, record)
            handle = env.client.get_workflow_handle(workflow_id(tenant, record))
            # A save pulls the moment in (a due date set by hand), then signals: same workflow.
            clocks.moments = [start + timedelta(minutes=30)]
            await waker.changed(tenant, record)
            await env.sleep(timedelta(hours=1))
            await handle.result()
    assert len(clocks.fired_at) == 1
    assert clocks.fired_at[0] < start + timedelta(hours=1)
