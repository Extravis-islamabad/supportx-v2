"""Fine-grained access to assets and CIs, narrow-only (ADR-053; D-172; WP-053 S3a; 0183).

- Rules only narrow what a role's scope shows; across roles the clearest wins; never a grant.
- Applied at every choke point through `scope_filter`: the record (404 outside the set), lists,
  `visible_ci_ids`, neighbours, versions, the type counts, writes, and asset lookups.
- The effective view is the person's own compile; `roles.manage` or the person themself.
- A lapse keeps every rule applying; rules can still be viewed and removed, not added.
- The assets' managing group is the real `group` scope in every edition.
- The rules table is isolated per tenant (RLS).

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h). Each test
makes its own roles and takes them away again, as the world is shared by the module.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.cmdb import visible_ci_ids
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_assets_api import _add as add_asset
from tests.db.test_assets_api import _product
from tests.db.test_cmdb_api import _ci, _types
from tests.db.test_incidents_api import Org, World, problem, role, unit
from tests.db.test_knowledge_api import _match, _new

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

RULES = "/resource-access/rules"


async def _edition(world: World, org: Org, edition: str) -> None:
    await world.sql(
        "UPDATE tenant_subscriptions SET edition = $2 WHERE tenant_id = $1", org.tenant, edition
    )
    client = world.app.state.policy.cache.client
    prefix = world.app.state.settings.valkey_key_prefix
    keys = [k async for k in client.scan_iter(match=f"{prefix}*")]
    if keys:
        await client.delete(*keys)


@asynccontextmanager
async def _holding(
    world: World, org: Org, user: uuid.UUID, grants: list[tuple[str, str]]
) -> AsyncIterator[uuid.UUID]:
    """A new role with `grants`, held by `user` for the block, then taken away."""
    made = await role(world, org, f"S3a {uuid.uuid4().hex[:6]}", grants)
    assigned = await world.call("PUT", f"/users/{user}/roles/{made}", org, org.admin)
    assert assigned.status_code == 204, assigned.text
    try:
        yield made
    finally:
        await world.call("DELETE", f"/users/{user}/roles/{made}", org, org.admin)


async def _rule(
    world: World, org: Org, role_id: uuid.UUID, resource: str, criteria: dict[str, Any]
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "POST",
        RULES,
        org,
        org.admin,
        json={"role_id": str(role_id), "resource": resource, "criteria": criteria},
        headers=_new(),
    )


async def _made(world: World, org: Org, name: str, type_code: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    found = await _ci(world, org, name, type_code, **extra)
    assert found.status_code == 201, found.text
    return dict(found.json())


async def test_the_rules_table_is_isolated_per_tenant(world: World) -> None:
    a, b = world.a, world.b
    await _edition(world, a, "enterprise")
    async with _holding(world, a, a.requester, [("cmdb.view", "all")]) as narrowed:
        types = await _types(world, a)
        made = await _rule(world, a, narrowed, "ci", {"type_ids": [types["server"]["id"]]})
        assert made.status_code == 201, made.text
        assert (await world.call("GET", RULES, b, b.admin)).json() == []
        seen = await world.sql(
            "SELECT count(*) AS n FROM role_resource_access WHERE tenant_id = $1", b.tenant
        )
        assert seen[0]["n"] == 0
        gone = await world.call(
            "DELETE", f"{RULES}/{made.json()['id']}", a, a.admin, headers={"If-Match": '"1"'}
        )
        assert gone.status_code == 204, gone.text


async def test_a_rule_narrows_cis_at_every_choke_point(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    server = await _made(world, a, "Narrow server", "server", site_id=str(a.s1))
    database = await _made(world, a, "Narrow database", "database", site_id=str(a.s1))
    types = await _types(world, a)
    grants = [("cmdb.view", "all"), ("cmdb.edit", "all")]
    async with _holding(world, a, a.requester, grants) as narrowed:
        rule = await _rule(world, a, narrowed, "ci", {"type_ids": [types["server"]["id"]]})
        assert rule.status_code == 201, rule.text
        me = a.requester
        assert (await world.call("GET", f"/cmdb/cis/{server['id']}", a, me)).status_code == 200
        # The record, its neighbours and its versions: 404 outside the set, never 403.
        for path in ("", "/neighbours", "/versions"):
            found = await world.call("GET", f"/cmdb/cis/{database['id']}{path}", a, me)
            assert problem(found) == (404, "cmdb_ci_not_found"), path
        listed = (await world.call("GET", "/cmdb/cis?limit=200", a, me)).json()["items"]
        ids = {c["id"] for c in listed}
        assert server["id"] in ids
        assert database["id"] not in ids
        # The type counts count only what the reader may see (lane C 2).
        counted = {
            t["api_name"]: t["ci_count"]
            for t in (await world.call("GET", "/cmdb/ci-types", a, me)).json()["items"]
        }
        assert counted["database"] == 0
        # A write on a CI outside the set: 404 (lane C 1).
        edited = await world.call(
            "PATCH", f"/cmdb/cis/{database['id']}", a, me, json={"name": "Renamed"},
            headers=_match(database["version"]),
        )  # fmt: skip
        assert problem(edited) == (404, "cmdb_ci_not_found")
        # The public subset other modules use for placeholders and counts.
        subject = await world.app.state.policy.subject(a.tenant, me)
        async with world.app.state.db.tenant_session(TenantContext(a.tenant, me)) as session:
            seen = await visible_ci_ids(
                session, subject, [uuid.UUID(server["id"]), uuid.UUID(database["id"])]
            )
        assert seen == {uuid.UUID(server["id"])}


async def test_the_clearest_role_wins_and_rules_never_grant(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    elsewhere = await _made(world, a, "Other site server", "server", site_id=str(a.s2))
    types = await _types(world, a)
    async with _holding(world, a, a.requester, [("cmdb.view", "all")]) as narrowed:
        made = await _rule(world, a, narrowed, "ci", {"type_ids": [types["database"]["id"]]})
        assert made.status_code == 201, made.text
        hidden = await world.call("GET", f"/cmdb/cis/{elsewhere['id']}", a, a.requester)
        assert problem(hidden) == (404, "cmdb_ci_not_found")
        async with _holding(world, a, a.requester, [("cmdb.view", "all")]):
            # A second role that sees CIs without a rule: the person isn't narrowed (D-172).
            again = await world.call("GET", f"/cmdb/cis/{elsewhere['id']}", a, a.requester)
            assert again.status_code == 200, again.text
    # Never a grant: a rule naming site 2 on a role scoped to site 1 shows nothing of site 2.
    async with _holding(world, a, a.requester, [("cmdb.view", "site")]) as site_role:
        made = await _rule(world, a, site_role, "ci", {"site_ids": [str(a.s2)]})
        assert made.status_code == 201, made.text
        refused = await world.call("GET", f"/cmdb/cis/{elsewhere['id']}", a, a.requester)
        assert problem(refused) == (404, "cmdb_ci_not_found")


async def test_the_effective_view_is_the_compile_and_its_readers(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    async with _holding(world, a, a.requester, [("cmdb.view", "all")]) as narrowed:
        made = await _rule(world, a, narrowed, "ci", {"type_ids": [types["server"]["id"]]})
        assert made.status_code == 201, made.text
        path = f"/people/{a.requester}/access-rules"
        own = await world.call("GET", path, a, a.requester)
        assert own.status_code == 200, own.text
        subject = await world.app.state.policy.subject(a.tenant, a.requester)
        reaches = subject.resource_access["ci"]  # the same compile as the person's access
        assert own.json()["narrowed"] == {
            "ci": {
                "rules": [
                    {k: list(v) if isinstance(v, tuple) else v for k, v in c.items()}
                    for reach in reaches
                    if reach.rules is not None
                    for c in reach.rules
                ],
                "whole_scope_roles": sum(1 for reach in reaches if reach.rules is None),
            }
        }
        assert own.json()["narrowed"]["ci"]["rules"] == [{"type_ids": [types["server"]["id"]]}]
        by_admin = await world.call("GET", path, a, a.admin)
        assert by_admin.status_code == 200, by_admin.text
        other = await world.call("GET", path, a, a.requester2)
        assert other.status_code == 403, other.text


async def test_a_lapse_keeps_rules_applying_and_removal_working(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    database = await _made(world, a, "Lapse database", "database")
    types = await _types(world, a)
    async with _holding(world, a, a.requester, [("cmdb.view", "all")]) as narrowed:
        rule = (await _rule(world, a, narrowed, "ci", {"type_ids": [types["server"]["id"]]})).json()
        await _edition(world, a, "professional")
        refused = await _rule(world, a, narrowed, "ci", {"type_ids": [types["database"]["id"]]})
        assert problem(refused) == (403, "entitlement_required")
        changed = await world.call(
            "PATCH", f"{RULES}/{rule['id']}", a, a.admin,
            json={"criteria": {"type_ids": [types["database"]["id"]]}},
            headers={"If-Match": '"1"'},
        )  # fmt: skip
        assert problem(changed) == (403, "entitlement_required")
        still = await world.call("GET", f"/cmdb/cis/{database['id']}", a, a.requester)
        assert problem(still) == (404, "cmdb_ci_not_found")  # the rule still applies
        assert len((await world.call("GET", f"{RULES}?role_id={narrowed}", a, a.admin)).json()) == 1
        gone = await world.call(
            "DELETE", f"{RULES}/{rule['id']}", a, a.admin, headers={"If-Match": '"1"'}
        )
        assert gone.status_code == 204, gone.text
        shown = await world.call("GET", f"/cmdb/cis/{database['id']}", a, a.requester)
        assert shown.status_code == 200, shown.text
    await _edition(world, a, "enterprise")


@pytest.mark.parametrize("edition", ["professional", "enterprise"])
async def test_the_managing_group_is_the_group_scope_in_every_edition(
    world: World, edition: str
) -> None:
    a = world.a
    await _edition(world, a, edition)
    mine = await unit(world, a, "groups", f"Mine {uuid.uuid4().hex[:6]}", [a.requester])
    theirs = await unit(world, a, "groups", f"Theirs {uuid.uuid4().hex[:6]}", [])
    product = await _product(world, a, "laptop", f"Group laptop {uuid.uuid4().hex[:6]}")

    async def asset(name: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
        made = await add_asset(world, a, {"name": name, "product_id": product, **extra})
        assert made.status_code == 201, made.text
        return dict(made.json())

    managed = await asset("Managed by mine", managed_by_group_id=str(mine))
    others = await asset("Managed by theirs", managed_by_group_id=str(theirs))
    assert managed["managed_by_group_id"] == str(mine)
    async with _holding(world, a, a.requester, [("assets.view", "group")]):
        assert (
            await world.call("GET", f"/assets/{managed['id']}", a, a.requester)
        ).status_code == 200
        hidden = await world.call("GET", f"/assets/{others['id']}", a, a.requester)
        assert hidden.status_code == 404, hidden.text
    await _edition(world, a, "enterprise")


async def test_a_rule_narrows_assets_by_product_type(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    laptop = await _product(world, a, "laptop", f"Rule laptop {uuid.uuid4().hex[:6]}")
    made = await add_asset(world, a, {"name": "Narrowed laptop", "product_id": laptop})
    assert made.status_code == 201, made.text
    types = (await world.call("GET", "/assets/product-types", a, a.admin)).json()  # a plain list
    # A type outside the laptop's line: an ancestor (IT hardware, computer) would rightly cover it.
    others = [t["id"] for t in types if t["api_name"] == "phone"]
    async with _holding(world, a, a.requester, [("assets.view", "all")]) as narrowed:
        rule = await _rule(world, a, narrowed, "asset", {"product_type_ids": others})
        assert rule.status_code == 201, rule.text
        hidden = await world.call("GET", f"/assets/{made.json()['id']}", a, a.requester)
        assert hidden.status_code == 404, hidden.text


async def test_bad_criteria_and_unknown_resources_are_refused(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    async with _holding(world, a, a.requester, [("cmdb.view", "all")]) as narrowed:
        empty = await _rule(world, a, narrowed, "ci", {})
        assert empty.status_code == 422, empty.text
        unknown = await _rule(world, a, narrowed, "ci", {"colour": ["red"]})
        assert unknown.status_code == 422, unknown.text
        ceiling = await _rule(world, a, narrowed, "ci", {"criticality_max": "enormous"})
        assert ceiling.status_code == 422, ceiling.text
        fine = await _rule(world, a, narrowed, "ci", {"criticality_max": "high"})
        assert fine.status_code == 201, fine.text


async def _sees(world: World, org: Org, user: uuid.UUID, ci: dict[str, Any]) -> bool:
    found = await world.call("GET", f"/cmdb/cis/{ci['id']}", org, user)
    assert found.status_code in (200, 404), found.text
    return found.status_code == 200


async def test_each_role_shows_its_own_scope_narrowed_by_its_own_rules(world: World) -> None:
    """ADR-053 §2, the coordinator's case. Role A: every site, databases only. Role B: the
    person's site (S1), servers only. They see every database and S1's servers, never S2's."""
    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    s1_server = await _made(world, a, "S1 server", "server", site_id=str(a.s1))
    s2_server = await _made(world, a, "S2 server", "server", site_id=str(a.s2))
    s2_database = await _made(world, a, "S2 database", "database", site_id=str(a.s2))
    async with (
        _holding(world, a, a.requester, [("cmdb.view", "all")]) as role_a,
        _holding(world, a, a.requester, [("cmdb.view", "site")]) as role_b,
    ):
        for role_id, kind in ((role_a, "database"), (role_b, "server")):
            made = await _rule(world, a, role_id, "ci", {"type_ids": [types[kind]["id"]]})
            assert made.status_code == 201, made.text
        assert await _sees(world, a, a.requester, s2_database)  # A: every site, databases
        assert await _sees(world, a, a.requester, s1_server)  # B: S1, servers
        assert not await _sees(world, a, a.requester, s2_server)  # neither role allows it


