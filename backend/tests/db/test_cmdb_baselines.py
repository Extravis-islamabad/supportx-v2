"""CI baselines: save, list, compare, delete (WP-053 S7b; REQ-CMDB-033; 0209).

Pinned here: tenant isolation (RLS and over HTTP), `cmdb.manage` to save and delete, the outbox
event in the save's transaction (IDs and the action only), the compare through the reader's
ADR-047 rules (a hidden field absent from both sides, a masked one changed or not, never its
values), and a baseline's text reaching the erasure's mentions.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_custom_fields import _field, _made, _role_id, _rule
from tests.db.test_cmdb_mentions import _on, _patch, _redact
from tests.db.test_cmdb_relationships import _link
from tests.db.test_incidents_api import Org, World, problem, role
from tests.db.test_knowledge_api import _match, _new
from tests.db.test_person_erasure_api import _name, _request
from tests.db.test_person_erasure_mentions import _build, _mentions
from tests.db.test_users_api import seed_users

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

BASE = "/cmdb"


def _path(ci: dict[str, Any], *rest: str) -> str:
    return "/".join([f"{BASE}/cis/{ci['id']}/baselines", *rest])


async def _save(
    world: World, org: Org, ci: dict[str, Any], name: str, user: uuid.UUID | None = None
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "POST", _path(ci), org, user or org.admin, json={"name": name}, headers=_new()
    )


async def _saved(world: World, org: Org, ci: dict[str, Any], name: str) -> dict[str, Any]:
    made = await _save(world, org, ci, name)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _person(world: World, org: Org, name: str, grants: list[tuple[str, str]]) -> uuid.UUID:
    [person] = await seed_users(world.db, org.tenant, [{"user_type": "technician"}])
    made = await role(world, org, f"{name} {uuid.uuid4().hex[:6]}", grants)
    assigned = await world.call("PUT", f"/users/{person}/roles/{made}", org, org.admin)
    assert assigned.status_code == 204, assigned.text
    return person


# --- tenant isolation (rule a) --------------------------------------------------------------------


async def test_baselines_are_isolated_by_rls_and_over_http(world: World) -> None:
    a, b = world.a, world.b
    ci = await _made(world, a, f"RLS baseline host {uuid.uuid4().hex[:6]}", "server")
    baseline = await _saved(world, a, ci, "Before patching")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        mine = await session.execute(text("SELECT count(*) FROM cmdb_ci_baselines"))
        assert mine.scalar_one() > 0
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text("SELECT count(*) FROM cmdb_ci_baselines WHERE tenant_id = :a"), {"a": a.tenant}
        )
        assert seen.scalar_one() == 0
        changed = await session.execute(
            text("UPDATE cmdb_ci_baselines SET name = 'x' WHERE tenant_id = :a"), {"a": a.tenant}
        )
        assert changed.rowcount == 0
    for method, path in (
        ("GET", _path(ci)),
        ("GET", _path(ci, baseline["id"], "compare")),
    ):
        assert problem(await world.call(method, path, b, b.admin)) == (404, "cmdb_ci_not_found")
    refused = await world.call("POST", _path(ci), b, b.admin, json={"name": "x"}, headers=_new())
    assert problem(refused) == (404, "cmdb_ci_not_found")


# --- saving and deleting ------------------------------------------------------------------------


async def test_saving_needs_manage_and_raises_an_ids_only_event(world: World) -> None:
    a = world.a
    ci = await _made(world, a, f"Managed host {uuid.uuid4().hex[:6]}", "server")
    editor = await _person(world, a, "CI editor", [("cmdb.view", "all"), ("cmdb.edit", "all")])
    assert problem(await _save(world, a, ci, "Not mine", editor))[0] == 403
    manager = await _person(world, a, "CI manager", [("cmdb.view", "all"), ("cmdb.manage", "all")])
    key = _new()
    first = await world.call(
        "POST", _path(ci), a, manager, json={"name": "  Gold build  "}, headers=key
    )
    assert first.status_code == 201, first.text
    again = await world.call(
        "POST", _path(ci), a, manager, json={"name": "Gold build"}, headers=key
    )
    assert again.json()["id"] == first.json()["id"]  # the same Idempotency-Key: the same baseline
    saved = first.json()
    assert (saved["name"], saved["from_version"]) == ("Gold build", ci["version"])
    listed = await world.call("GET", _path(ci), a, editor)  # cmdb.view reads them
    assert [i["id"] for i in listed.json()["items"]] == [saved["id"]]
    rows = await world.sql(
        "SELECT envelope->'payload' AS payload FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'cmdb.baseline.changed' AND aggregate_id = $2",
        a.tenant,
        uuid.UUID(saved["id"]),
    )
    [payload] = [json.loads(r["payload"]) for r in rows]
    assert payload["action"] == "created"
    assert payload["ci_id"] == ci["id"]
    assert "Gold build" not in json.dumps(payload)  # IDs and the action only
    assert (
        problem(
            await world.call("POST", _path(ci), a, manager, json={"name": " "}, headers=_new())
        )[0]
        == 422
    )


async def test_delete_needs_if_match_and_hides_the_baseline(world: World) -> None:
    a = world.a
    ci = await _made(world, a, f"Deleted baseline host {uuid.uuid4().hex[:6]}", "server")
    baseline = await _saved(world, a, ci, "Short-lived")
    stale = await world.call(
        "DELETE", _path(ci, baseline["id"]), a, a.admin, headers=_match(baseline["version"] + 1)
    )
    assert problem(stale)[0] == 409
    done = await world.call(
        "DELETE", _path(ci, baseline["id"]), a, a.admin, headers=_match(baseline["version"])
    )
    assert done.status_code == 204, done.text
    assert (await world.call("GET", _path(ci), a, a.admin)).json()["items"] == []
    gone = await world.call("GET", _path(ci, baseline["id"], "compare"), a, a.admin)
    assert problem(gone) == (404, "cmdb_ci_baseline_not_found")
    (row,) = await world.sql(
        "SELECT deleted_at FROM cmdb_ci_baselines WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(baseline["id"]),
    )
    assert row["deleted_at"] is not None  # soft: kept for erasure and audit


# --- compare --------------------------------------------------------------------------------------


async def test_a_baseline_compares_with_now_and_with_another(world: World) -> None:
    a = world.a
    suffix = uuid.uuid4().hex[:6]
    ci = await _made(world, a, f"Compared host {suffix}", "server")
    first = await _saved(world, a, ci, "Before")
    ci = await _patch(world, a, ci, name=f"Compared host {suffix} (renamed)")
    db = await _made(world, a, f"Compared db {suffix}", "database")
    linked = await _link(world, a, ci, "depends_on", [db])
    assert linked.status_code == 201, linked.text
    second = await _saved(world, a, ci, "After")

    now = await world.call("GET", _path(ci, first["id"], "compare"), a, a.admin)
    assert now.status_code == 200, now.text
    body = now.json()
    assert [(c["field"], c["kind"]) for c in body["attributes"]] == [("name", "changed")]
    assert [r["ci"]["id"] for r in body["relationships_added"]] == [db["id"]]
    assert body["from_version"]["version"] == first["from_version"]

    pair = await world.call(
        "GET", _path(ci, first["id"], "compare"), a, a.admin, params={"against": second["id"]}
    )
    assert pair.status_code == 200, pair.text
    assert [c["field"] for c in pair.json()["attributes"]] == ["name"]
    same = await world.call(
        "GET", _path(ci, second["id"], "compare"), a, a.admin, params={"against": second["id"]}
    )
    assert same.json()["attributes"] == []
    other_ci = await _made(world, a, f"Other host {suffix}", "server")
    foreign = await _saved(world, a, other_ci, "Elsewhere")
    mixed = await world.call(
        "GET", _path(ci, first["id"], "compare"), a, a.admin, params={"against": foreign["id"]}
    )
    assert problem(mixed) == (404, "cmdb_ci_baseline_not_found")  # never another CI's baseline


async def test_hidden_fields_are_absent_and_masked_ones_say_only_changed(world: World) -> None:
    a = world.a
    hidden = (await _field(world, a, "Baseline cost code", None))["key"]
    masked = (await _field(world, a, "Baseline licence key", None))["key"]
    steady = (await _field(world, a, "Baseline asset tag", None))["key"]
    shown = (await _field(world, a, "Baseline rack", None))["key"]
    secret_old, secret_new, key_old, key_new = "CC-OLD-77", "CC-NEW-88", "LK-OLD-1", "LK-NEW-2"
    ci = await _made(
        world,
        a,
        f"Field access host {uuid.uuid4().hex[:6]}",
        "server",
        custom={hidden: secret_old, masked: key_old, steady: "TAG-9", shown: "Row 1"},
    )
    baseline = await _saved(world, a, ci, "Access baseline")
    ci = await _patch(world, a, ci, custom={hidden: secret_new, masked: key_new, shown: "Row 2"})
    reader = await role(world, a, f"Baseline reader {uuid.uuid4().hex[:6]}", [("cmdb.view", "all")])
    [person] = await seed_users(world.db, a.tenant, [{"user_type": "requester"}])
    assigned = await world.call("PUT", f"/users/{person}/roles/{reader}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    for role_id in (reader, await _role_id(world, a, "requester")):
        await _rule(world, a, role_id, f"custom.{hidden}", "hidden")
        await _rule(world, a, role_id, f"custom.{masked}", "masked")
        await _rule(world, a, role_id, f"custom.{steady}", "masked")

    seen = await world.call("GET", _path(ci, baseline["id"], "compare"), a, person)
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert [c["field"] for c in body["attributes"]] == [f"custom.{shown}"]
    assert {(m["field"], m["changed"]) for m in body["masked"]} == {
        (f"custom.{masked}", True),
        (f"custom.{steady}", False),
    }
    for side in ("from_version", "to_version"):
        assert f"custom.{hidden}" not in body[side]["fields"]
        assert f"custom.{masked}" not in body[side]["fields"]
    assert f"custom.{hidden}" not in seen.text  # hidden: not even named
    for value in (secret_old, secret_new, key_old, key_new, "TAG-9"):
        assert value not in seen.text

    full = await world.call("GET", _path(ci, baseline["id"], "compare"), a, a.admin)
    assert {c["field"] for c in full.json()["attributes"]} == {
        f"custom.{hidden}",
        f"custom.{masked}",
        f"custom.{shown}",
    }
    assert full.json()["masked"] == []


# --- erasure (the mentions port) ----------------------------------------------------------------


async def test_a_baselines_name_and_copy_are_found_and_redacted(world: World) -> None:
    a = world.a
    name = await _name(world, a, a.tech_a)
    ci = await _made(world, a, f"Kept by {name}", "server")
    baseline = await _saved(world, a, ci, f"Signed off by {name}")
    asked = await _request(world, a, a.admin, a.tech_a, successor_id=str(a.lead))
    assert asked.status_code == 201, asked.text
    erasure = dict(asked.json())
    await _build(world, a)
    page = await _mentions(world, a, erasure)
    own = [m for m in _on(page, "ci_baseline", "name") if m["record_id"] == baseline["id"]]
    copy = [
        m for m in _on(page, "ci_baseline_snapshot", "name") if m["record_id"] == baseline["id"]
    ]
    assert (len(own), len(copy)) == (1, 1)
    passage = await world.call(
        "GET", f"/erasures/{erasure['id']}/mentions/{own[0]['id']}/passage", a, a.admin
    )
    assert passage.status_code == 200, passage.text
    assert name in passage.text
    done = await _redact(world, a, erasure, [own[0]["id"], copy[0]["id"]])
    assert done.status_code == 200, done.text
    (row,) = await world.sql(
        "SELECT name, snapshot->>'name' AS copied, version FROM cmdb_ci_baselines"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(baseline["id"]),
    )
    assert name not in row["name"]
    assert name not in row["copied"]
    assert row["version"] == baseline["version"] + 2  # one update per redacted field
