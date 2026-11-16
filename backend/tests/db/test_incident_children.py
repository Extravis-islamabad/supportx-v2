"""Parent and child incidents (WP-046b S2; REQ-INC-086; lane B's conditions).

One level and no loops; edit on both records; a link never widens access: an unseen side
shows as a hidden line; the generic unlink refuses parent links (they have their own route);
another tenant's record is never found.
"""

from typing import Any

from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, world  # noqa: F401 - fixture


def _problem(response: Any) -> tuple[int, str | None]:  # noqa: ANN401 - an httpx response
    body = response.json()
    codes = [e.get("code") for e in body.get("errors") or []]
    return response.status_code, (codes[0] if codes else body.get("code"))


async def _child(
    world: World,  # noqa: F811
    org: Org,
    user: Any,  # noqa: ANN401 - a user ID
    parent: dict[str, Any],
    child: dict[str, Any],
) -> Any:  # noqa: ANN401 - an httpx response
    return await world.call(
        "POST",
        f"{BASE}/{parent['id']}/children",
        org,
        user,
        json={"child_id": child["id"]},
        headers=CONSOLE,
    )


async def _links(world: World, org: Org, user: Any, item: dict[str, Any]) -> list[Any]:  # noqa: F811, ANN401
    response = await world.call("GET", f"{BASE}/{item['id']}/links", org, user)
    assert response.status_code == 200, response.text
    return list(response.json())


async def test_one_level_no_loops_both_sides_and_history(world: World) -> None:  # noqa: F811
    a = world.a
    parent = await world.create(a, a.admin, group_id=str(a.ga))
    child = await world.create(a, a.admin, group_id=str(a.ga))
    other = await world.create(a, a.admin, group_id=str(a.ga))
    made = await _child(world, a, a.admin, parent, child)
    assert made.status_code == 201, made.text
    link = made.json()
    assert (link["child_id"], link["parent_id"]) == (child["id"], parent["id"])
    # Both sides read it their way.
    (from_parent,) = await _links(world, a, a.admin, parent)
    assert (from_parent["relation"], from_parent["other_id"]) == ("parent_of", child["id"])
    (from_child,) = await _links(world, a, a.admin, child)
    assert (from_child["relation"], from_child["other_id"]) == ("child_of", parent["id"])
    # One parent; a parent is no child; a child has no children; never itself.
    assert _problem(await _child(world, a, a.admin, other, child)) == (422, "already_has_parent")
    assert _problem(await _child(world, a, a.admin, other, parent)) == (422, "child_has_children")
    assert _problem(await _child(world, a, a.admin, child, other)) == (422, "parent_is_a_child")
    assert _problem(await _child(world, a, a.admin, other, other)) == (422, "cannot_link_itself")
    # History on both records.
    for item in (parent, child):
        history = await world.call("GET", f"{BASE}/{item['id']}/history", a, a.admin)
        assert any(c["field"] == "link" for e in history.json()["items"] for c in e["changes"]), (
            history.text
        )


async def test_edit_on_both_and_no_wider_access(world: World) -> None:  # noqa: F811
    a = world.a
    mine = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    theirs = await world.create(a, a.admin, group_id=str(a.gb), requester_id=str(a.requester2))
    # tech_a cannot see group B's record: it cannot be their child, and nothing says it exists.
    refused = await _child(world, a, a.tech_a, mine, theirs)
    assert _problem(refused) == (422, "record_not_found")
    # The admin links them; tech_a's view of the parent shows a hidden line, never the record.
    assert (await _child(world, a, a.admin, mine, theirs)).status_code == 201
    (line,) = await _links(world, a, a.tech_a, mine)
    assert line["relation"] == "parent_of"
    assert line["other_id"] is None
    assert line["other_display_id"] is None
    # And the child stays out of their reach.
    assert _problem(await world.get(a, a.tech_a, theirs)) == (404, "work_item_not_found")


async def test_own_route_to_remove_and_tenants_apart(world: World) -> None:  # noqa: F811
    a = world.a
    parent = await world.create(a, a.admin, group_id=str(a.ga))
    child = await world.create(a, a.admin, group_id=str(a.ga))
    link = (await _child(world, a, a.admin, parent, child)).json()
    # The generic unlink refuses it: removing a parent link needs edit on both.
    generic = await world.call(
        "DELETE",
        f"{BASE}/{parent['id']}/links/{link['link_id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{link["version"]}"', **CONSOLE},
    )
    assert _problem(generic) == (409, "link_has_own_route")
    removed = await world.call(
        "DELETE",
        f"{BASE}/{child['id']}/children/{link['link_id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{link["version"]}"', **CONSOLE},
    )
    assert removed.status_code == 204, removed.text
    assert await _links(world, a, a.admin, parent) == []
    # Another tenant's incident is never found.
    elsewhere = await world.create(world.b, world.b.admin)
    assert _problem(await _child(world, a, a.admin, parent, elsewhere)) == (422, "record_not_found")


async def test_a_closed_incident_takes_no_parent(world: World) -> None:  # noqa: F811
    a = world.a
    parent = await world.create(a, a.admin, group_id=str(a.ga))
    child = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    resolved = await world.act(a, a.admin, child, "resolve")
    closed = await world.act(a, a.admin, resolved.json(), "close")
    assert closed.json()["status_category"] == "closed"
    assert _problem(await _child(world, a, a.admin, parent, closed.json())) == (
        422,
        "record_closed",
    )
