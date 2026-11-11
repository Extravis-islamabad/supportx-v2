"""Conversation summaries over HTTP (WP-038, REQ-INC-137), with the recorded fake.

Same world as test_incidents_api.py (two orgs; tech_a in GA at S1, tech_b in GB at S2).

- A technician who may open the incident gets a summary through the gateway (logged). Someone who
  may not open it gets 404, in the same tenant (D-052) and across tenants.
- Private notes are read only when the admin chose them; the two levels never mix.
- The prompt holds display names, never e-mail addresses.
- A newer reply makes the summary stale, announced on the record's channel.
- AI off: refused, nothing summarised. Another tenant cannot read the rows (RLS).
- Erasing a person deletes the tenant's summaries, audited.
"""

import json
import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.ai.infra.models import AiSummary
from app.modules.ai.service.erasure import on_status_changed
from app.modules.ai.service.realtime import ROUTES as AI_ROUTES
from app.modules.ai.service.summaries import on_conversation_changed
from app.shared.events import EventEnvelope
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_conversation_api import events_of, say
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

PUBLIC_REPLY = "<p>Outlook keeps asking for the password since Monday.</p>"
PRIVATE_NOTE = "<p>Suspect the expired certificate on mail-gw-2.</p>"


def summary_path(item: dict[str, Any]) -> str:
    return f"/ai/summaries/incident/{item['id']}"


async def ai_settings(world: World, org: Org, **values: Any) -> None:  # noqa: ANN401 - JSON
    current = await world.call("GET", "/ai/settings", org, org.admin)
    assert current.status_code == 200, current.text
    changed = await world.call(
        "PATCH",
        "/ai/settings",
        org,
        org.admin,
        json=values,
        headers={"If-Match": current.headers["etag"], **CONSOLE},
    )
    assert changed.status_code == 200, changed.text


async def masked_inputs(world: World, org: Org) -> list[str]:
    rows = await world.sql(
        "SELECT masked_input FROM ai_calls WHERE tenant_id = $1 AND feature = $2"
        " ORDER BY created_at",
        org.tenant,
        "conversation_summary",
    )
    return [str(r["masked_input"]) for r in rows]


async def incident_with_talk(world: World, org: Org) -> dict[str, Any]:
    item = await world.create(
        org, org.tech_a, group_id=str(org.ga), description="<p>Mail asks for a password.</p>"
    )
    reply = await say(world, org, org.tech_a, item, kind="reply", body=PUBLIC_REPLY)
    assert reply.status_code == 201, reply.text
    note = await say(world, org, org.tech_a, item, body=PRIVATE_NOTE)  # notes start private
    assert note.status_code == 201, note.text
    return item


async def test_req_inc_137_a_summary_through_the_gateway_without_private_notes(
    world: World,
) -> None:
    a = world.a
    item = await incident_with_talk(world, a)
    empty = await world.call("GET", summary_path(item), a, a.tech_a)
    assert empty.status_code == 200, empty.text
    assert empty.json()["summary"] is None
    made = await world.call("POST", f"{summary_path(item)}/refresh", a, a.tech_a, headers=CONSOLE)
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["summary"].startswith("[conversation_summary]")
    assert (body["stale"], body["includes_private"], body["model"]) == (False, False, "fake")
    again = await world.call("GET", summary_path(item), a, a.tech_a)
    assert again.json()["summary"] == body["summary"]
    (sent,) = await masked_inputs(world, a)
    assert "Outlook keeps asking" in sent
    assert "expired certificate" not in sent  # private notes only when the admin chose them
    assert "@" not in sent  # display names only, never e-mail addresses


async def test_req_inc_137_private_notes_only_when_chosen_and_levels_never_mix(
    world: World,
) -> None:
    a = world.a
    item = await incident_with_talk(world, a)
    public = await world.call("POST", f"{summary_path(item)}/refresh", a, a.tech_a, headers=CONSOLE)
    assert public.status_code == 200, public.text
    await ai_settings(
        world, a, summary_sources=["description", "replies", "public_notes", "private_notes"]
    )
    # The level with private notes has no summary yet: the public one is never shown for it.
    assert (await world.call("GET", summary_path(item), a, a.tech_a)).json()["summary"] is None
    private = await world.call(
        "POST", f"{summary_path(item)}/refresh", a, a.tech_a, headers=CONSOLE
    )
    assert private.status_code == 200, private.text
    assert private.json()["includes_private"] is True
    assert "expired certificate" in (await masked_inputs(world, a))[-1]
    unknown = await world.call(
        "PATCH",
        "/ai/settings",
        a,
        a.admin,
        json={"summary_sources": ["emails"]},
        headers={"If-Match": '"999"', **CONSOLE},
    )
    assert unknown.status_code == 422


