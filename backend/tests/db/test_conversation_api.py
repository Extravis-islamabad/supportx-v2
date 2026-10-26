"""Conversation, notes, followers, counters and reply templates over HTTP (WP-020b).

Same world as test_incidents_api.py (two orgs, sites S1/S2, groups GA/GB; tech_a in GA at S1,
tech_b in GB at S2, tech_c in GA and GB). Test names cite parity file 01 criteria and D-068.
"""

import json
import uuid
from typing import Any

import httpx
from sqlalchemy import text

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.work_items.service.realtime import ROUTES
from app.shared.events import EventEnvelope
from tests.db.test_incidents_api import (
    BASE,
    CONSOLE,
    Org,
    World,
    field_codes,
    problem,
    states,
    world,
)

__all__ = ["world"]  # the fixture, re-used

MAIL = "<p>Mail is down again</p>"


async def say(
    world: World,
    org: Org,
    user: uuid.UUID,
    item: dict[str, Any],
    *,
    kind: str = "note",
    body: str = MAIL,
    key: str | None = None,
    **extra: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "POST",
        f"{BASE}/{item['id']}/conversation",
        org,
        user,
        json={"kind": kind, "body": body, **extra},
        headers={"Idempotency-Key": key or str(uuid.uuid4()), **CONSOLE},
    )


async def timeline(
    world: World, org: Org, user: uuid.UUID, item: dict[str, Any], query: str = ""
) -> httpx.Response:
    return await world.call("GET", f"{BASE}/{item['id']}/conversation{query}", org, user)


async def followers(world: World, org: Org, user: uuid.UUID, item: dict[str, Any]) -> list[Any]:
    found = await world.call("GET", f"{BASE}/{item['id']}/followers", org, user)
    assert found.status_code == 200, found.text
    return list(found.json()["items"])


async def follow(
    world: World, org: Org, user: uuid.UUID, item: dict[str, Any], who: uuid.UUID, *, on: bool
) -> httpx.Response:
    return await world.call(
        "PUT" if on else "DELETE", f"{BASE}/{item['id']}/followers/{who}", org, user
    )


async def events_of(world: World, aggregate_type: str) -> list[EventEnvelope]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE envelope->>'aggregate_type' = $1 ORDER BY id",
        aggregate_type,
    )
    return [EventEnvelope.model_validate(json.loads(r["envelope"])) for r in rows]


def mention(user: uuid.UUID, label: str) -> str:
    return f'<span data-type="mention" data-id="{user}" data-label="{label}">@{label}</span>'


# --- the timeline and notes -----------------------------------------------------------------------


