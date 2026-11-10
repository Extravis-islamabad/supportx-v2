"""Service requests from catalog items over HTTP (WP-030 s1; REQ-SR-001, -004, -005, -008, -021).

Real PostgreSQL with RLS. A service request always comes from an item; the item decides the
first status (awaiting approval when it needs one), the priority (marked as the item's), the
group, and the technician (after approval when it says so); the answers follow the form.
"""

import uuid
from typing import Any

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_catalog_api import add as add_item
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

SR = "/service-requests"


async def raise_request(world: World, org: Org, user: uuid.UUID, **body: Any) -> Any:  # noqa: ANN401
    return await world.call(
        "POST",
        SR,
        org,
        user,
        json={"subject": "New laptop for Sara", "requester_id": str(user), **body},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def an_item(world: World, org: Org, **over: Any) -> dict[str, Any]:  # noqa: ANN401
    body: dict[str, Any] = {
        "questions": [
            {
                "key": "model",
                "label": {"en": "Model"},
                "kind": "choice",
                "required": True,
                "options": ["air", "pro"],
            }
        ],
        "group_id": str(org.ga),
        "default_priority": "p2",
        **over,
    }
    made = await add_item(world, org, org.admin, **body)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def test_a_request_from_an_item_that_needs_approval_waits_for_it(world: World) -> None:
    a = world.a
    item = await an_item(
        world,
        a,
        approval={"approvers": [{"kind": "requested_for_manager"}]},
        technician_id=str(a.tech_a),
        technician_after_approval=True,
    )
    made = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["display_id"] == "SR-1"  # its own counter (REQ-SR-001 AC1)
    assert body["status"] == "awaiting_approval"  # REQ-SR-004 AC1
    assert body["approval_status"] == "pending"
    assert (body["priority"], body["priority_source"]) == ("p2", "catalog_item")  # REQ-SR-005
    assert body["group_id"] == str(a.ga)  # the group at once (REQ-SR-008 AC1)
    assert body["technician_id"] is None  # the technician after approval (AC2)
    assert (body["catalog_item_id"], body["answers"]) == (item["id"], {"model": "air"})
    # Incidents keep their own counter.
    incident = await world.create(a, a.admin)
    assert incident["display_id"].startswith("INC-")


async def test_without_approval_a_request_starts_new_or_assigned(world: World) -> None:
    a = world.a
    plain = await an_item(world, a)
    assigned = await an_item(world, a, technician_id=str(a.tech_a))
    found = []
    for item in (plain, assigned):
        made = await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "pro"}
        )
        assert made.status_code == 201, made.text
        found.append(made.json())
    first, second = found
    assert (first["status"], first["approval_status"]) == ("new", "not_needed")
    assert (second["status"], second["technician_id"]) == ("assigned", str(a.tech_a))


async def test_a_request_needs_an_item_it_may_raise_and_valid_answers(world: World) -> None:
    a = world.a
    none = await raise_request(world, a, a.requester)
    assert none.status_code == 422, none.text
    assert none.json()["errors"][0]["field"] == "body.catalog_item_id"  # REQ-SR-001 AC2
    staff_only = await an_item(world, a, audience="technicians")
    hidden = await raise_request(
        world, a, a.requester, catalog_item_id=staff_only["id"], answers={"model": "air"}
    )
    assert hidden.status_code == 422, hidden.text
    assert hidden.json()["errors"][0]["code"] == "catalog_item_not_found"
    item = await an_item(world, a)
    bad = await raise_request(world, a, a.requester, catalog_item_id=item["id"], answers={})
    assert bad.status_code == 422, bad.text
    assert {e["field"] for e in bad.json()["errors"]} == {"body.answers.model"}


async def test_an_incident_takes_no_item(world: World) -> None:
    a = world.a
    item = await an_item(world, a)
    refused = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"subject": "x", "requester_id": str(a.requester), "catalog_item_id": item["id"]},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert problem(refused)[0] == 422
    assert refused.json()["errors"][0]["field"] == "body.catalog_item_id"


async def test_nobody_chooses_awaiting_approval_or_rejected_by_hand(world: World) -> None:
    """REQ-SR-004 AC3: approve and reject are the approval engine's, never a person's action."""
    a = world.a
    item = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    made = (
        await raise_request(world, a, a.admin, catalog_item_id=item["id"], answers={"model": "air"})
    ).json()
    for action in ("approve", "reject"):
        moved = await world.call(
            "POST",
            f"{SR}/{made['id']}/actions/{action}",
            a,
            a.admin,
            json={},
            headers={"If-Match": f'"{made["version"]}"', **CONSOLE},
        )
        assert problem(moved) == (409, "invalid_transition"), (action, moved.text)


