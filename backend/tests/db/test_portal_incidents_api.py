"""The portal's incidents for requesters over HTTP (WP-028 session 1; wp-028-plan.md D1-D3).

Real PostgreSQL with RLS. A requester sees only their own incidents (requester or the person it
is for), unless they hold a wider reach (D2 default: direct reports, department); another
tenant's records never appear; out-of-reach records are 404; staff-only fields are absent from
every response, and a staff field can't be used as a filter to probe for records.
"""

import uuid
from typing import Any

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.work_items.service.notifications import SOURCE as NOTIFICATIONS
from app.modules.work_items.service.realtime import CHANNELS, PORTAL_KIND, ROUTES
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import LabelRef
from app.shared.realtime import Channel, ChannelRequest
from tests.db.test_conversation_api import events_of, say
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, role, world

__all__ = ["world"]  # the fixture, re-used

PORTAL = "/portal/incidents"
STAFF_ONLY = {"group_id", "technician_id", "priority", "status", "channel", "tags", "level"}


async def mine(world: World, org: Org, user: uuid.UUID, **params: str) -> dict[str, Any]:
    response = await world.call("GET", PORTAL, org, user, params=params)
    assert response.status_code == 200, response.text
    return dict(response.json())


def ids(page: dict[str, Any]) -> set[str]:
    return {item["id"] for item in page["items"]}


async def test_a_requester_sees_only_their_own_incidents_with_requester_fields(
    world: World,
) -> None:
    a, b = world.a, world.b
    own = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    for_me = await world.create(
        a, a.admin, requester_id=str(a.requester2), on_behalf_of_id=str(a.requester)
    )
    theirs = await world.create(a, a.admin, requester_id=str(a.requester2))
    other_tenant = await world.create(b, b.admin)

    page = await mine(world, a, a.requester)
    assert ids(page) == {own["id"], for_me["id"]}  # REQ-PRT-007 AC1
    assert theirs["id"] not in ids(page)
    assert other_tenant["id"] not in ids(page)
    row = next(i for i in page["items"] if i["id"] == own["id"])
    assert row["portal_status"] == "in_progress"  # assigned: staff wording, not the requester's
    assert row["reach"] == "own"
    assert not set(row) & STAFF_ONLY  # REQ-INC-147 AC2
    assert row["display_id"] == own["display_id"]