async def test_a_role_without_a_rule_widens_nothing_beyond_its_own_scope(world: World) -> None:
    """Role A: the person's site (S1), no rule. Role B: every site, databases only. They see
    all of S1 and every database; never a server at S2 (A's lack of a rule lifts only A)."""
    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    s1_server = await _made(world, a, "Own-site server", "server", site_id=str(a.s1))
    s2_server = await _made(world, a, "Far server", "server", site_id=str(a.s2))
    s2_database = await _made(world, a, "Far database", "database", site_id=str(a.s2))
    async with (
        _holding(world, a, a.requester, [("cmdb.view", "site")]),
        _holding(world, a, a.requester, [("cmdb.view", "all")]) as role_b,
    ):
        made = await _rule(world, a, role_b, "ci", {"type_ids": [types["database"]["id"]]})
        assert made.status_code == 201, made.text
        assert await _sees(world, a, a.requester, s1_server)  # A: its site, whole
        assert await _sees(world, a, a.requester, s2_database)  # B: databases everywhere
        assert not await _sees(world, a, a.requester, s2_server)  # never: no role allows it


async def test_an_api_keys_scopes_still_apply_under_narrowing(world: World) -> None:
    """Lane C's #560 finding: a key without a scope gets nothing, narrowed owner or not.

    The narrowed branch of `scope_filter` built each role's reach from the role's own grants; an
    API key trims only the subject's grants (`for_key`). Without the check, a key lacking
    `cmdb:read` read its narrowed owner's CIs wherever a service filters by `cmdb.view` with no
    route check of its own (here cmdb's public `visible_ci_ids`, which other modules call). The
    control: a key with `cmdb:read` sees exactly the owner's narrowed set.
    """
    from app.modules.identity_access.service.policy import for_key  # noqa: PLC0415

    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    server = await _made(world, a, f"Key server {uuid.uuid4().hex[:6]}", "server")
    printer = await _made(world, a, f"Key printer {uuid.uuid4().hex[:6]}", "printer")
    wanted = [uuid.UUID(server["id"]), uuid.UUID(printer["id"])]
    async with _holding(world, a, a.requester, [("cmdb.view", "all")]) as narrowed:
        made = await _rule(world, a, narrowed, "ci", {"type_ids": [types["server"]["id"]]})
        assert made.status_code == 201, made.text
        owner = await world.app.state.policy.subject(a.tenant, a.requester)
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            assert await visible_ci_ids(session, owner, wanted) == {wanted[0]}  # narrowed
            full = for_key(owner, frozenset({"cmdb:read"}))
            assert await visible_ci_ids(session, full, wanted) == {wanted[0]}  # the control
            other = for_key(owner, frozenset({"incidents:read"}))
            assert await visible_ci_ids(session, other, wanted) == frozenset()  # no cmdb scope
