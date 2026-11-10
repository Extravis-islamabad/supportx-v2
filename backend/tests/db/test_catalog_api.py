"""The service catalog over HTTP (WP-030 s1, plan D2). Real PostgreSQL with RLS.

Admins add items with forms, an approval stage and a plan; requesters see only enabled items
open to everyone; technicians see all; another tenant sees none; every reference is checked;
writes need catalog_items.manage, follow If-Match and are audited.
"""

import uuid
from typing import Any

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, Org, World, problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

ITEMS = "/catalog/items"
CATEGORIES = "/catalog/categories"


async def category(world: World, org: Org, **body: Any) -> str:  # noqa: ANN401 - JSON
    """A category made by the org's admin; its ID."""
    made = await world.call(
        "POST",
        CATEGORIES,
        org,
        org.admin,
        json={"names": {"en": "Hardware", "ar": "الأجهزة"}, **body},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


async def add(world: World, org: Org, user: uuid.UUID, **body: Any) -> Any:  # noqa: ANN401
    """An item, published at once in a new category with the org's group (WP-031 plan D9).

    `enabled=False` makes a draft (the WP-030 spelling); `status` is passed through.
    """
    if "status" not in body and "enabled" not in body:
        body["status"] = "published"
    if body.get("enabled") is False:
        del body["enabled"]
        body["status"] = "draft"
    body.setdefault("category_id", await category(world, org))
    body.setdefault("group_id", str(org.ga))
    return await world.call(
        "POST",
        ITEMS,
        org,
        user,
        json={"names": {"en": "New laptop", "ar": "حاسوب جديد"}, **body},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


def laptop(org: Org) -> dict[str, Any]:
    return {
        "questions": [
            {
                "key": "model",
                "label": {"en": "Model"},
                "kind": "choice",
                "required": True,
                "options": ["air", "pro"],
            }
        ],
        "approval": {"approvers": [{"kind": "requested_for_manager"}]},
        "plan": [{"title": {"en": "Image the laptop"}, "group_id": str(org.ga)}],
        "group_id": str(org.ga),
        "default_priority": "p3",
    }


async def test_an_admin_adds_an_item_and_changes_it_with_if_match(world: World) -> None:
    a = world.a
    made = await add(world, a, a.admin, **laptop(a))
    assert made.status_code == 201, made.text
    item = made.json()
    assert item["approval"]["approvers"] == [{"kind": "requested_for_manager", "person_id": None}]
    assert item["plan"][0]["group_id"] == str(a.ga)
    changed = await world.call(
        "PATCH",
        f"{ITEMS}/{item['id']}",
        a,
        a.admin,
        json={"enabled": False},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["enabled"], changed.json()["version"]) == (False, item["version"] + 1)
    stale = await world.call(
        "PATCH",
        f"{ITEMS}/{item['id']}",
        a,
        a.admin,
        json={"enabled": True},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert problem(stale)[0] == 409
    audited = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'catalog.item_changed' AND outcome = 'done'",
        a.tenant,
    )
    assert audited[0]["n"] == 2  # the create and the change


async def test_who_sees_which_items(world: World) -> None:
    a, b = world.a, world.b
    for_all = (await add(world, a, a.admin)).json()
    staff_only = (await add(world, a, a.admin, audience="technicians")).json()
    off = (await add(world, a, a.admin, enabled=False)).json()

    def ids(response: Any) -> set[str]:  # noqa: ANN401
        assert response.status_code == 200, response.text
        return {i["id"] for i in response.json()}

    requester = ids(await world.call("GET", ITEMS, a, a.requester))
    assert for_all["id"] in requester
    assert {staff_only["id"], off["id"]}.isdisjoint(requester)  # REQ-SR-010 AC3
    technician = ids(await world.call("GET", ITEMS, a, a.tech_a))
    assert {for_all["id"], staff_only["id"], off["id"]} <= technician
    hidden = await world.call("GET", f"{ITEMS}/{staff_only['id']}", a, a.requester)
    assert problem(hidden) == (404, "catalog_item_not_found")
    # Another tenant sees none of them (RLS), even by ID.
    assert ids(await world.call("GET", ITEMS, b, b.admin)).isdisjoint(technician)
    other = await world.call("GET", f"{ITEMS}/{for_all['id']}", b, b.admin)
    assert problem(other) == (404, "catalog_item_not_found")


async def test_another_tenant_cannot_change_an_item(world: World) -> None:
    a, b = world.a, world.b
    item = (await add(world, a, a.admin)).json()
    attempt = await world.call(
        "PATCH",
        f"{ITEMS}/{item['id']}",
        b,
        b.admin,
        json={"enabled": False},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert problem(attempt) == (404, "catalog_item_not_found")
    still = (await world.call("GET", f"{ITEMS}/{item['id']}", a, a.admin)).json()
    assert still["enabled"] is True


async def test_writing_needs_the_permission(world: World) -> None:
    a = world.a
    for user in (a.tech_a, a.requester):
        refused = await add(world, a, user)
        assert refused.status_code == 403, refused.text


async def test_every_reference_is_checked_and_the_rules_too(world: World) -> None:
    a, b = world.a, world.b
    refused = await add(
        world,
        a,
        a.admin,
        group_id=str(b.ga),  # another tenant's group
        technician_id=str(uuid.uuid4()),
        approval={"approvers": [{"kind": "person"}]},
        questions=[{"key": "Bad Key", "label": {"en": "x"}, "kind": "text"}],
    )
    assert refused.status_code == 422, refused.text
    codes = {e["field"]: e["code"] for e in refused.json()["errors"]}
    assert codes == {
        "body.group_id": "not_found",
        "body.technician_id": "not_found",
        "body.approval.approvers.0.person_id": "required",
        "body.questions.0.key": "invalid_key",
    }
    no_english = await add(world, a, a.admin, names={"ar": "حاسوب"})
    assert no_english.status_code == 422, no_english.text
    assert {e["field"] for e in no_english.json()["errors"]} == {"body.names.en"}