async def test_service_requests_filter_by_item_and_approval_status(world: World) -> None:
    """REQ-SR-009 AC3: by catalog item and by approval status."""
    a = world.a
    needs = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    plain = await an_item(world, a)
    waiting = (
        await raise_request(
            world, a, a.admin, catalog_item_id=needs["id"], answers={"model": "air"}
        )
    ).json()
    free = (
        await raise_request(
            world, a, a.admin, catalog_item_id=plain["id"], answers={"model": "air"}
        )
    ).json()

    async def ids(**params: str) -> set[str]:
        listed = await world.call("GET", SR, a, a.admin, params=params)
        assert listed.status_code == 200, listed.text
        return {i["id"] for i in listed.json()["items"]}

    assert await ids(approval_status="pending") == {waiting["id"]}
    assert await ids(catalog_item_id=plain["id"]) == {free["id"]}
    assert {waiting["id"], free["id"]}.isdisjoint(
        {i["id"] for i in (await world.call("GET", BASE, a, a.admin)).json()["items"]}
    )  # the incident list never shows them


async def test_a_requester_raises_for_others_only_within_the_scope(world: World) -> None:
    """REQ-SR-011 AC1: same department by default, their direct reports always, else 403."""
    a = world.a
    item = await an_item(world, a)
    finance = uuid.uuid4()
    await world.sql(
        "INSERT INTO departments (id, tenant_id, name) VALUES ($1, $2, 'Finance')",
        finance,
        a.tenant,
    )
    stranger = await raise_request(
        world,
        a,
        a.requester,
        catalog_item_id=item["id"],
        answers={"model": "air"},
        on_behalf_of_id=str(a.requester2),
    )
    assert problem(stranger) == (403, "on_behalf_out_of_scope")
    await world.sql(
        "UPDATE users SET department_id = $1 WHERE id = ANY($2::uuid[])",
        finance,
        [a.requester, a.requester2],
    )
    colleague = await raise_request(
        world,
        a,
        a.requester,
        catalog_item_id=item["id"],
        answers={"model": "air"},
        on_behalf_of_id=str(a.requester2),
    )
    assert colleague.status_code == 201, colleague.text
    assert colleague.json()["on_behalf_of_id"] == str(a.requester2)
    # Staff raise for anyone.
    by_staff = await raise_request(
        world,
        a,
        a.admin,
        catalog_item_id=item["id"],
        answers={"model": "air"},
        on_behalf_of_id=str(a.tech_b),
    )
    assert by_staff.status_code == 201, by_staff.text


async def test_requests_have_approval_views_incidents_do_not(world: World) -> None:
    """REQ-SR-009 AC1: pending approval; approved (or needing none) and awaiting fulfilment."""
    a = world.a
    needs = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    plain = await an_item(world, a)
    waiting = (
        await raise_request(
            world, a, a.admin, catalog_item_id=needs["id"], answers={"model": "air"}
        )
    ).json()
    free = (
        await raise_request(
            world, a, a.admin, catalog_item_id=plain["id"], answers={"model": "air"}
        )
    ).json()

    async def in_view(view: str) -> set[str]:
        listed = await world.call("GET", SR, a, a.admin, params={"view": view})
        assert listed.status_code == 200, listed.text
        return {i["id"] for i in listed.json()["items"]}

    assert await in_view("pending_approval") == {waiting["id"]}
    assert await in_view("awaiting_fulfilment") == {free["id"]}
    counts = (await world.call("GET", f"{SR}/views", a, a.admin)).json()
    found = {c["view"]: c["count"] for c in counts}
    assert (found["pending_approval"], found["awaiting_fulfilment"]) == (1, 1)
    incident_views = (await world.call("GET", f"{BASE}/views", a, a.admin)).json()
    assert not {"pending_approval", "awaiting_fulfilment"} & {c["view"] for c in incident_views}


async def test_qa10_p4_40_a_request_raised_in_the_portal_reads_as_the_portal(world: World) -> None:
    a = world.a
    item = await an_item(world, a)
    made = await world.call(
        "POST",
        SR,
        a,
        a.requester,
        json={
            "subject": "Laptop",
            "requester_id": str(a.requester),
            "catalog_item_id": item["id"],
            "answers": {"model": "air"},
        },
        headers={"Idempotency-Key": str(uuid.uuid4()), "X-SupportX-Client": "portal"},
    )
    assert made.status_code == 201, made.text
    assert made.json()["channel"] == "portal"
