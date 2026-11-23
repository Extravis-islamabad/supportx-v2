"""Custom fields scoped to a type and its subtypes (0175; plans/metadata-type-subtree-design).

Asset product types are the tree here (the CMDB's CI types join with #524):
- a field scoped to a type applies to that type and every type below it, and is unknown on a
  sibling branch (`unknown_field`, as any key no field has);
- `GET /custom-fields?type_id=` lists what a type has, inherited ones marked;
- a scope widens any time; narrower or sideways once a record holds a value is refused (409);
- an entity with no type tree, or a type the tree does not know, refuses a scope (422);
- asset and CI fields are never sensitive, refused by the server on create and on change
  (lane A's condition a), whatever a client sends;
- work-item fields are unchanged; another tenant sees nothing.
"""

import uuid
from typing import Any

import pytest

from app.core.errors import ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.metadata.service import custom_fields as service
from tests.db import test_incidents_api
from tests.db.test_assets_api import _add, _product, _types
from tests.db.test_incidents_api import Org, World
from tests.db.test_knowledge_api import _match, _new

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

FIELDS = "/custom-fields"


async def _field(world: World, org: Org, entity: str, name: str, **extra: Any) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "POST",
        FIELDS,
        org,
        org.admin,
        json={"entity": entity, "field_type": "text", "labels": {"en": name}, **extra},
        headers=_new(),
    )


def _codes(response: Any) -> list[str]:  # noqa: ANN401 - httpx response
    body = response.json()
    return [e["code"] for e in body.get("errors", [])] or [body.get("code")]


async def test_a_scoped_field_reaches_its_subtree_and_not_a_sibling(world: World) -> None:
    a = world.a
    types = await _types(world, a)
    hardware = await _field(
        world, a, "asset", "Rack location", scope_type_id=types["it_hardware"]["id"]
    )
    assert hardware.status_code == 201, hardware.text
    assert hardware.json()["scope_type_id"] == types["it_hardware"]["id"]
    computers = await _field(world, a, "asset", "Image", scope_type_id=types["computer"]["id"])
    assert computers.status_code == 201, computers.text
    rack, image = hardware.json()["key"], computers.json()["key"]

    # A laptop (it_hardware > computer > laptop) has both: its grandparent's and its parent's.
    laptop = await _product(world, a, "laptop", "Scope laptop")
    made = await _add(
        world, a, {"name": "Scoped", "product_id": laptop, "custom": {rack: "R1", image: "W11"}}
    )
    assert made.status_code == 201, made.text
    assert made.json()["custom"] == {rack: "R1", image: "W11"}

    # A phone (it_hardware > mobile_device > phone) has the hardware field, not the computers'.
    phone = await _product(world, a, "phone", "Scope phone")
    refused = await _add(world, a, {"name": "Phone", "product_id": phone, "custom": {image: "x"}})
    assert refused.status_code == 422, refused.text
    assert "unknown_field" in _codes(refused)
    kept = await _add(world, a, {"name": "Phone 2", "product_id": phone, "custom": {rack: "R2"}})
    assert kept.status_code == 201, kept.text

    # What a type has, with the inherited ones marked.
    listed = await world.call(
        "GET", f"{FIELDS}?entity=asset&type_id={types['computer']['id']}", a, a.admin
    )
    assert listed.status_code == 200, listed.text
    by_key = {f["key"]: f for f in listed.json()}
    assert by_key[rack]["inherited"] is True  # the parent type's
    assert by_key[image]["inherited"] is False  # the type's own
    for_phone = await world.call(
        "GET", f"{FIELDS}?entity=asset&type_id={types['phone']['id']}", a, a.admin
    )
    assert image not in {f["key"] for f in for_phone.json()}
    # Without a type: every field of the entity, as before.
    everything = await world.call("GET", f"{FIELDS}?entity=asset", a, a.admin)
    assert {rack, image} <= {f["key"] for f in everything.json()}


