"""Service requests from catalog items over HTTP (WP-030 s1; REQ-SR-001, -004, -005, -008, -021).

Real PostgreSQL with RLS. A service request always comes from an item; the item decides the
first status (awaiting approval when it needs one), the priority (marked as the item's), the
group, and the technician (after approval when it says so); the answers follow the form.
"""

import uuid
from typing import Any

from tests.db.test_catalog_api import add as add_item
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, problem, world

__all__ = ["world"]  # the fixture, re-used

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
