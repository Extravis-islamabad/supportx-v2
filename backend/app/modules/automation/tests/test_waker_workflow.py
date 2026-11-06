"""The workflow instance waker on Temporal's time-skipping test server (WP-048b S1).

The activities are fakes with the real names: the waker's own logic is under test (wait for the
instance's moment, fire, plan again on a signal, end when nothing is pending). Time skips.
"""

import uuid
from datetime import datetime, timedelta

from temporalio import activity
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer, Worker

from app.modules.automation.infra.temporal import (
    WF_FIRE,
    WF_NEXT_WAKE,
    InstanceRef,
    TemporalInstanceWaker,
    WorkflowInstanceWaker,
    workflow_id,
    workflow_runner,
)
from tooling.temporal_testing import time_skipping

QUEUE = "workflows-test"


class FakeInstance:
    """An instance waiting on timers; firing passes the first one."""

    def __init__(self, moments: list[datetime]) -> None:
        self.moments = moments
        self.fired = 0

    @activity.defn(name=WF_NEXT_WAKE)
    async def next_wake(self, ref: InstanceRef) -> str | None:
        del ref
        return self.moments[0].isoformat() if self.moments else None

    @activity.defn(name=WF_FIRE)
    async def fire(self, ref: InstanceRef) -> bool:
        del ref
        now = activity.info().scheduled_time
        self.moments = [m for m in self.moments if m > now + timedelta(seconds=1)]
        self.fired += 1
        return True


async def test_req_wf_020_the_waker_fires_each_timer_once_then_ends() -> None:
    async with await time_skipping() as env:
        start = await env.get_current_time()
        instance = FakeInstance([start + timedelta(days=2), start + timedelta(days=3)])
        async with Worker(
            env.client,
            task_queue=QUEUE,
            workflows=[WorkflowInstanceWaker],
            activities=[instance.next_wake, instance.fire],
            workflow_runner=workflow_runner(),
        ):
            tenant, record = uuid.uuid4(), uuid.uuid4()
            await TemporalInstanceWaker(env.client, QUEUE).changed(tenant, record)
            handle = env.client.get_workflow_handle(workflow_id(tenant, record))
            await env.sleep(timedelta(days=4))
            await handle.result()
            history = await handle.fetch_history()
    assert instance.moments == []
    assert instance.fired == 2  # each timer once (REQ-WF-020 AC1)
    await Replayer(
        workflows=[WorkflowInstanceWaker], workflow_runner=workflow_runner()
    ).replay_workflow(WorkflowHistory.from_json(history.workflow_id, history.to_json()))


async def test_an_instance_waiting_on_no_timer_ends_the_waker_at_once() -> None:
    async with await time_skipping() as env:
        instance = FakeInstance([])
        async with Worker(
            env.client,
            task_queue=QUEUE,
            workflows=[WorkflowInstanceWaker],
            activities=[instance.next_wake, instance.fire],
            workflow_runner=workflow_runner(),
        ):
            tenant, record = uuid.uuid4(), uuid.uuid4()
            await TemporalInstanceWaker(env.client, QUEUE).changed(tenant, record)
            await env.client.get_workflow_handle(workflow_id(tenant, record)).result()
    assert instance.fired == 0
