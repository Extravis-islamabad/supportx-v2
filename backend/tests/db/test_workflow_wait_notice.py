"""A request's workflow tells its technician once per wait (WP-047a S5 follow-up; REQ-SR-053 AC1).

Real PostgreSQL with RLS, the consumer and the notification engine run as their workers do
(claim, then act). Lane B's conditions: one notice per started wait, none again on a redelivered
event, the group when there is no technician (never the requester), a loop back to the same wait
tells again, and a muted preference tells nobody (it is not required).
"""

import json
import uuid
from typing import Any

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.automation.infra.models import Workflow, WorkflowVersion
from app.modules.automation.service import workflow_runtime
from app.modules.notifications.service.engine import dispatch
from app.modules.work_items.service.workflow_waits import WORKFLOW_WAITS, on_instance_changed
from app.shared.events import EventEnvelope
from app.shared.events.consumers import claim
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import Org, World
from tests.db.test_notifications_api import NO_MAIL
from tests.db.test_service_requests_api import an_item, raise_request
from tests.db.test_workflow_events import WAIT_FOR_P1

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

CODE = "service_request.workflow_waiting"


async def _flow(world: World, org: Org) -> uuid.UUID:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        flow = Workflow(
            tenant_id=org.tenant,
            record_type="service_request",
            name=f"Wait {uuid.uuid4().hex[:6]}",
            draft=WAIT_FOR_P1,
            enabled=True,
            service_identity_id=org.admin,
            published_version=1,
        )
        session.add(flow)
        await session.flush()
        session.add(
            WorkflowVersion(
                tenant_id=org.tenant,
                workflow_id=flow.id,
                number=1,
                definition=WAIT_FOR_P1,
            )
        )
        return flow.id


async def _request(world: World, org: Org, *, technician: bool) -> dict[str, Any]:
    item = await an_item(world, org)
    made = await raise_request(
        world,
        org,
        org.admin,
        catalog_item_id=item["id"],
        answers={"model": "air"},
        group_id=str(org.ga),
        **({"technician_id": str(org.tech_a)} if technician else {}),
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _start(world: World, org: Org, flow: uuid.UUID, record: dict[str, Any]) -> uuid.UUID:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        instance = await workflow_runtime.start(
            session,
            workflow_id=flow,
            record_type="service_request",
            record_id=uuid.UUID(record["id"]),
            how="manual",
        )
        return instance.id


async def _events(world: World, org: Org, event_type: str, key: str, value: str) -> list[str]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND envelope->>'event_type' = $2"
        " AND envelope->'payload'->>$3 = $4 ORDER BY id",
        org.tenant,
        event_type,
        key,
        value,
    )
    return [
        r["envelope"] if isinstance(r["envelope"], str) else json.dumps(r["envelope"]) for r in rows
    ]


async def _run(world: World, org: Org, consumer: str, envelope: str, *, notify: bool) -> None:
    """As the worker does: claim the event once, then act (the consumer, or the engine)."""
    event = EventEnvelope.model_validate(json.loads(envelope))
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            if await claim(session, consumer, event):
                if notify:
                    await dispatch(session, NO_MAIL, event)
                else:
                    await on_instance_changed(event, session)
    finally:
        await database.dispose()


async def _waits_then_notify(world: World, org: Org, instance: uuid.UUID) -> None:
    """Every instance event of the run through the consumer, then each waiting event out."""
    for env in await _events(
        world, org, "automation.workflow_instance.changed", "instance_id", str(instance)
    ):
        await _run(world, org, WORKFLOW_WAITS.name, env, notify=False)
        await _run(world, org, WORKFLOW_WAITS.name, env, notify=False)  # redelivered: skipped
    for env in await _events(
        world, org, "work_items.service_request.workflow_waiting", "instance_id", str(instance)
    ):
        await _run(world, org, "notifications__engine", env, notify=True)
        await _run(world, org, "notifications__engine", env, notify=True)  # redelivered


async def _told(world: World, org: Org, record: dict[str, Any]) -> list[uuid.UUID]:
    rows = await world.sql(
        "SELECT user_id FROM notifications WHERE tenant_id = $1 AND event_code = $2"
        " AND record_id = $3 ORDER BY user_id",
        org.tenant,
        CODE,
        uuid.UUID(record["id"]),
    )
    return [r["user_id"] for r in rows]


async def test_the_technician_is_told_once_per_wait(world: World) -> None:
    a = world.a
    flow = await _flow(world, a)
    record = await _request(world, a, technician=True)
    instance = await _start(world, a, flow, record)
    await _waits_then_notify(world, a, instance)
    assert await _told(world, a, record) == [a.tech_a]  # once, never again on redelivery
    waiting = await _events(
        world, a, "work_items.service_request.workflow_waiting", "instance_id", str(instance)
    )
    payload = json.loads(waiting[0])["payload"]
    assert (payload["node_id"], payload["wait_kind"]) == ("w", "field")  # codes, never words


async def test_without_a_technician_the_group_never_the_requester(world: World) -> None:
    a = world.a
    flow = await _flow(world, a)
    record = await _request(world, a, technician=False)
    instance = await _start(world, a, flow, record)
    await _waits_then_notify(world, a, instance)
    told = await _told(world, a, record)
    assert told  # the group's members
    assert uuid.UUID(record["requester_id"]) not in told  # never the requester


async def test_a_loop_back_to_the_same_wait_tells_again(world: World) -> None:
    a = world.a
    flow = await _flow(world, a)
    record = await _request(world, a, technician=True)
    instance = await _start(world, a, flow, record)
    await _waits_then_notify(world, a, instance)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        stopped = await workflow_runtime.stop(
            session, instance, reason="again", expected_version=None
        )
        await workflow_runtime.restart(
            session, instance, node="w", expected_version=stopped.version
        )
    await _waits_then_notify(world, a, instance)
    assert await _told(world, a, record) == [a.tech_a, a.tech_a]  # a new wait: told again


async def test_a_muted_preference_tells_nobody(world: World) -> None:
    a = world.a
    prefs = await world.call("GET", "/notifications/preferences", a, a.tech_a)
    saved = await world.call(
        "PUT",
        "/notifications/preferences",
        a,
        a.tech_a,
        json={"off": [{"category": "assignment", "channel": "in_app"}]},
        headers={"If-Match": prefs.headers["etag"]},
    )
    assert saved.status_code == 200, saved.text
    try:
        flow = await _flow(world, a)
        record = await _request(world, a, technician=True)
        instance = await _start(world, a, flow, record)
        await _waits_then_notify(world, a, instance)
        assert await _told(world, a, record) == []  # not required: muted is muted
    finally:
        current = await world.call("GET", "/notifications/preferences", a, a.tech_a)
        await world.call(
            "PUT",
            "/notifications/preferences",
            a,
            a.tech_a,
            json={"off": []},
            headers={"If-Match": current.headers["etag"]},
        )