async def test_a_new_incident_reads_as_received(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    found = await world.call("GET", f"{PORTAL}/{item['id']}", a, a.requester)
    assert found.status_code == 200, found.text
    body = found.json()
    assert (body["portal_status"], body["subject"]) == ("received", "Mail is down")
    assert not set(body) & STAFF_ONLY


async def test_out_of_reach_and_other_tenant_records_are_not_found(world: World) -> None:
    a, b = world.a, world.b
    theirs = await world.create(a, a.admin, requester_id=str(a.requester2))
    other_tenant = await world.create(b, b.admin)
    for record in (theirs, other_tenant):
        response = await world.call("GET", f"{PORTAL}/{record['id']}", a, a.requester)
        assert problem(response) == (404, "work_item_not_found")


async def test_a_staff_field_cannot_be_used_to_probe_records(world: World) -> None:
    a = world.a
    await world.create(a, a.admin, group_id=str(a.ga))
    for params in ({"group_id": str(a.ga)}, {"sort": "priority"}):
        response = await world.call("GET", PORTAL, a, a.requester, params=params)
        assert response.status_code in {400, 422}, (params, response.text)


async def test_a_template_hides_a_field_from_requesters(world: World) -> None:
    a = world.a
    before = await world.create(a, a.admin)
    body = (await world.call("GET", f"{PORTAL}/{before['id']}", a, a.requester)).json()
    assert "category_id" in body  # shown (empty) while the template lets requesters see it
    templates = (await world.call("GET", "/incidents/templates", a, a.admin)).json()
    default = next(t for t in templates if t["is_default"])
    changed = await world.call(
        "PATCH",
        f"/incidents/templates/{default['id']}",
        a,
        a.admin,
        json={"fields": {"category_id": {"requester_can_see": False}}},
        headers={"If-Match": f'"{default["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    item = await world.create(a, a.admin)
    body = (await world.call("GET", f"{PORTAL}/{item['id']}", a, a.requester)).json()
    assert "category_id" not in body  # absent, not null
    assert "description" in body


async def test_direct_reports_need_the_permission_and_have_their_own_filter(
    world: World,
) -> None:
    a = world.a
    boss = a.requester
    await world.sql("UPDATE users SET manager_id = $1 WHERE id = $2", boss, a.requester2)
    reports_item = await world.create(a, a.admin, requester_id=str(a.requester2))
    own = await world.create(a, a.admin)

    assert ids(await mine(world, a, boss)) == {own["id"]}  # no permission yet
    granted = await role(world, a, "Team lead (portal)", [("work_items.view_reports", "all")])
    assigned = await world.call("PUT", f"/users/{boss}/roles/{granted}", a, a.admin)
    assert assigned.status_code in {200, 204}, assigned.text

    assert ids(await mine(world, a, boss)) == {own["id"], reports_item["id"]}
    only = await mine(world, a, boss, reach="reports")  # REQ-PRT-007 AC2
    assert ids(only) == {reports_item["id"]}
    assert only["items"][0]["reach"] == "reports"
    # the report does not see the manager's records the other way round
    assert reports_item["id"] in ids(await mine(world, a, a.requester2))
    assert own["id"] not in ids(await mine(world, a, a.requester2))


async def test_department_reach_covers_the_persons_own_department_only(world: World) -> None:
    a = world.a
    finance, sales = uuid.uuid4(), uuid.uuid4()
    for dept, name in ((finance, "Finance"), (sales, "Sales")):
        await world.sql(
            "INSERT INTO departments (id, tenant_id, name) VALUES ($1, $2, $3)",
            dept,
            a.tenant,
            name,
        )
    await world.sql("UPDATE users SET department_id = $1 WHERE id = $2", finance, a.requester)
    colleague = await world.create(
        a, a.admin, requester_id=str(a.requester2), department_id=str(finance)
    )
    elsewhere = await world.create(
        a, a.admin, requester_id=str(a.requester2), department_id=str(sales)
    )
    assert colleague["id"] not in ids(await mine(world, a, a.requester))

    granted = await role(world, a, "Department viewer", [("work_items.view_department", "all")])
    assigned = await world.call("PUT", f"/users/{a.requester}/roles/{granted}", a, a.admin)
    assert assigned.status_code in {200, 204}, assigned.text
    seen = ids(await mine(world, a, a.requester))
    assert colleague["id"] in seen
    assert elsewhere["id"] not in seen
    record = await world.call("GET", f"{PORTAL}/{elsewhere['id']}", a, a.requester)
    assert problem(record) == (404, "work_item_not_found")


async def test_open_closed_and_search_filters(world: World) -> None:
    a = world.a
    printer = await world.create(a, a.admin, subject="Printer jams on tray 2")
    vpn = await world.create(a, a.admin, subject="VPN drops every hour")
    canceled = await world.act(a, a.admin, vpn, "cancel", "duplicate")
    assert canceled.status_code == 200, canceled.text

    assert ids(await mine(world, a, a.requester, state="open")) == {printer["id"]}
    assert ids(await mine(world, a, a.requester, state="closed")) == {vpn["id"]}
    assert ids(await mine(world, a, a.requester, q="printer")) == {printer["id"]}
    assert ids(await mine(world, a, a.requester, q=vpn["display_id"])) == {vpn["id"]}
    assert ids(await mine(world, a, a.requester, q="100%_")) == set()


async def report(world: World, org: Org, user: uuid.UUID, **body: Any) -> Any:  # noqa: ANN401
    return await world.call(
        "POST",
        PORTAL,
        org,
        user,
        json={"subject": "Laptop will not start", **body},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )


async def test_a_requester_reports_an_issue_and_gets_its_id_at_once(world: World) -> None:
    a = world.a
    made = await report(world, a, a.requester, description="<p>Black screen</p>")
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["display_id"].startswith("INC-")  # REQ-INC-028 AC1
    assert (body["portal_status"], body["reach"]) == ("received", "own")
    assert not set(body) & STAFF_ONLY
    staff = (await world.call("GET", f"/incidents/{body['id']}", a, a.admin)).json()
    assert staff["channel"] == "portal"
    assert staff["requester_id"] == str(a.requester)  # always the signed-in person
    # it is in the technicians' list (live: the engine's usual outbox event, REQ-INC-028 AC3)
    listed = (await world.call("GET", "/incidents", a, a.admin)).json()
    assert body["id"] in {i["id"] for i in listed["items"]}


async def test_a_requester_cannot_set_staff_or_unfillable_fields(world: World) -> None:
    a = world.a
    for extra in (
        {"group_id": str(a.ga)},
        {"technician_id": str(a.tech_a)},
        {"priority": "critical"},
        {"requester_id": str(a.requester2)},
    ):
        refused = await report(world, a, a.requester, **extra)
        assert refused.status_code == 422, (extra, refused.text)
    # urgency is a requester field the default template does not let them fill in
    refused = await report(world, a, a.requester, urgency="high")
    assert refused.status_code == 422, refused.text
    assert [e["code"] for e in refused.json()["errors"]] == ["read_only"]


async def test_the_portal_offers_requester_templates_with_requester_fields_only(
    world: World,
) -> None:
    a = world.a
    offered = (await world.call("GET", f"{PORTAL}/templates", a, a.requester)).json()
    assert [t["is_default"] for t in offered] == [True]  # none marked: the default
    assert {f["name"] for f in offered[0]["fields"]} == {"subject", "description"}
    other_tenant = await world.call(
        "POST",
        PORTAL,
        a,
        a.requester,
        json={"subject": "x", "template_id": str(uuid.uuid4())},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert other_tenant.status_code == 422, other_tenant.text
    assert other_tenant.json()["errors"][0]["code"] == "template_not_found"


async def test_the_portal_conversation_shows_public_entries_only(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    private = await say(world, a, a.admin, item, body="<p>Vendor case 8812, ignore user</p>")
    assert private.status_code == 201, private.text
    public = await say(world, a, a.admin, item, kind="reply", body="<p>Restart it please.</p>")
    assert public.status_code == 201, public.text

    found = await world.call("GET", f"{PORTAL}/{item['id']}/conversation", a, a.requester)
    assert found.status_code == 200, found.text
    entries = found.json()["items"]
    assert [e["body"] for e in entries] == ["<p>Restart it please.</p>"]  # REQ-INC-147 AC2
    assert entries[0]["by_you"] is False
    assert set(entries[0]) == {"id", "kind", "body", "created_at", "author_name", "by_you"}
    other = await world.call("GET", f"{PORTAL}/{item['id']}/conversation", a, a.requester2)
    assert problem(other) == (404, "work_item_not_found")


async def test_a_requester_replies_but_a_manager_with_reach_only_reads(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, requester_id=str(a.requester2))
    replied = await world.call(
        "POST", f"{PORTAL}/{item['id']}/replies", a, a.requester2, json={"body": "<p>Any news?</p>"}
    )
    assert replied.status_code == 201, replied.text
    entries = (
        await world.call("GET", f"{PORTAL}/{item['id']}/conversation", a, a.requester2)
    ).json()["items"]
    assert [(e["body"], e["by_you"]) for e in entries] == [("<p>Any news?</p>", True)]

    await world.sql("UPDATE users SET manager_id = $1 WHERE id = $2", a.requester, a.requester2)
    granted = await role(world, a, "Lead (portal)", [("work_items.view_reports", "all")])
    await world.call("PUT", f"/users/{a.requester}/roles/{granted}", a, a.admin)
    seen = await world.call("GET", f"{PORTAL}/{item['id']}/conversation", a, a.requester)
    assert seen.status_code == 200, seen.text
    refused = await world.call(
        "POST", f"{PORTAL}/{item['id']}/replies", a, a.requester, json={"body": "<p>Hi</p>"}
    )
    assert refused.status_code == 403, refused.text


async def test_the_requester_confirms_or_rejects_a_fix_in_the_portal(world: World) -> None:
    a = world.a
    first = await world.create(a, a.admin, group_id=str(a.ga))
    second = await world.create(a, a.admin, group_id=str(a.ga))
    for item in (first, second):
        resolved = await world.act(a, a.admin, item, "resolve", resolution="<p>Reset done</p>")
        assert resolved.status_code == 200, resolved.text
    shown = (await world.call("GET", f"{PORTAL}/{first['id']}", a, a.requester)).json()
    assert (shown["portal_status"], shown["resolution"]) == ("resolved", "<p>Reset done</p>")

    confirmed = await world.call(
        "POST", f"{PORTAL}/{first['id']}/resolution/confirm", a, a.requester
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["portal_status"] in {"closed", "resolved"}
    assert not set(confirmed.json()) & STAFF_ONLY
    rejected = await world.call(
        "POST",
        f"{PORTAL}/{second['id']}/resolution/reject",
        a,
        a.requester,
        json={"comment": "Still jams."},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["portal_status"] == "in_progress"
    again = await world.call("POST", f"{PORTAL}/{second['id']}/resolution/confirm", a, a.requester)
    assert problem(again)[0] == 409


async def _published(app_db: Database, org: Org, envelope: EventEnvelope) -> dict[str, Any]:
    """Channel name -> the publication's fields, for one event through the realtime routes."""
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        for spec in ROUTES:
            if envelope.event_type in spec.event_types:
                effects = await spec.route(envelope, session)
                return {p.channel.name: p for p in effects.publications}
    return {}


async def test_the_requester_channel_hears_only_what_the_requester_sees(
    world: World, app_db: Database
) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    portal = f"t:{a.tenant}:portal_wi:{item['id']}"
    await say(world, a, a.admin, item, body="<p>Vendor case 8812</p>")  # private note
    await say(world, a, a.admin, item, kind="reply", body="<p>On it</p>")  # public reply
    current = await world.fresh(a, item)
    for action, reason in (
        ("start_work", None),
        ("wait_third_party", "vendor"),  # in progress -> third party: the same to them
        ("resume", None),
        ("wait_requester", "more_information"),
    ):
        moved = await world.act(a, a.admin, current, action, reason_code=reason)
        assert moved.status_code == 200, (action, moved.text)
        current = moved.json()

    entries = [
        e
        for e in await events_of(world, "work_item_conversation")
        if e.payload["work_item_id"] == item["id"]
    ]
    heard = [portal in await _published(app_db, a, e) for e in entries]
    assert heard == [False, True]  # the private note says nothing there (REQ-INC-147 AC2)

    changes = [
        e
        for e in await events_of(world, "work_item")
        if e.payload.get("work_item_id") == item["id"] and "to_status" in e.payload
    ]
    by_status = {}
    for event in changes:
        found = await _published(app_db, a, event)
        by_status[event.payload["to_status"]] = found[portal].fields if portal in found else None
    assert by_status["awaiting_third_party"] is None
    assert by_status["awaiting_requester"] == ("portal_status",)


async def test_only_the_requester_side_may_join_the_requester_channel(
    world: World, app_db: Database
) -> None:
    a, b = world.a, world.b
    item = await world.create(
        a, a.admin, requester_id=str(a.requester2), on_behalf_of_id=str(a.requester)
    )
    spec = next(c for c in CHANNELS if c.kind == PORTAL_KIND)

    async def joins(org: Org, user: uuid.UUID, record_id: str) -> bool:
        async with app_db.tenant_session(TenantContext(org.tenant, user_id=user)) as session:
            subject = await subject_for(session, org.tenant, user)
            request = ChannelRequest(
                Channel(org.tenant, PORTAL_KIND, record_id), org.tenant, user, subject, session
            )
            return await spec.authorize(request) is not None

    assert await joins(a, a.requester2, item["id"])  # requester
    assert await joins(a, a.requester, item["id"])  # the person it is for
    assert not await joins(a, a.tech_a, item["id"])  # staff use the record channel
    assert not await joins(a, a.admin, item["id"])
    assert not await joins(b, b.requester, item["id"])  # another tenant: RLS hides the row
    assert not await joins(a, a.requester, "not-a-uuid")


async def test_requester_side_messages_name_the_portal_status_only(
    world: World, app_db: Database
) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    current = await world.fresh(a, item)
    for action, reason in (("start_work", None), ("wait_third_party", "vendor")):
        moved = await world.act(a, a.admin, current, action, reason_code=reason)
        assert moved.status_code == 200, (action, moved.text)
        current = moved.json()
    event = next(
        e
        for e in await events_of(world, "work_item")
        if e.payload.get("work_item_id") == item["id"]
        and e.payload.get("to_status") == "awaiting_third_party"
    )
    async with app_db.tenant_session(TenantContext(a.tenant)) as session:
        context = await NOTIFICATIONS.context(session, "incident.status_changed", event)
    assert context is not None
    # staff read the real status; the requester's side the plain one (REQ-INC-147 AC2)
    assert context.variables["record.status"] != LabelRef("portal_status.in_progress")
    assert context.public_variables["record.status"] == LabelRef("portal_status.in_progress")
    assert context.public_variables["change.from_status"] == LabelRef("portal_status.in_progress")
    assert context.public_link == f"/requests/{item['id']}"  # e-mails open it in the portal