async def test_req_inc_057_ac1_ac2_timeline_order_markers_and_filters(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    note = await say(world, a, a.tech_a, item, body="<p>checked logs</p>")
    assert note.status_code == 201, note.text
    reply = await say(world, a, a.tech_a, item, kind="reply", body="<p>We are on it</p>")
    assert reply.status_code == 201, reply.text
    public = await say(world, a, a.tech_a, item, body="<p>update</p>", visibility="public")
    found = (await timeline(world, a, a.tech_a, item)).json()
    entries = found["items"]
    assert [(e["kind"], e["visibility"]) for e in entries] == [
        ("note", "private"),  # D-077: notes start private
        ("reply", "public"),
        ("note", "public"),
    ]
    assert entries[0]["id"] == note.json()["entry"]["id"]
    assert entries[2]["id"] == public.json()["entry"]["id"]
    assert str(a.tech_a) in found["people"]  # authors are named, never shown as IDs
    only_notes = (await timeline(world, a, a.tech_a, item, "?kind=note")).json()["items"]
    assert {e["kind"] for e in only_notes} == {"note"}
    only_replies = (await timeline(world, a, a.tech_a, item, "?kind=reply")).json()["items"]
    assert {e["kind"] for e in only_replies} == {"reply"}
    record = (await world.get(a, a.tech_a, item)).json()
    assert record["conversation_count"] == 3


async def test_req_inc_058_reply_saved_not_sent_without_email_channel(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    reply = await say(world, a, a.tech_a, item, kind="reply", body="<p>Hello</p>")
    assert reply.status_code == 201, reply.text
    entry = reply.json()["entry"]
    # Never silent (WP-024 sends): saved, marked not sent, with the reason.
    assert entry["delivery_state"] == "not_sent"
    assert entry["delivery_reason"] == "email_channel_not_configured"
    requester = (await world.get(a, a.admin, item)).json()["people"][str(a.requester)]
    assert entry["recipients"] == {"to": [requester["email"].lower()], "cc": []}
    forward = await say(world, a, a.tech_a, item, kind="reply", reply_mode="forward")
    assert field_codes(forward) == {"to": "required"}
    bad = await say(
        world, a, a.tech_a, item, kind="reply", to=["not an address"], cc=["x@example.com"]
    )
    assert field_codes(bad) == {"to": "invalid_email"}
    all_mode = await say(
        world,
        a,
        a.tech_a,
        item,
        kind="reply",
        reply_mode="reply_all",
        to=["A@Example.com"],
        cc=["a@example.com", "b@example.com"],
    )
    assert all_mode.json()["entry"]["recipients"] == {
        "to": ["a@example.com"],
        "cc": ["b@example.com"],
    }
    private_reply = await say(world, a, a.tech_a, item, kind="reply", visibility="private")
    assert field_codes(private_reply) == {"visibility": "invalid_choice"}


async def test_req_inc_061_private_by_default_and_requester_cannot_read(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    await say(world, a, a.tech_a, item)
    # AC1: the requester has no staff API access at all (the portal comes with WP-028).
    assert (await timeline(world, a, a.requester, item)).status_code == 403
    assert (await say(world, a, a.requester, item)).status_code == 403
    # Someone outside the record's reach cannot read it either (404, no existence leak).
    assert problem(await timeline(world, a, a.tech_b, item)) == (404, "work_item_not_found")


async def test_req_inc_061_ac3_making_public_is_recorded_and_audited(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    entry = (await say(world, a, a.tech_a, item)).json()["entry"]
    path = f"{BASE}/{item['id']}/conversation/{entry['id']}"
    stale = await world.call(
        "PATCH",
        path,
        a,
        a.tech_a,
        json={"visibility": "public"},
        headers={"If-Match": '"9"', **CONSOLE},
    )
    assert problem(stale) == (409, "version_conflict")
    made = await world.call(
        "PATCH",
        path,
        a,
        a.tech_a,
        json={"visibility": "public"},
        headers={"If-Match": f'"{entry["version"]}"', **CONSOLE},
    )
    assert made.status_code == 200, made.text
    assert made.json()["visibility"] == "public"
    changes = [c for e in await world.history(a, item) for c in e["changes"]]
    assert {"field": "note_visibility", "old": "private", "new": "public"} in changes
    audited = await world.sql(
        "SELECT action FROM audit_entries"
        " WHERE tenant_id = $1 AND action = $2 AND outcome = 'done'",
        a.tenant,
        "incident.note_visibility_changed",
    )
    assert len(audited) == 1
    reply = (await say(world, a, a.tech_a, item, kind="reply")).json()["entry"]
    replies = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}/conversation/{reply['id']}",
        a,
        a.tech_a,
        json={"visibility": "private"},
        headers={"If-Match": f'"{reply["version"]}"', **CONSOLE},
    )
    assert field_codes(replies) == {"visibility": "replies_are_public"}


async def test_req_inc_064_bodies_are_sanitised_with_the_editor_allow_list(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    body = (
        '<h2 data-align="center">Steps</h2><p data-indent="2" style="color:red">'
        '<span data-color="red">red</span> <mark data-color="yellow">hi</mark>'
        '<font face="Comic Sans">x</font></p><script>alert(1)</script><img src=x onerror=1>'
    )
    saved = (await say(world, a, a.tech_a, item, body=body)).json()["entry"]["body"]
    assert saved == (
        '<h2 data-align="center">Steps</h2><p data-indent="2"><span data-color="red">red</span>'
        ' <mark data-color="yellow">hi</mark>x</p>'
    )
    blank = await say(world, a, a.tech_a, item, body="<p> </p><script>x</script>")
    assert field_codes(blank) == {"body": "required"}


async def test_req_wi_008_retried_note_is_saved_once(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    first = await say(world, a, a.tech_a, item, key="same-key")
    again = await say(world, a, a.tech_a, item, key="same-key")
    assert first.status_code == again.status_code == 201
    assert first.json()["entry"]["id"] == again.json()["entry"]["id"]
    assert len((await timeline(world, a, a.tech_a, item)).json()["items"]) == 1


# --- first response -------------------------------------------------------------------------------


async def test_req_inc_065_first_public_reply_stamps_once_private_note_never(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    await say(world, a, a.tech_a, item)  # private note: not a response (AC2)
    assert (await world.fresh(a, item))["first_responded_at"] is None
    first = (await say(world, a, a.tech_a, item, kind="reply")).json()["entry"]
    assert first["first_response"] is True
    stamped = (await world.fresh(a, item))["first_responded_at"]
    assert stamped is not None
    later = (await say(world, a, a.tech_a, item, visibility="public")).json()["entry"]
    assert later["first_response"] is False
    assert (await world.fresh(a, item))["first_responded_at"] == stamped  # AC3
    changes = [c for e in await world.history(a, item) for c in e["changes"]]
    assert [c["field"] for c in changes].count("first_responded_at") == 1


async def test_req_inc_065_admins_choose_what_counts(world: World) -> None:
    a = world.a
    settings = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
    assert settings["first_response_on"] == ["reply", "public_note"]
    changed = await world.call(
        "PATCH",
        f"{BASE}/settings",
        a,
        a.admin,
        json={"first_response_on": ["private_note"]},
        headers={"If-Match": f'"{settings["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    await say(world, a, a.tech_a, item, kind="reply")
    assert (await world.fresh(a, item))["first_responded_at"] is None
    await say(world, a, a.tech_a, item)
    assert (await world.fresh(a, item))["first_responded_at"] is not None


# --- followers and the hand-over (D-068, REQ-INC-151) ---------------------------------------------


async def test_req_inc_151_ac1_ac2_handed_over_keeps_following_with_read_and_notes(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    warned = await world.assign(a, a.tech_a, item, group=a.gb, reason_code="wrong_group")
    assert problem(warned) == (409, "would_lose_access")
    assert warned.json()["params"]["keep_following"] is True  # the dialog's default
    handed = await world.assign(
        a, a.tech_a, item, group=a.gb, reason_code="wrong_group", confirm_lose_access=True
    )
    assert handed.status_code == 200, handed.text
    assert handed.json()["visible"] is True
    assert handed.json()["following"] is True
    # AC1: still opens it, and it is in their list.
    seen = await world.get(a, a.tech_a, item)
    assert seen.status_code == 200
    listed = await world.call("GET", BASE, a, a.tech_a)
    assert item["id"] in {r["id"] for r in listed.json()["items"]}
    # AC2: may add private notes, nothing else.
    current = seen.json()
    assert states(current, "operations") == {
        "edit": "out_of_scope",
        "assign": "out_of_scope",
        "take": "out_of_scope",
        "change_priority": "out_of_scope",
        "delete": "no_permission",
    }
    assert states(current, "conversation_actions") == {
        "add_note": None,
        "reply": "out_of_scope",
        "manage_followers": "out_of_scope",
    }
    assert (await say(world, a, a.tech_a, item)).status_code == 201
    assert (await say(world, a, a.tech_a, item, visibility="public")).status_code == 403
    assert (await say(world, a, a.tech_a, item, kind="reply")).status_code == 403
    assert (await world.patch(a, a.tech_a, current, subject="Changed")).status_code == 403
    assert (await world.act(a, a.tech_a, current, "start_work")).status_code == 403
    # AC4: recorded in history.
    rows = await followers(world, a, a.admin, item)
    assert [(f["user_id"], f["reason"], f["grants_access"]) for f in rows] == [
        (str(a.tech_a), "handed_over", True)
    ]
    changes = [c for e in await world.history(a, item) for c in e["changes"]]
    assert {"field": "follower_access", "old": None, "new": str(a.tech_a)} in changes


async def test_req_inc_151_ac3_without_keep_following_access_is_lost(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    handed = await world.assign(
        a,
        a.tech_a,
        item,
        group=a.gb,
        reason_code="wrong_group",
        confirm_lose_access=True,
        keep_following=False,
    )
    assert handed.json()["visible"] is False
    assert problem(await world.get(a, a.tech_a, item)) == (404, "work_item_not_found")
    assert await followers(world, a, a.admin, item) == []


async def test_req_inc_151_ac4_follow_removed_by_self_or_assignee(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    handed = await world.assign(
        a,
        a.tech_a,
        item,
        group=a.gb,
        technician=a.tech_b,
        reason_code="wrong_group",
        confirm_lose_access=True,
    )
    assert handed.status_code == 200, handed.text
    # The new assignee may remove the follower; then the old technician loses sight of it.
    removed = await follow(world, a, a.tech_b, item, a.tech_a, on=False)
    assert removed.status_code == 200, removed.text
    assert problem(await world.get(a, a.tech_a, item)) == (404, "work_item_not_found")
    found = await events_of(world, "work_item_follower")
    assert [e.event_type for e in found][-1] == "work_items.follower.removed"
    # Unfollowing yourself works the same way.
    item2 = await world.create(a, a.tech_a, group_id=str(a.ga))
    await world.assign(
        a, a.tech_a, item2, group=a.gb, reason_code="wrong_group", confirm_lose_access=True
    )
    gone = await follow(world, a, a.tech_a, item2, a.tech_a, on=False)
    assert gone.status_code == 200
    assert gone.json()["items"] == []
    assert problem(await world.get(a, a.tech_a, item2)) == (404, "work_item_not_found")


async def test_req_inc_056_follow_and_add_followers_without_widening_access(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    mine = await follow(world, a, a.tech_c, item, a.tech_c, on=True)
    assert mine.status_code == 200, mine.text
    assert [(f["reason"], f["grants_access"]) for f in mine.json()["items"]] == [("self", False)]
    assert (await follow(world, a, a.tech_c, item, a.tech_c, on=True)).status_code == 200  # again
    # tech_b cannot see GA's incident: adding them is refused, never a silent grant.
    refused = await follow(world, a, a.tech_a, item, a.tech_b, on=True)
    assert field_codes(refused) == {"user_id": "cannot_see_record"}
    # tech_b may not follow what they cannot see either.
    assert problem(await follow(world, a, a.tech_b, item, a.tech_b, on=True)) == (
        404,
        "work_item_not_found",
    )
    # The lead's custom role has no manage_followers; their built-in technician scope (group)
    # does not reach GA, so they may not add people here.
    assert (await follow(world, a, a.lead, item, a.admin, on=True)).status_code == 403
    added = await follow(world, a, a.tech_c, item, a.admin, on=True)
    assert added.status_code == 200, added.text
    assert {f["user_id"] for f in added.json()["items"]} == {str(a.tech_c), str(a.admin)}
    assert [f["reason"] for f in added.json()["items"]] == ["self", "added"]
    assert (await follow(world, a, a.tech_c, item, a.admin, on=False)).status_code == 200
    record = (await world.get(a, a.tech_c, item)).json()
    assert record["following"] is True


async def test_req_inc_063_mentions_follow_only_people_who_can_see(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    body = f"<p>{mention(a.tech_c, 'Tech C')} and {mention(a.tech_b, 'Tech B')} please look</p>"
    saved = await say(world, a, a.tech_a, item, body=body)
    assert saved.status_code == 201, saved.text
    assert saved.json()["not_notified"] == [str(a.tech_b)]
    assert saved.json()["entry"]["mentioned_ids"] == [str(a.tech_c)]
    rows = await followers(world, a, a.admin, item)
    assert [(f["user_id"], f["reason"], f["grants_access"]) for f in rows] == [
        (str(a.tech_c), "mentioned", False)
    ]
    added = [e for e in await events_of(world, "work_item_conversation") if e.aggregate_id]
    assert added[-1].payload["mentioned_ids"] == [str(a.tech_c)]
    candidates = await world.call("GET", f"{BASE}/{item['id']}/mentionable", a, a.tech_a)
    sees = {row["id"]: row["can_see"] for row in candidates.json()}
    assert sees[str(a.tech_c)] is True
    assert sees[str(a.tech_b)] is False


# --- live -----------------------------------------------------------------------------------------


async def test_req_inc_057_ac3_entries_and_followers_reach_the_record_channel(
    world: World, app_db: Database
) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    await say(world, a, a.tech_a, item)
    await world.assign(
        a, a.tech_a, item, group=a.gb, reason_code="wrong_group", confirm_lose_access=True
    )
    await follow(world, a, a.admin, item, a.tech_a, on=False)
    found = [
        *await events_of(world, "work_item_conversation"),
        *await events_of(world, "work_item_follower"),
    ]

    async def route(envelope: EventEnvelope) -> tuple[set[str], list[uuid.UUID]]:
        async with app_db.tenant_session(TenantContext(a.tenant)) as session:
            for spec in ROUTES:
                if envelope.event_type in spec.event_types:
                    effects = await spec.route(envelope, session)
                    return {p.channel.name for p in effects.publications}, list(
                        effects.revoke_users
                    )
        return set(), []

    record_channel = f"t:{a.tenant}:wi:{item['id']}"
    by_type = {e.event_type: e for e in found}
    added, _ = await route(by_type["work_items.conversation.added"])
    assert added == {record_channel}
    followed, _ = await route(by_type["work_items.follower.added"])
    assert {record_channel, f"t:{a.tenant}:user:{a.tech_a}"} <= followed
    _, revoked = await route(by_type["work_items.follower.removed"])
    assert revoked == [a.tech_a]  # their record subscription ends (§8.2)
    assert "Mail" not in json.dumps([e.payload for e in found])  # IDs and codes only


async def test_req_wi_006_typing_needs_the_record(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    path = f"{BASE}/{item['id']}/typing"
    ok = await world.call("POST", path, a, a.tech_a, json={"state": "start", "kind": "reply"})
    assert ok.status_code == 204
    hidden = await world.call("POST", path, a, a.tech_b, json={"state": "start"})
    assert problem(hidden) == (404, "work_item_not_found")
    requester = await world.call("POST", path, a, a.requester, json={"state": "start"})
    assert requester.status_code == 403  # AC3: never the requester


# --- personal counters (REQ-INC-128) --------------------------------------------------------------


async def test_req_inc_128_counters_match_their_views(world: World) -> None:
    a = world.a
    mine = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    await world.create(a, a.admin, group_id=str(a.ga))  # unassigned in tech_a's group
    await say(world, a, a.admin, mine)  # someone else wrote on tech_a's incident
    counters = await world.call("GET", f"{BASE}/counters", a, a.tech_a)
    assert counters.status_code == 200, counters.text
    found = {c["counter"]: c["count"] for c in counters.json()}
    assert found == {
        "my_overdue": 0,  # due dates come with SLA (WP-025)
        "my_due_today": 0,
        "waiting_on_me": 1,
        "updated_by_others": 1,
        "unassigned_in_my_groups": 1,
    }
    for code, count in found.items():  # AC2: each counter opens a view with as many rows
        listed = await world.call("GET", f"{BASE}?view={code}", a, a.tech_a)
        assert len(listed.json()["items"]) == count, code
    await world.sql(
        "UPDATE work_items SET resolution_due_at = now() - interval '1 hour' WHERE id = $1",
        uuid.UUID(mine["id"]),
    )
    overdue = await world.call("GET", f"{BASE}/counters", a, a.tech_a)
    assert {c["counter"]: c["count"] for c in overdue.json()}["my_overdue"] == 1


# --- reply templates ------------------------------------------------------------------------------


async def test_req_inc_058_reply_templates_admin_managed_and_sanitised(world: World) -> None:
    a = world.a
    path = f"{BASE}/reply-templates"
    refused = await world.call("POST", path, a, a.tech_a, json={"name": "Hi", "body": "<p>x</p>"})
    assert refused.status_code == 403
    made = await world.call(
        "POST",
        path,
        a,
        a.admin,
        json={"name": "  Greeting ", "body": "<p>Hello<script>x</script></p>"},
    )
    assert made.status_code == 201, made.text
    template = made.json()
    assert (template["name"], template["body"]) == ("Greeting", "<p>Hello</p>")
    twice = await world.call(
        "POST", path, a, a.admin, json={"name": "greeting", "body": "<p>y</p>"}
    )
    assert field_codes(twice) == {"name": "duplicate_name"}
    listed = await world.call("GET", path, a, a.tech_a)
    assert [t["name"] for t in listed.json()] == ["Greeting"]
    changed = await world.call(
        "PUT",
        f"{path}/{template['id']}",
        a,
        a.admin,
        json={"name": "Greeting", "body": "<p>Hi</p>"},
        headers={"If-Match": f'"{template["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    gone = await world.call(
        "DELETE",
        f"{path}/{template['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{changed.json()["version"]}"'},
    )
    assert gone.status_code == 204
    assert (await world.call("GET", path, a, a.tech_a)).json() == []
    audited = await world.sql(
        "SELECT action FROM audit_entries"
        " WHERE tenant_id = $1 AND action LIKE $2 AND outcome = 'done' ORDER BY 1",
        a.tenant,
        "incident.reply_template_%",
    )
    assert [r["action"] for r in audited] == [
        "incident.reply_template_changed",
        "incident.reply_template_created",
        "incident.reply_template_deleted",
    ]
    assert (await world.call("GET", path, world.b, world.b.admin)).json() == []


# --- tenant isolation (CLAUDE.md rule a) ----------------------------------------------------------


async def test_new_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    await say(world, a, a.tech_a, item)
    await follow(world, a, a.tech_a, item, a.tech_a, on=True)
    await world.call(
        "POST", f"{BASE}/reply-templates", a, a.admin, json={"name": "T", "body": "<p>t</p>"}
    )
    tables = ("work_item_conversations", "work_item_followers", "work_item_reply_templates")
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in tables:
            rows = (await session.execute(text(f"SELECT tenant_id FROM {table}"))).all()  # noqa: S608 - fixed names
            assert rows == [], table
    # Tenant B cannot write onto tenant A's record, even naming it directly.
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        updated = await session.execute(
            text("UPDATE work_item_conversations SET body = '<p>x</p>' WHERE work_item_id = :id"),
            {"id": uuid.UUID(item["id"])},
        )
        assert updated.rowcount == 0
    other = await world.call("GET", f"{BASE}/{item['id']}/conversation", b, b.admin)
    assert problem(other) == (404, "work_item_not_found")
    rows = await world.sql(
        "SELECT count(*) AS n FROM work_item_conversations WHERE tenant_id = $1", a.tenant
    )
    assert rows[0]["n"] == 1


# --- WP-020b QA findings ------------------------------------------------------------------------


async def test_c2_invalid_addresses_are_named_without_a_second_required_error(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    forward = await say(
        world, a, a.tech_a, item, kind="reply", reply_mode="forward", to=["vendor-at-example"]
    )
    assert forward.status_code == 422, forward.text
    errors = forward.json()["errors"]
    assert [(e["field"], e["code"]) for e in errors] == [("body.to", "invalid_email")]
    assert errors[0]["params"] == {"addresses": "vendor-at-example"}


async def test_c3_unknown_mentions_become_plain_text(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    ghost = "00000000-0000-0000-0000-000000000000"
    body = f"<p>{mention(uuid.UUID(ghost), 'Ghost')} and {mention(a.tech_c, 'Tech C')}</p>"
    saved = await say(world, a, a.tech_a, item, body=body)
    assert saved.status_code == 201, saved.text
    entry = saved.json()["entry"]
    assert ghost not in entry["body"]
    assert "@Ghost" in entry["body"]  # the words stay, as plain text
    assert f'data-id="{a.tech_c}"' in entry["body"]
    assert saved.json()["not_notified"] == []  # nobody unknown is reported
    # Someone of another tenant is unknown here too.
    other = f"<p>{mention(world.b.tech_a, 'Elsewhere')}</p>"
    foreign = (await say(world, a, a.tech_a, item, body=other)).json()
    assert str(world.b.tech_a) not in foreign["entry"]["body"]
    assert foreign["not_notified"] == []
