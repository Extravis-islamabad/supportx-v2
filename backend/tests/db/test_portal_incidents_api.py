"""The portal's incidents for requesters over HTTP (WP-028 session 1; wp-028-plan.md D1-D3).

Real PostgreSQL with RLS. A requester sees only their own incidents (requester or the person it
is for), unless they hold a wider reach (D2 default: direct reports, department); another
tenant's records never appear; out-of-reach records are 404; staff-only fields are absent from
every response, and a staff field can't be used as a filter to probe for records.
"""

import uuid
from typing import Any

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
    granted = await role(world, a, "Team lead (portal)", [("requests.view_reports", "all")])
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

    granted = await role(world, a, "Department viewer", [("requests.view_department", "all")])
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
