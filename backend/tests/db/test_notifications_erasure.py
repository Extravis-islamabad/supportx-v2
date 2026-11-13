"""An erased person's notifications go (GDPR; WP-056, found by lane C).

Their in-app entries and delivery rows are deleted, and rules that name them drop them; others'
stay; a plain deactivation keeps everything; doing it twice changes nothing; another tenant is
untouched.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.notifications.service.erasure import on_user_status_changed
from app.shared.events import EventEnvelope
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World
from tests.db.test_notifications_api import _rule, run_engine

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the incidents fixture, re-used


def _changed(tenant: uuid.UUID, user: uuid.UUID, reason: str) -> EventEnvelope:
    return EventEnvelope.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "identity_access.user.status_changed",
            "schema_version": 1,
            "tenant_id": str(tenant),
            "aggregate_type": "user",
            "aggregate_id": str(user),
            "aggregate_version": 1,
            "occurred_at": datetime.now(UTC).isoformat(),
            "actor": {"type": "system", "id": "test"},
            "payload": {"user_id": str(user), "status": "disabled", "reason": reason},
        }
    )


async def _handle(world: World, envelope: EventEnvelope) -> None:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(envelope.tenant_id)) as session:
            await on_user_status_changed(envelope, session)
    finally:
        await database.dispose()


async def _counts(world: World, org: Any, user: uuid.UUID) -> tuple[int, int]:  # noqa: ANN401 - Org
    entries = await world.sql(
        "SELECT count(*) AS n FROM notifications WHERE tenant_id = $1 AND user_id = $2",
        org.tenant,
        user,
    )
    deliveries = await world.sql(
        "SELECT count(*) AS n FROM notification_deliveries WHERE tenant_id = $1 AND user_id = $2",
        org.tenant,
        user,
    )
    return int(entries[0]["n"]), int(deliveries[0]["n"])


async def test_an_erased_persons_notifications_go_and_nobody_elses(world: World) -> None:
    org, other = world.a, world.b
    # tech_b is assigned (an in-app entry and a delivery); a rule also names them.
    rules = (await world.call("GET", "/notifications/rules", org, org.admin)).json()
    created = next(r for r in rules if r["event_code"] == "incident.created")
    named = await world.call(
        "PUT",
        "/notifications/rules/incident.created",
        org,
        org.admin,
        json={**_rule(created), "user_ids": [str(org.tech_b), str(org.tech_a)]},
        headers={"If-Match": f'"{created["version"]}"'},
    )
    assert named.status_code == 200, named.text
    item = await world.create(org, org.lead, group_id=str(org.gb))
    assert (
        await world.assign(org, org.lead, item, group=org.gb, technician=org.tech_b)
    ).status_code == 200
    await run_engine(world, org)
    assert (await _counts(world, org, org.tech_b))[0] > 0
    before_a = await _counts(world, org, org.tech_a)

    # A plain deactivation keeps their history.
    await _handle(world, _changed(org.tenant, org.tech_b, "admin"))
    assert (await _counts(world, org, org.tech_b))[0] > 0

    # An erasure takes it; twice is the same; nobody else's is touched, in either tenant.
    await _handle(world, _changed(org.tenant, org.tech_b, "erasure"))
    await _handle(world, _changed(org.tenant, org.tech_b, "erasure"))
    assert await _counts(world, org, org.tech_b) == (0, 0)
    assert await _counts(world, org, org.tech_a) == before_a
    rule = (await world.call("GET", "/notifications/rules", org, org.admin)).json()
    after = next(r for r in rule if r["event_code"] == "incident.created")
    assert after["user_ids"] == [str(org.tech_a)]
    # Another tenant's same-named event does nothing here (RLS: the session's tenant only).
    await _handle(world, _changed(other.tenant, org.tech_a, "erasure"))
    assert await _counts(world, org, org.tech_a) == before_a