async def test_d052_not_visible_means_404_in_the_tenant_and_across(world: World) -> None:
    a, b = world.a, world.b
    item = await incident_with_talk(world, a)
    for org, user in ((a, a.tech_b), (b, b.admin)):  # tech_b is in GB at S2; b is another tenant
        assert problem(await world.call("GET", summary_path(item), org, user))[0] == 404
        refused = await world.call(
            "POST", f"{summary_path(item)}/refresh", org, user, headers=CONSOLE
        )
        assert refused.status_code == 404, refused.text
    assert await masked_inputs(world, a) == []


async def test_a_newer_entry_makes_the_summary_stale_live(world: World) -> None:
    a = world.a
    item = await incident_with_talk(world, a)
    assert (
        await world.call("POST", f"{summary_path(item)}/refresh", a, a.tech_a, headers=CONSOLE)
    ).status_code == 200
    later = await say(world, a, a.tech_a, item, kind="reply", body="<p>Fixed the certificate.</p>")
    assert later.status_code == 201, later.text
    added = [
        e
        for e in await events_of(world, "work_item_conversation")
        if e.event_type == "work_items.conversation.added"
        and e.payload["work_item_id"] == item["id"]
    ][-1]
    database = world.app.state.db
    async with database.tenant_session(TenantContext(a.tenant)) as session:
        await on_conversation_changed(added, session)
    stale = await world.call("GET", summary_path(item), a, a.tech_a)
    assert stale.json()["stale"] is True
    (changed,) = [
        e
        for e in await events_of(world, "ai_summary")
        if e.payload["record_id"] == item["id"] and e.payload["stale"]
    ]
    route = next(r for r in AI_ROUTES if changed.event_type in r.event_types)
    async with database.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(changed, session)
    (publication,) = effects.publications
    assert publication.channel.name == f"t:{a.tenant}:wi:{item['id']}"
    assert (publication.type, publication.fields) == ("ai.summary_changed", ("stale",))
    # Refresh makes it current again.
    fresh = await world.call("POST", f"{summary_path(item)}/refresh", a, a.tech_a, headers=CONSOLE)
    assert fresh.json()["stale"] is False


async def test_ai_off_refuses_and_another_tenant_cannot_read_the_rows(world: World) -> None:
    a, b = world.a, world.b
    item = await incident_with_talk(world, a)
    assert (
        await world.call("POST", f"{summary_path(item)}/refresh", a, a.tech_a, headers=CONSOLE)
    ).status_code == 200
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        from sqlalchemy import func, select, update  # noqa: PLC0415 - this test only

        assert await session.scalar(select(func.count()).select_from(AiSummary)) == 0
        changed = await session.execute(update(AiSummary).values(text="tampered"))
        assert getattr(changed, "rowcount", 0) == 0
    await ai_settings(world, a, disabled_features=["conversation_summary"])
    off = await world.call("POST", f"{summary_path(item)}/refresh", a, a.tech_a, headers=CONSOLE)
    assert problem(off) == (403, "ai_feature_off")


async def test_erasing_a_person_deletes_the_summaries_audited(world: World) -> None:
    a = world.a
    item = await incident_with_talk(world, a)
    assert (
        await world.call("POST", f"{summary_path(item)}/refresh", a, a.tech_a, headers=CONSOLE)
    ).status_code == 200
    envelope = EventEnvelope.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "identity_access.user.status_changed",
            "schema_version": 1,
            "tenant_id": str(a.tenant),
            "aggregate_type": "user",
            "aggregate_id": str(a.requester),
            "occurred_at": "2026-11-04T00:00:00Z",
            "actor": {"type": "system", "id": "erasure"},
            "payload": {"user_id": str(a.requester), "reason": "erasure"},
        }
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await on_status_changed(envelope, session)
    rows = await world.sql("SELECT count(*) AS n FROM ai_summaries WHERE tenant_id = $1", a.tenant)
    assert rows[0]["n"] == 0
    audited = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a.tenant,
        "ai.summaries_erased",
    )
    assert [json.loads(r["details"]) for r in audited] == [{"summaries": 1}]
    assert BASE  # the incidents API base, kept for readers of this file