async def test_a_scope_widens_any_time_and_never_narrows_once_used(world: World) -> None:
    a = world.a
    types = await _types(world, a)
    made = await _field(world, a, "asset", "Warranty desk", scope_type_id=types["computer"]["id"])
    assert made.status_code == 201, made.text
    field = made.json()
    # Unused: a sideways move is fine.
    moved = await world.call(
        "PATCH",
        f"{FIELDS}/{field['id']}",
        a,
        a.admin,
        json={"scope_type_id": types["mobile_device"]["id"]},
        headers=_match(field["version"]),
    )
    assert moved.status_code == 200, moved.text
    field = moved.json()
    phone = await _product(world, a, "phone", "Scope phone 3")
    used = await _add(
        world, a, {"name": "Used", "product_id": phone, "custom": {field["key"]: "Desk 4"}}
    )
    assert used.status_code == 201, used.text
    field = (await world.call("GET", f"{FIELDS}?entity=asset", a, a.admin)).json()
    field = next(f for f in field if f["id"] == moved.json()["id"])
    # Used: narrower (to phone) or sideways (to computer) is refused; nothing changes.
    for wanted in (types["phone"]["id"], types["computer"]["id"]):
        refused = await world.call(
            "PATCH",
            f"{FIELDS}/{field['id']}",
            a,
            a.admin,
            json={"scope_type_id": wanted},
            headers=_match(field["version"]),
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "custom_field_scope_in_use"
    # Wider: to the parent, then to the whole entity.
    wider = await world.call(
        "PATCH",
        f"{FIELDS}/{field['id']}",
        a,
        a.admin,
        json={"scope_type_id": types["it_hardware"]["id"]},
        headers=_match(field["version"]),
    )
    assert wider.status_code == 200, wider.text
    whole = await world.call(
        "PATCH",
        f"{FIELDS}/{field['id']}",
        a,
        a.admin,
        json={"scope_type_id": None},
        headers=_match(wider.json()["version"]),
    )
    assert whole.status_code == 200, whole.text
    assert whole.json()["scope_type_id"] is None


async def test_a_scope_needs_a_tree_and_a_known_type(world: World) -> None:
    a = world.a
    types = await _types(world, a)
    # Work items have no type tree: refused, and their fields are unchanged.
    incident = await _field(
        world, a, "incident", "Scoped incident", scope_type_id=types["laptop"]["id"]
    )
    assert incident.status_code == 422, incident.text
    assert "custom_field_scope_unsupported" in _codes(incident)
    plain = await _field(world, a, "incident", "Plain incident field")
    assert plain.status_code == 201, plain.text
    assert plain.json()["scope_type_id"] is None
    assert plain.json()["inherited"] is False
    unknown = await _field(world, a, "asset", "Lost type", scope_type_id=str(uuid.uuid4()))
    assert unknown.status_code == 422, unknown.text
    assert "custom_field_scope_unknown" in _codes(unknown)


@pytest.mark.parametrize("entity", ["asset", "ci"])
async def test_asset_and_ci_fields_are_never_sensitive(world: World, entity: str) -> None:
    """Lane A's 0175 condition (a): the server refuses, on create and on change."""
    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant, a.admin)) as session:
        with pytest.raises(ValidationFailed) as created:
            await service.create_field(
                session,
                entity,
                {
                    "field_type": "text",
                    "labels": {"en": f"Secret {entity} {uuid.uuid4().hex[:6]}"},
                    "sensitive": True,
                },
                source="api",
            )
        assert [e.code for e in created.value.errors] == ["custom_field_sensitive_unsupported"]
    made = await _field(world, a, entity, f"Open {entity} {uuid.uuid4().hex[:6]}")
    assert made.status_code == 201, made.text
    field = made.json()
    async with world.app.state.db.tenant_session(TenantContext(a.tenant, a.admin)) as session:
        with pytest.raises(ValidationFailed) as changed:
            await service.update_field(
                session,
                uuid.UUID(field["id"]),
                expected_version=field["version"],
                values={"sensitive": True},
                source="api",
            )
        assert [e.code for e in changed.value.errors] == ["custom_field_sensitive_unsupported"]
    # The sensitive switch refuses too (no seal port), and the API forbids the key on create.
    switch = await world.call(
        "PUT",
        f"{FIELDS}/{field['id']}/sensitivity",
        a,
        a.admin,
        json={"sensitive": True},
        headers=_match(field["version"]),
    )
    assert switch.status_code in (403, 409), switch.text  # 403: a recent sign-in asked first
    extra = await _field(world, a, entity, f"Extra {entity}", sensitive=True)
    assert extra.status_code == 422, extra.text


async def test_another_tenant_sees_no_scoped_field(world: World) -> None:
    a, b = world.a, world.b
    types = await _types(world, a)
    made = await _field(world, a, "asset", "Tenant A rack", scope_type_id=types["computer"]["id"])
    assert made.status_code == 201, made.text
    seen = await world.call(
        "GET", f"{FIELDS}?entity=asset&type_id={types['computer']['id']}", b, b.admin
    )
    assert seen.status_code == 200, seen.text
    assert made.json()["key"] not in {f["key"] for f in seen.json()}
    # A's type is unknown in B's tree: B cannot scope a field to it.
    borrowed = await _field(world, b, "asset", "Borrowed", scope_type_id=types["computer"]["id"])
    assert borrowed.status_code == 422, borrowed.text
    assert "custom_field_scope_unknown" in _codes(borrowed)
