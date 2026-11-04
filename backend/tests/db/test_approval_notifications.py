"""Approval notifications with each approver's own link (WP-030 s3; REQ-SR-025, -026; lane B's
review: one link per recipient, nothing new on a retry or a redelivery, none in-app, no token
in the outbox or the logs).
"""

import json
import logging
import re
import uuid
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.notifications.service.engine import dispatch
from app.shared.events import EventEnvelope
from tests.db.test_approvals_api import manager_of
from tests.db.test_incidents_api import Org, World, world
from tests.db.test_notifications_api import NO_MAIL, run_engine
from tests.db.test_service_requests_api import an_item, raise_request

pytestmark = pytest.mark.db

__all__ = ["world"]  # the fixture, re-used

LINK = re.compile(r"requests/approval-link#([A-Za-z0-9_-]{43})")


async def two_approvers(world: World, org: Org) -> dict[str, Any]:
    item = await an_item(
        world,
        org,
        approval={
            "approvers": [
                {"kind": "person", "person_id": str(org.tech_a)},
                {"kind": "person", "person_id": str(org.tech_b)},
            ]
        },
    )
    made = await raise_request(
        world, org, org.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def rows(world: World, org: Org, record: dict[str, Any]) -> list[Any]:
    return await world.sql(
        "SELECT event_code, user_id, channel, text_body FROM notification_deliveries"
        " WHERE tenant_id = $1 AND record_id = $2 ORDER BY created_at",
        org.tenant,
        uuid.UUID(record["id"]),
    )


async def test_each_approver_gets_their_own_link_by_email_and_none_in_app(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    a = world.a
    caplog.set_level(logging.DEBUG)
    record = await two_approvers(world, a)
    await run_engine(world, a)
    found = [r for r in await rows(world, a, record) if r["event_code"].endswith("requested")]
    mails = {r["user_id"]: r["text_body"] for r in found if r["channel"] == "email"}
    assert set(mails) == {a.tech_a, a.tech_b}
    tokens = {user: LINK.findall(body) for user, body in mails.items()}
    assert all(len(t) == 1 for t in tokens.values())
    assert tokens[a.tech_a] != tokens[a.tech_b]  # one link per recipient, never shared
    links = await world.sql("SELECT recipient_id FROM action_links WHERE tenant_id = $1", a.tenant)
    assert sorted(r["recipient_id"] for r in links) == sorted([a.tech_a, a.tech_b])
    in_app = await world.sql(
        "SELECT title, link FROM notifications WHERE tenant_id = $1 AND user_id = ANY($2::uuid[])",
        a.tenant,
        [a.tech_a, a.tech_b],
    )
    assert in_app
    assert not any("approval-link" in f"{r['title']} {r['link']}" for r in in_app)
    secrets = [t[0] for t in tokens.values()]
    outbox = await world.sql("SELECT envelope FROM outbox_events WHERE tenant_id = $1", a.tenant)
    assert not any(s in str(r["envelope"]) for r in outbox for s in secrets)
    assert not any(s in caplog.text for s in secrets)


async def test_a_redelivered_event_mints_no_second_link(world: World) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    record = (
        await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
        )
    ).json()
    await run_engine(world, a)
    before = await world.sql(
        "SELECT count(*) AS n FROM action_links WHERE tenant_id = $1", a.tenant
    )
    opened = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'work_items.approval.changed' ORDER BY id",
        a.tenant,
    )
    envelope = EventEnvelope.model_validate(json.loads(opened[0]["envelope"]))
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            await dispatch(session, NO_MAIL, envelope)  # the same event again
    finally:
        await database.dispose()
    after = await world.sql("SELECT count(*) AS n FROM action_links WHERE tenant_id = $1", a.tenant)
    assert after[0]["n"] == before[0]["n"] == 1
    emails = [
        r
        for r in await rows(world, a, record)
        if r["channel"] == "email" and r["event_code"].endswith("requested")
    ]
    assert len(emails) == 1


async def test_a_fallback_approval_tells_the_administrators_in_app_without_a_link(
    world: World,
) -> None:
    a = world.a
    item = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    record = (
        await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
        )
    ).json()  # the requester has no manager: the administrators hold it
    await run_engine(world, a)
    found = [r for r in await rows(world, a, record) if r["event_code"].endswith("fallback")]
    assert found
    assert {r["channel"] for r in found} == {"in_app"}
    assert a.admin in {r["user_id"] for r in found}
    links = await world.sql("SELECT count(*) AS n FROM action_links WHERE tenant_id = $1", a.tenant)
    assert links[0]["n"] == 0
