"""Field access per role over HTTP (ADR-047 slice a; REQ-WI-016, REQ-ADM-026) and lane B's terms.

- Rules: set, changed and removed by `roles.manage`, versioned, audited before and after, one
  event each; one live rule per role and field; at most 2,000 per tenant.
- The person's compiled subject has the rule on their next request, roles held through a group
  included; the clearest mode of their roles wins, and the effective view agrees with it.
- A lapsed licence keeps every rule applied; rules can still be viewed and removed, not added
  or changed.
- The table is isolated per tenant (RLS).
"""

import json
import uuid
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import Request

from app.core.recent_auth import SignInFreshness, record_freshness
from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.modules.identity_access.domain.field_access import to_json
from tests.db.test_access_api import Org, World, fake_session, problem, world  # noqa: F401
from tests.db.test_incidents_api import CONSOLE

RULES = "/field-access/rules"


async def _custom_field(world: World, org: Org, name: str = "Salary band") -> str:  # noqa: F811
    made = await world.call(
        "POST",
        "/custom-fields",
        org,
        org.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": name}},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    return f"custom.{made.json()['key']}"


async def _rule(
    world: World,  # noqa: F811
    org: Org,
    role_id: uuid.UUID,
    field: str,
    mode: str = "hidden",
    user: uuid.UUID | None = None,
) -> httpx.Response:
    return await world.call(
        "POST",
        RULES,
        org,
        user or org.admin,
        json={"role_id": str(role_id), "record_type": "incident", "field": field, "mode": mode},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )


async def _access(world: World, org: Org, user: uuid.UUID) -> dict[str, Any]:  # noqa: F811
    """The person's compiled field access, as their next request sees it (cache included)."""
    subject = await world.app.state.policy.subject(org.tenant, user)
    return to_json(subject.field_access)


async def _sql(world: World, statement: str, *args: Any) -> list[asyncpg.Record]:  # noqa: F811, ANN401
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        return list(await conn.fetch(statement, *args))
    finally:
        await conn.close()


async def _forget_caches(world: World) -> None:  # noqa: F811
    client = world.app.state.policy.cache.client
    keys = [
        k async for k in client.scan_iter(match=f"{world.app.state.settings.valkey_key_prefix}*")
    ]
    if keys:
        await client.delete(*keys)


async def _insert_as(
    conn: asyncpg.Connection, inside: uuid.UUID, owner: uuid.UUID, role_id: uuid.UUID
) -> None:
    """Inside tenant `inside`, try to write a rule belonging to tenant `owner`."""
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(inside))
        await conn.execute(
            "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
            " VALUES (gen_random_uuid(), $1, $2, 'incident', 'custom.x', 'hidden')",
            owner,
            role_id,
        )


async def test_a_rule_is_set_changed_and_removed_with_versions_audit_and_events(
    world: World,  # noqa: F811
) -> None:
    a = world.a
    field = await _custom_field(world, a)
    technician = await world.role_id(a, "technician")
    catalogue = (await world.call("GET", "/field-access/catalogue", a, a.admin)).json()
    incident = next(c for c in catalogue if c["record_type"] == "incident")
    assert field in {f["key"] for f in incident["fields"]}
    assert not {"subject", "status", "priority"} & {f["key"] for f in incident["fields"]}

    made = await _rule(world, a, technician, field)
    assert made.status_code == 201, made.text
    rule = made.json()
    assert (rule["mode"], rule["version"]) == ("hidden", 1)
    listed = (await world.call("GET", f"{RULES}?role_id={technician}", a, a.manager)).json()
    assert [r["id"] for r in listed] == [rule["id"]]

    stale = await world.call(
        "PATCH", f"{RULES}/{rule['id']}", a, a.admin, json={"mode": "masked"},
        headers={"If-Match": '"9"'},
    )  # fmt: skip
    assert problem(stale) == (409, "version_conflict")
    changed = await world.call(
        "PATCH", f"{RULES}/{rule['id']}", a, a.admin, json={"mode": "masked"},
        headers={"If-Match": '"1"'},
    )  # fmt: skip
    assert (changed.status_code, changed.json()["mode"]) == (200, "masked"), changed.text
    removed = await world.call(
        "DELETE", f"{RULES}/{rule['id']}", a, a.admin, headers={"If-Match": '"2"'}
    )
    assert removed.status_code == 204, removed.text
    assert (await world.call("GET", RULES, a, a.admin)).json() == []

    audits = await _sql(
        world,
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'role.field_access_changed' ORDER BY occurred_at",
        a.tenant,
    )
    entries = [dict(json.loads(r["details"])) for r in audits]
    assert {"status": 409} in entries  # the stale attempt is audited as refused
    details = [d for d in entries if "change" in d]
    assert [(d["change"], d["old_mode"], d["new_mode"]) for d in details] == [
        ("created", None, "hidden"),
        ("updated", "hidden", "masked"),
        ("deleted", "masked", None),
    ]
    events = await _sql(
        world,
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'identity_access.field_access.changed'",
        a.tenant,
    )
    assert len(events) == 3


