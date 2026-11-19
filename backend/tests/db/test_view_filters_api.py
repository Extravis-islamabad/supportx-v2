"""Sealed values in saved-view filters (lane C's conditions for the #549 follow-up; ADR-050).

Real PostgreSQL, the incidents test world, a key ring of its own. The values hold a space and
"!", which no base64 text contains, so "absent from the stored text" never passes by chance.
"""

import json
import uuid
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.work_items.service import view_audit
from app.shared.crypto.codec import TEXT_PREFIX, from_text, key_id_of
from app.shared.files.keyring import KeyRing
from app.shared.files.service.core import rotate_data_key
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, field_codes

pytestmark = [pytest.mark.db, pytest.mark.valkey, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, used by name

SECRET = "AB 12345!"


def _with_keys(w: World) -> None:
    from pydantic import SecretStr  # noqa: PLC0415 - only these tests need keys

    if w.app.state.settings.files_keys is not None:
        return
    settings = w.app.state.settings.model_copy(
        update={"files_keys": SecretStr(KeyRing.generate()), "valkey_url": None}
    )
    w.app.state.settings = settings
    w.app.state.db.settings = settings


async def _sealed_field(w: World, org: Org, name: str) -> str:
    made = await w.call(
        "POST",
        "/custom-fields",
        org,
        org.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": name}},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    key = made.json()["key"]
    await w.sql(
        "UPDATE custom_fields SET sensitive = true, seal_state = 'sealed'"
        " WHERE tenant_id = $1 AND entity = 'incident' AND key = $2",
        org.tenant,
        key,
    )
    await _forget(w)
    return f"custom.{key}"


async def _forget(w: World) -> None:
    client = w.app.state.policy.cache.client
    prefix = w.app.state.settings.valkey_key_prefix
    stale = [k async for k in client.scan_iter(match=f"{prefix}*")]
    if stale:
        await client.delete(*stale)


async def _save(w: World, org: Org, user: uuid.UUID, **body: Any) -> Any:  # noqa: ANN401 - JSON
    return await w.call("POST", f"{BASE}/saved-views", org, user, json=body)


async def _stored(w: World, org: Org, view_id: str) -> dict[str, Any]:
    (row,) = await w.sql(
        "SELECT filter FROM work_item_views WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        uuid.UUID(view_id),
    )
    return dict(json.loads(row["filter"]))


async def _shown(w: World, org: Org, user: uuid.UUID, view_id: str) -> Any:  # noqa: ANN401 - JSON
    listed = (await w.call("GET", f"{BASE}/saved-views", org, user)).json()
    return next(v for v in listed if v["id"] == view_id)["filter"]


async def test_a_sealed_value_is_stored_sealed_and_opened_only_for_its_owner(
    world: World,
) -> None:
    _with_keys(world)
    a = world.a
    field = await _sealed_field(world, a, "Passport")
    tree = {"field": field, "op": "eq", "value": SECRET}
    made = await _save(world, a, a.admin, name="Mine", filter=tree)
    assert made.status_code == 201, made.text
    assert made.json()["filter"] == tree  # the response is the owner's form, opened
    stored = await _stored(world, a, made.json()["id"])
    assert stored["value"].startswith(TEXT_PREFIX)
    assert SECRET not in json.dumps(stored)
    assert await _shown(world, a, a.admin, made.json()["id"]) == tree
    # Renaming keeps the stored ciphertext (same view, same plaintext: nothing re-sealed).
    renamed = await world.call(
        "PATCH",
        f"{BASE}/saved-views/{made.json()['id']}",
        a,
        a.admin,
        json={"name": "Mine, renamed", "filter": tree},
        headers={"If-Match": f'"{made.json()["version"]}"'},
    )
    assert renamed.status_code == 200, renamed.text
    assert (await _stored(world, a, made.json()["id"]))["value"] == stored["value"]
    # History keeps no value and no sealed text (lane C's condition 6).
    history = await world.sql(
        "SELECT old_value::text AS o, new_value::text AS n FROM field_changes"
        " WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        uuid.UUID(made.json()["id"]),
    )
    assert all(SECRET not in f"{h['o']}{h['n']}" for h in history)
    assert all(TEXT_PREFIX not in f"{h['o']}{h['n']}" for h in history)


async def test_a_client_never_sends_sealed_text_and_a_copy_seals_afresh(world: World) -> None:
    _with_keys(world)
    a = world.a
    field = await _sealed_field(world, a, "Badge")
    tree = {"field": field, "op": "eq", "value": SECRET}
    first = (await _save(world, a, a.admin, name="First", filter=tree)).json()
    second = (await _save(world, a, a.admin, name="Second", filter=tree)).json()
    one = (await _stored(world, a, first["id"]))["value"]
    two = (await _stored(world, a, second["id"]))["value"]
    assert one != two  # the same plaintext, sealed for each view (lane C's condition 1)
    # Ciphertext from outside is refused (condition 2).
    pasted = await _save(world, a, a.admin, name="Pasted", filter={**tree, "value": one})
    assert field_codes(pasted) == {"filter": "view_filter_sealed_value"}
    # Moved raw into the other view, it does not open there: withheld, never shown.
    await world.sql(
        "UPDATE work_item_views SET filter = jsonb_set(filter, '{value}', to_jsonb($3::text))"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(second["id"]),
        one,
    )
    shown = await _shown(world, a, a.admin, second["id"])
    assert shown == {"field": field, "op": "eq", "value": None, "withheld": True}


async def test_a_field_the_owner_can_no_longer_see_is_withheld_and_kept_on_save(
    world: World,
) -> None:
    _with_keys(world)
    a = world.a
    field = await _sealed_field(world, a, "Grade")
    tree = {
        "and": [
            {"field": field, "op": "eq", "value": SECRET},
            {"field": "priority", "op": "eq", "value": "p1"},
        ]
    }
    made = (await _save(world, a, a.tech_a, name="Graded", filter=tree)).json()
    stored = await _stored(world, a, made["id"])
    await world.sql(
        "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
        " SELECT gen_random_uuid(), $1, id, 'incident', $2, 'hidden' FROM roles"
        " WHERE tenant_id = $1 AND key = 'technician'",
        a.tenant,
        field,
    )
    await _forget(world)
    shown = await _shown(world, a, a.tech_a, made["id"])
    assert shown["and"][0] == {"field": field, "op": "eq", "value": None, "withheld": True}
    assert SECRET not in json.dumps(shown)
    # Saved back with that condition untouched: the stored value stays as it was.
    saved = await world.call(
        "PATCH",
        f"{BASE}/saved-views/{made['id']}",
        a,
        a.tech_a,
        json={"filter": shown},
        headers={"If-Match": f'"{made["version"]}"'},
    )
    assert saved.status_code == 200, saved.text
    assert (await _stored(world, a, made["id"]))["and"][0] == stored["and"][0]


async def test_a_rotated_data_key_still_opens_a_view_saved_before_it(world: World) -> None:
    """Lane C's condition 4: a retired key still opens what it sealed (ADR-050 §3)."""
    _with_keys(world)
    a = world.a
    field = await _sealed_field(world, a, "Licence")
    tree = {"field": field, "op": "eq", "value": SECRET}
    before = (await _save(world, a, a.admin, name="Before", filter=tree)).json()
    ring = KeyRing.parse(world.app.state.settings.files_keys.get_secret_value())
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await rotate_data_key(session, ring)
    after = (await _save(world, a, a.admin, name="After", filter=tree)).json()

    def key_of(text: str) -> str | None:
        blob = from_text(text)
        return None if blob is None else key_id_of(blob)

    old = (await _stored(world, a, before["id"]))["value"]
    new = (await _stored(world, a, after["id"]))["value"]
    assert key_of(old) != key_of(new)  # the later view names the new data key
    assert await _shown(world, a, a.admin, before["id"]) == tree
    assert await _shown(world, a, a.admin, after["id"]) == tree


async def test_the_job_seals_what_was_stored_plain_and_runs_once(world: World) -> None:
    _with_keys(world)
    a = world.a
    field = await _sealed_field(world, a, "Account")
    made = (
        await _save(
            world,
            a,
            a.admin,
            name="Old view",
            filter={"field": "priority", "op": "eq", "value": "p2"},
        )
    ).json()
    # As before this change: the sealed field's value written in plain text.
    await world.sql(
        "UPDATE work_item_views SET filter = $3::jsonb WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(made["id"]),
        json.dumps({"field": field, "op": "eq", "value": SECRET}),
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await view_audit.audit_all(session)
    stored = await _stored(world, a, made["id"])
    assert stored["value"].startswith(TEXT_PREFIX)
    assert SECRET not in json.dumps(stored)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await view_audit.audit_all(session)
    assert (await _stored(world, a, made["id"]))["value"] == stored["value"]  # once only
    assert await _shown(world, a, a.admin, made["id"]) == {
        "field": field,
        "op": "eq",
        "value": SECRET,
    }
