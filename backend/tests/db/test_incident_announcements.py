"""Announcing from an incident (WP-046b S4, REQ-INC-129; lane B's and lane C's conditions).

The announcements module makes the announcement with the actor's own rights and audience
rules; work_items keeps only the link, which grants nothing. Lane C's tests: another tenant's
incident cannot be linked; an actor without announcements.manage is refused with no link row
written; a retried request (same Idempotency-Key) makes one announcement; announcements never
imports work_items (pyproject's import-linter contract).
"""

import dataclasses
import uuid
from typing import Any

import pytest

from app.core.errors import PermissionDenied
from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.work_items.service import incident_announcements as service
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, world  # noqa: F401 - fixture

TEXT = {
    "title": "E-mail is down for the Riyadh site",
    "body": "We are working on it. No need to report it again.",
    "audience": "everyone",
}


async def _announce(
    world: World,  # noqa: F811
    org: Org,
    user: uuid.UUID,
    item: dict[str, Any],
    key: str,
    **extra: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - an httpx response
    return await world.call(
        "POST",
        f"{BASE}/{item['id']}/announcements",
        org,
        user,
        json={**TEXT, **extra},
        headers={"Idempotency-Key": key, **CONSOLE},
    )


async def _links(world: World, org: Org, item: dict[str, Any]) -> list[Any]:  # noqa: F811
    return await world.sql(
        "SELECT announcement_id FROM work_item_announcements WHERE tenant_id = $1"
        " AND work_item_id = $2 AND deleted_at IS NULL",
        org.tenant,
        uuid.UUID(item["id"]),
    )


async def test_announce_link_list_and_end_once_per_dialog(world: World) -> None:  # noqa: F811
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    key = str(uuid.uuid4())
    made = await _announce(world, a, a.admin, item, key)
    assert made.status_code == 201, made.text
    assert made.json()["status"] == "published"  # the admin may publish
    again = await _announce(world, a, a.admin, item, key)  # a retry or a double click
    assert again.status_code == 201, again.text
    assert again.json()["id"] == made.json()["id"]
    assert len(await _links(world, a, item)) == 1
    listed = await world.call("GET", f"{BASE}/{item['id']}/announcements", a, a.admin)
    assert [x["id"] for x in listed.json()] == [made.json()["id"]]
    # The incident's history names the link by the announcement's number, nothing more.
    entries = await world.history(a, item)
    named = [c for e in entries for c in e["changes"] if c["field"] == "announcements"]
    assert [c["new"] for c in named] == [made.json()["display_id"]]
    # Requesters see it in the portal, as any live announcement (AC3).
    feed = await world.call("GET", "/announcements/feed", a, a.requester)
    assert made.json()["id"] in str(feed.json())
    # Ending it from the incident: archived through announcements; the link stays.
    ended = await world.call(
        "POST",
        f"{BASE}/{item['id']}/announcements/{made.json()['id']}/end",
        a,
        a.admin,
        json={"reason": "Mail is back"},
        headers=CONSOLE,
    )
    assert ended.status_code == 200, ended.text
    assert ended.json()["status"] == "archived"
    assert len(await _links(world, a, item)) == 1
    # Another announcement can't be ended through this incident.
    other = await world.create(a, a.admin, group_id=str(a.ga))
    stranger = await world.call(
        "POST",
        f"{BASE}/{other['id']}/announcements/{made.json()['id']}/end",
        a,
        a.admin,
        json={},
        headers=CONSOLE,
    )
    assert stranger.status_code == 404, stranger.text


async def test_a_technician_leaves_a_draft_for_someone_who_may_publish(world: World) -> None:  # noqa: F811
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    made = await _announce(world, a, a.tech_a, item, str(uuid.uuid4()))
    assert made.status_code == 201, made.text
    assert made.json()["status"] == "draft"  # technicians may not publish by default


async def test_another_tenant_s_incident_cannot_be_linked(world: World) -> None:  # noqa: F811
    a, b = world.a, world.b
    theirs = await world.create(b, b.admin)
    refused = await _announce(world, a, a.admin, theirs, str(uuid.uuid4()))
    assert refused.status_code == 404, refused.text
    rows = await world.sql(
        "SELECT 1 FROM work_item_announcements WHERE work_item_id = $1", uuid.UUID(theirs["id"])
    )
    assert rows == []


async def test_without_announcements_manage_nothing_is_written(
    world: World,  # noqa: F811
    app_db: Any,  # noqa: ANN401 - the app's Database fixture
) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    async with app_db.tenant_session(TenantContext(a.tenant)) as session:
        full = await subject_for(session, a.tenant, a.tech_a)
        limited = dataclasses.replace(
            full, grants={k: v for k, v in full.grants.items() if k != "announcements.manage"}
        )
        with pytest.raises(PermissionDenied):
            await service.announce(
                session,
                limited,
                uuid.UUID(item["id"]),
                values=TEXT,
                publish=True,
                source="ui",
                holders=world.app.state.policy,  # the running policy service
            )
    assert await _links(world, a, item) == []