async def test_what_is_refused(world: World) -> None:  # noqa: F811
    a = world.a
    field = await _custom_field(world, a)
    technician = await world.role_id(a, "technician")
    unknown = await _rule(world, a, technician, "subject")
    assert problem(unknown)[0] == 422  # a core field is never offered
    assert problem(await _rule(world, a, technician, field, user=a.tech)) == (
        403,
        "permission_denied",
    )
    assert (await _rule(world, a, technician, field)).status_code == 201
    assert problem(await _rule(world, a, technician, field, "masked")) == (
        409,
        "field_access_rule_exists",
    )
    other = await world.call(
        "POST",
        RULES,
        a,
        a.admin,
        json={"role_id": str(technician), "record_type": "spaceship", "field": field,
              "mode": "hidden"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )  # fmt: skip
    assert problem(other)[0] == 422


async def test_the_next_request_has_the_rule_roles_through_a_group_too(
    world: World,  # noqa: F811
) -> None:
    a = world.a
    field = await _custom_field(world, a)
    assert await _access(world, a, a.tech) == {}  # compiled and cached
    technician = await world.role_id(a, "technician")
    assert (await _rule(world, a, technician, field)).status_code == 201
    assert await _access(world, a, a.tech) == {"incident": {field: "hidden"}}

    # The manager holds a custom role and requester; a group gives them technician as well. The
    # requester role has no rule, so for them the field stays clear (clearest wins).
    group = await world.call("POST", "/organization/groups", a, a.admin, json={"name": "Desk"})
    group_id = group.json()["id"]
    assert (
        await world.call("PUT", f"/roles/{technician}/groups/{group_id}", a, a.admin)
    ).status_code == 204
    assert (
        await world.call("PUT", f"/organization/groups/{group_id}/members/{a.manager}", a, a.admin)
    ).status_code == 204
    assert await _access(world, a, a.manager) == {}
    requester = await world.role_id(a, "requester")
    rules = (await world.call("GET", RULES, a, a.admin)).json()
    custom_role = next(
        r["id"] for r in (await world.call("GET", "/roles", a, a.admin)).json()
        if r["name"] == "Access manager"
    )  # fmt: skip
    assert (await _rule(world, a, requester, field, "read_only")).status_code == 201
    assert (await _rule(world, a, uuid.UUID(custom_role), field, "masked")).status_code == 201
    # Every role of theirs now restricts it: the clearest of hidden, read_only, masked.
    assert await _access(world, a, a.manager) == {"incident": {field: "read_only"}}
    assert len(rules) == 1
    # Removing the group's rule clears it for the group member at once.
    tech_rule = next(r for r in (await world.call("GET", RULES, a, a.admin)).json()
                     if r["role_id"] == str(technician))  # fmt: skip
    gone = await world.call(
        "DELETE", f"{RULES}/{tech_rule['id']}", a, a.admin, headers={"If-Match": '"1"'}
    )
    assert gone.status_code == 204
    assert await _access(world, a, a.manager) == {}


async def test_who_sees_what_agrees_with_each_person_s_compiled_access(
    world: World,  # noqa: F811
) -> None:
    a = world.a
    field = await _custom_field(world, a)
    for key, mode in (("technician", "hidden"), ("tenant_admin", "masked")):
        assert (await _rule(world, a, await world.role_id(a, key), field, mode)).status_code == 201
    found = await world.call(
        "GET", f"/field-access/effective?record_type=incident&field={field}", a, a.admin
    )
    assert found.status_code == 200, found.text
    body = found.json()
    seen = {mode: {p["id"] for p in people} for mode, people in body["people"].items()}
    for user in (a.admin, a.manager, a.tech, a.requester):
        mode = (await _access(world, a, user)).get("incident", {}).get(field, "clear")
        assert str(user) in seen[mode], (user, mode, seen)
    assert seen["hidden"] >= {str(a.tech)}
    assert seen["masked"] >= {str(a.admin)}
    assert sum(body["counts"].values()) >= 4


async def test_a_lapsed_licence_keeps_rules_and_allows_only_viewing_and_removing(
    world: World,  # noqa: F811
) -> None:
    a = world.a
    field = await _custom_field(world, a)
    technician = await world.role_id(a, "technician")
    rule = (await _rule(world, a, technician, field)).json()
    await _sql(
        world, "UPDATE tenant_subscriptions SET edition = 'essentials' WHERE tenant_id = $1",
        a.tenant,
    )  # fmt: skip
    await _forget_caches(world)
    assert problem(await _rule(world, a, technician, await _custom_field(world, a, "Other"))) == (
        403,
        "entitlement_required",
    )
    refused = await world.call(
        "PATCH", f"{RULES}/{rule['id']}", a, a.admin, json={"mode": "masked"},
        headers={"If-Match": '"1"'},
    )  # fmt: skip
    assert problem(refused) == (403, "entitlement_required")
    assert await _access(world, a, a.tech) == {"incident": {field: "hidden"}}  # still applies
    assert len((await world.call("GET", RULES, a, a.admin)).json()) == 1
    gone = await world.call(
        "DELETE", f"{RULES}/{rule['id']}", a, a.admin, headers={"If-Match": '"1"'}
    )
    assert gone.status_code == 204, gone.text
    assert await _access(world, a, a.tech) == {}


async def test_at_most_two_thousand_rules(world: World) -> None:  # noqa: F811
    a = world.a
    field = await _custom_field(world, a)
    technician = await world.role_id(a, "technician")
    await _sql(
        world,
        "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
        " SELECT gen_random_uuid(), $1, $2, 'incident', 'custom.f' || n, 'hidden'"
        " FROM generate_series(1, 2000) AS n",
        a.tenant,
        technician,
    )
    assert problem(await _rule(world, a, technician, field)) == (
        422,
        "field_access_limit_reached",
    )


async def test_rules_are_isolated_per_tenant(world: World) -> None:  # noqa: F811
    a, b = world.a, world.b
    field = await _custom_field(world, a)
    rule = (await _rule(world, a, await world.role_id(a, "technician"), field)).json()
    assert (await world.call("GET", RULES, b, b.admin)).json() == []
    assert problem(
        await world.call("DELETE", f"{RULES}/{rule['id']}", b, b.admin, headers={"If-Match": '"1"'})
    ) == (404, "field_access_rule_not_found")
    # The app's own role, inside tenant B: reads none of A's rules, writes none for A.
    conn = await asyncpg.connect(world.db.app_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(b.tenant))
            assert await conn.fetch("SELECT id FROM role_field_access") == []
            updated = await conn.execute(
                "UPDATE role_field_access SET mode = 'masked' WHERE id = $1", uuid.UUID(rule["id"])
            )
            assert updated == "UPDATE 0"
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await _insert_as(conn, b.tenant, a.tenant, uuid.UUID(rule["role_id"]))
    finally:
        await conn.close()


async def _stale_session(request: Request) -> TenantContext | None:
    """Signed in through the browser, but the last confirmation is older than the window."""
    tenant, user = request.headers.get("x-test-tenant"), request.headers.get("x-test-user")
    if tenant is None:
        return None
    record_freshness(request, SignInFreshness(interactive=True, recent=False))
    return TenantContext(uuid.UUID(tenant), uuid.UUID(user) if user else None)


async def test_rule_changes_need_a_recent_confirmation(world: World) -> None:  # noqa: F811
    """REQ-SEC-027, lane B's #499 review: like role changes, a stale sign-in confirms first."""
    a = world.a
    field = await _custom_field(world, a)
    technician = await world.role_id(a, "technician")
    rule = (await _rule(world, a, technician, field)).json()
    other = await _custom_field(world, a, "B")
    setattr(world.app.state, SESSION_RESOLVER_STATE, _stale_session)
    try:
        assert problem(await _rule(world, a, technician, other)) == (
            403,
            "reauth_required",
        )
        changed = await world.call(
            "PATCH", f"{RULES}/{rule['id']}", a, a.admin, json={"mode": "masked"},
            headers={"If-Match": '"1"'},
        )  # fmt: skip
        assert problem(changed) == (403, "reauth_required")
        removed = await world.call(
            "DELETE", f"{RULES}/{rule['id']}", a, a.admin, headers={"If-Match": '"1"'}
        )
        assert problem(removed) == (403, "reauth_required")
        assert (await world.call("GET", RULES, a, a.admin)).status_code == 200  # reading: fine
    finally:
        setattr(world.app.state, SESSION_RESOLVER_STATE, fake_session)
