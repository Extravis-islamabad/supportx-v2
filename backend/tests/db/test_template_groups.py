"""Templates limited to groups (WP-044c S1; REQ-PRB-021; migration 0109)."""

import uuid
from typing import Any

from tests.db.test_incidents_api import Org, World, field_codes, world
from tests.db.test_problems_api import PRB, new_problem

__all__ = ["world"]  # the fixture, re-used


async def limited(world: World, org: Org, groups: list[uuid.UUID], **values: Any) -> Any:  # noqa: ANN401 - the response
    body = {
        "labels": {"en": f"Network outage {uuid.uuid4().hex[:6]}"},
        "limited_group_ids": [str(g) for g in groups],
        **values,
    }
    return await world.call("POST", f"{PRB}/templates", org, org.admin, json=body)


async def listed(world: World, org: Org, user: uuid.UUID) -> set[str]:
    found = await world.call("GET", f"{PRB}/templates", org, user)
    assert found.status_code == 200, found.text
    return {t["id"] for t in found.json()}


async def test_req_prb_021_ac1_only_the_groups_members_are_offered_it(world: World) -> None:
    a = world.a
    made = await limited(world, a, [a.ga])
    assert made.status_code == 201, made.text
    template = made.json()
    assert template["limited_group_ids"] == [str(a.ga)]
    assert template["id"] in await listed(world, a, a.tech_a)  # in GA
    assert template["id"] not in await listed(world, a, a.tech_b)  # not in GA
    assert template["id"] in await listed(world, a, a.admin)  # admins see every template
    # The API refuses what the form does not offer.
    refused = await new_problem(world, a, a.tech_b, template_id=template["id"])
    assert field_codes(refused) == {"template_id": "template_not_offered"}
    made_by_member = await new_problem(world, a, a.tech_a, template_id=template["id"])
    assert made_by_member.status_code == 201, made_by_member.text
    # AC2: a problem made from it stays visible to whoever may see the problem.
    seen = await world.call("GET", f"{PRB}/{made_by_member.json()['id']}", a, a.admin)
    assert seen.status_code == 200, seen.text


async def test_req_prb_021_the_groups_are_this_tenants_and_at_most_fifty(world: World) -> None:
    a, b = world.a, world.b
    # Another tenant's group is not found here (RLS), never used.
    other = await limited(world, a, [b.ga])
    assert set(field_codes(other).values()) == {"group_not_found"}
    too_many = await limited(world, a, [uuid.uuid4() for _ in range(51)])
    assert too_many.status_code == 422, too_many.text
    # Tenant B never sees tenant A's limited template, even its admin.
    made = (await limited(world, a, [a.ga])).json()
    assert made["id"] not in await listed(world, b, b.admin)


async def test_req_prb_021_a_template_for_requesters_is_for_everyone(world: World) -> None:
    a = world.a
    both = await limited(world, a, [a.ga], for_requesters=True)
    assert set(field_codes(both).values()) == {"limited_template_for_requesters"}
    # Turning on "for requesters" on a limited template is refused the same way.
    made = (await limited(world, a, [a.ga])).json()
    changed = await world.call(
        "PATCH",
        f"{PRB}/templates/{made['id']}",
        a,
        a.admin,
        json={"for_requesters": True},
        headers={"If-Match": f'"{made["version"]}"'},
    )
    assert set(field_codes(changed).values()) == {"limited_template_for_requesters"}
    # Emptying the groups opens it to everyone again.
    opened = await world.call(
        "PATCH",
        f"{PRB}/templates/{made['id']}",
        a,
        a.admin,
        json={"limited_group_ids": []},
        headers={"If-Match": f'"{made["version"]}"'},
    )
    assert opened.status_code == 200, opened.text
    assert made["id"] in await listed(world, a, a.tech_b)
