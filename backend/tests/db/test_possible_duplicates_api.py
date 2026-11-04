"""Possible duplicates over HTTP (WP-038, REQ-INC-022, D-134), with the recorded fake.

Same world as test_incidents_api.py (two orgs; tech_a in GA at S1, tech_b in GB at S2).

- AI off: subject similarity in PostgreSQL (pg_trgm), and no AI call at all.
- AI on: by meaning through the gateway (embeddings, the fake's word-overlap vectors), logged.
- Only open incidents the person may see (AC3); resolved and closed ones never.
- The same requester's incidents from the last hour count extra; creating needs the permission.
"""

import json
import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.ai.service.embeddings import on_work_item_changed
from app.modules.work_items.service.ai_sources import incident_texts
from tests.db.test_ai_summaries_api import ai_settings
from tests.db.test_conversation_api import events_of, say
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, world

__all__ = ["world"]  # the fixture, re-used

MAIL = "Outlook keeps asking for the password since Monday"


async def duplicates(world: World, org: Org, user: Any, **query: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    response = await world.call("GET", f"{BASE}/possible-duplicates", org, user, params=query)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def ai_calls(world: World, org: Org) -> int:
    rows = await world.sql(
        "SELECT count(*) AS n FROM ai_calls WHERE tenant_id = $1 AND feature = $2",
        org.tenant,
        "possible_duplicates",
    )
    return int(rows[0]["n"])


async def index_all(world: World, org: Org) -> None:
    """Run the indexing consumer over this org's created incidents (the worker's job)."""
    database = world.app.state.db
    for envelope in await events_of(world, "work_item"):
        if (
            envelope.tenant_id != org.tenant
            or envelope.event_type != "work_items.work_item.created"
        ):
            continue
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            await on_work_item_changed(envelope, session)


async def test_req_inc_022_ai_off_finds_by_subject_with_no_ai_call(world: World) -> None:
    a = world.a
    await ai_settings(world, a, disabled_features=["possible_duplicates"])
    same = await world.create(a, a.tech_a, group_id=str(a.ga), subject=MAIL)
    await world.create(a, a.tech_a, group_id=str(a.ga), subject="Printer on floor 3 jams")
    found = await duplicates(world, a, a.tech_a, title="Outlook asks for the password")
    assert found["method"] == "text"
    assert [d["item"]["id"] for d in found["items"]] == [same["id"]]
    assert found["items"][0]["reasons"] == ["similar_subject"]
    assert await ai_calls(world, a) == 0


async def test_req_inc_022_ai_on_finds_by_meaning_logged(world: World) -> None:
    a = world.a
    same = await world.create(a, a.tech_a, group_id=str(a.ga), subject=MAIL)
    await world.create(a, a.tech_a, group_id=str(a.ga), subject="Printer on floor 3 jams")
    await index_all(world, a)
    found = await duplicates(
        world, a, a.tech_a, title="Outlook keeps asking for the password again"
    )
    assert found["method"] == "meaning"
    assert [d["item"]["id"] for d in found["items"]] == [same["id"]]
    assert found["items"][0]["reasons"] == ["similar_meaning"]
    assert await ai_calls(world, a) == 1


async def test_req_inc_022_ac3_only_open_incidents_you_may_see(world: World) -> None:
    a = world.a
    await ai_settings(world, a, disabled_features=["possible_duplicates"])
    visible = await world.create(a, a.tech_a, group_id=str(a.ga), subject=MAIL)
    hidden = await world.create(
        a, a.admin, group_id=str(a.gb), subject=MAIL, requester_id=str(a.requester2)
    )
    resolved = await world.create(a, a.tech_a, group_id=str(a.ga), subject=MAIL)
    moved = await world.act(a, a.tech_a, await world.fresh(a, resolved), "resolve")
    assert moved.status_code == 200, moved.text
    found = {d["item"]["id"] for d in (await duplicates(world, a, a.tech_a, title=MAIL))["items"]}
    assert visible["id"] in found
    assert not {hidden["id"], resolved["id"]} & found
    other = await duplicates(world, world.b, world.b.admin, title=MAIL)  # another tenant
    assert other["items"] == []


async def test_req_inc_022_same_requester_within_the_hour_counts_and_needs_create(
    world: World,
) -> None:
    a = world.a
    await ai_settings(world, a, disabled_features=["possible_duplicates"])
    recent = await world.create(a, a.tech_a, group_id=str(a.ga), subject="Laptop will not start")
    found = await duplicates(
        world, a, a.tech_a, title="Badge reader broken", requester_id=str(a.requester)
    )
    assert [(d["item"]["id"], d["reasons"]) for d in found["items"]] == [
        (recent["id"], ["same_requester"])
    ]
    refused = await world.call(
        "GET", f"{BASE}/possible-duplicates", a, a.requester, params={"title": MAIL}
    )
    assert refused.status_code == 403
    assert CONSOLE  # console headers are only needed for writes


async def vectors(world: World, org: Org) -> int:
    rows = await world.sql(
        "SELECT count(*) AS n FROM ai_embeddings WHERE tenant_id = $1", org.tenant
    )
    return int(rows[0]["n"])


async def test_indexing_only_while_ai_is_on_and_deletion_forgets(world: World) -> None:
    a = world.a
    await ai_settings(world, a, disabled_features=["possible_duplicates"])
    await world.create(a, a.tech_a, group_id=str(a.ga), subject=MAIL)
    await index_all(world, a)
    assert await vectors(world, a) == 0  # AI off: no model sees the text (D-134)
    await ai_settings(world, a, disabled_features=[])
    item = await world.create(a, a.tech_a, group_id=str(a.ga), subject="VPN drops every hour")
    await index_all(world, a)
    assert await vectors(world, a) == 2  # both, now that it is on
    deleted = await world.call(
        "DELETE",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{(await world.fresh(a, item))["version"]}"', **CONSOLE},
    )
    assert deleted.status_code in {200, 204}, deleted.text
    database = world.app.state.db
    (gone,) = [
        e
        for e in await events_of(world, "work_item")
        if e.event_type == "work_items.work_item.deleted"
        and e.payload["work_item_id"] == item["id"]
    ]
    async with database.tenant_session(TenantContext(a.tenant)) as session:
        await on_work_item_changed(gone, session)
    assert await vectors(world, a) == 1


async def test_switching_off_deletes_the_vectors_audited(world: World) -> None:
    a = world.a
    await world.create(a, a.tech_a, group_id=str(a.ga), subject=MAIL)
    await index_all(world, a)
    assert await vectors(world, a) == 1
    await ai_settings(world, a, disabled_features=["possible_duplicates"])
    assert await vectors(world, a) == 0  # AI off keeps no AI data (D-134)
    audited = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a.tenant,
        "ai.embeddings_purged",
    )
    assert [json.loads(r["details"]) for r in audited] == [{"embeddings": 1}]


async def test_visibility_is_checked_at_query_time_after_a_scope_change(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga), subject=MAIL)
    await index_all(world, a)
    query = {"title": "Outlook keeps asking for the password again"}
    assert [d["item"]["id"] for d in (await duplicates(world, a, a.tech_a, **query))["items"]] == [
        item["id"]
    ]
    moved = await world.assign(
        a, a.admin, await world.fresh(a, item), group=a.gb, reason_code="needs_expertise"
    )
    assert moved.status_code == 200, moved.text
    # Still indexed, but tech_a (GA) may no longer open it: never offered.
    assert await vectors(world, a) == 1
    assert (await duplicates(world, a, a.tech_a, **query))["items"] == []


async def test_embedded_text_is_the_subject_and_description_never_notes(world: World) -> None:
    a = world.a
    item = await world.create(
        a, a.tech_a, group_id=str(a.ga), subject=MAIL, description="<p>Since the update.</p>"
    )
    note = await say(world, a, a.tech_a, item, body="<p>secret-note-words</p>")
    assert note.status_code == 201, note.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        texts = await incident_texts(session, [uuid.UUID(item["id"])])
    assert texts == {uuid.UUID(item["id"]): [f"{MAIL}\nSince the update."]}
