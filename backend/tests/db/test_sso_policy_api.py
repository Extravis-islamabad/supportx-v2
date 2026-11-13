"""Single sign-on required and break-glass admins (REQ-SEC-009; WP-057 S1b).

The coordinator's rules and lane B's: only a tenant admin names a break-glass admin, never
themselves; the person must be a tenant admin with MFA; requiring single sign-on needs one
(AC2), and the last one cannot go while it is required; every change is audited.
"""

import json
import uuid

import asyncpg
import httpx

from conftest import assign_system_role
from tests.db.test_access_api import Org
from tests.db.test_identity_api import World, _admin_rows, world

__all__ = ["world"]  # the fixture, re-used

POLICY = "/identity/sso-policy"


async def _sql(world: World, statement: str, *args: object) -> None:
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        await conn.execute(statement, *args)
    finally:
        await conn.close()


async def _version(world: World, user: uuid.UUID) -> int:
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        return int(await conn.fetchval("SELECT version FROM users WHERE id = $1", user))
    finally:
        await conn.close()


async def _mark(world: World, org: Org, user: uuid.UUID, **body: bool) -> httpx.Response:
    return await world.call(
        "PUT",
        f"/identity/break-glass/{user}",
        org,
        json={"break_glass": True, **body},
        headers={"If-Match": f'"{await _version(world, user)}"'},
    )


async def _second_admin(world: World, org: Org, *, mfa: bool) -> uuid.UUID:
    """The org's technician, made a tenant admin (with MFA enrolled if asked)."""
    await assign_system_role(world.db.admin_url, org.tenant, org.tech, "tenant_admin")
    if mfa:
        await _sql(world, "UPDATE users SET mfa_enrolled_at = now() WHERE id = $1", org.tech)
    return org.tech


async def test_req_sec_009_ac2_requiring_sso_needs_a_break_glass_admin(world: World) -> None:
    a = world.a
    shown = (await world.call("GET", POLICY, a)).json()
    admins = shown.pop("admins")
    assert shown == {
        "sso_required": "off",
        "sso_also_require_mfa": False,
        "break_glass_admins": 0,
        "version": 0,
    }
    assert [x["user_id"] for x in admins] == [str(a.admin)]  # the tenant's admins, named
    assert admins[0]["break_glass"] is False
    refused = await world.call(
        "PUT",
        POLICY,
        a,
        json={"sso_required": "everyone", "sso_also_require_mfa": False},
        headers={"If-Match": '"0"'},
    )
    assert (refused.status_code, refused.json()["code"]) == (
        409,
        "sso_required_needs_break_glass",
    )


async def test_a_break_glass_admin_is_another_tenant_admin_with_mfa(world: World) -> None:
    a = world.a
    # Never yourself (lane B).
    self_mark = await _mark(world, a, a.admin)
    assert (self_mark.status_code, self_mark.json()["code"]) == (403, "break_glass_not_self")
    # Not a tenant admin: refused.
    not_admin = await _mark(world, a, a.requester)
    assert (not_admin.status_code, not_admin.json()["code"]) == (409, "break_glass_needs_admin")
    # A tenant admin without MFA: refused; with it: named, audited.
    other = await _second_admin(world, a, mfa=False)
    no_mfa = await _mark(world, a, other)
    assert (no_mfa.status_code, no_mfa.json()["code"]) == (409, "break_glass_needs_mfa")
    await _sql(world, "UPDATE users SET mfa_enrolled_at = now() WHERE id = $1", other)
    named = await _mark(world, a, other)
    assert named.status_code == 200, named.text
    assert named.json()["break_glass"] is True
    (entry,) = await _admin_rows(
        world.db,
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2"
        " AND outcome = 'done'",
        a.tenant,
        "identity.break_glass_changed",
    )
    assert json.loads(entry["details"])["after"]["break_glass"] is True
    # An IP exemption only for a break-glass admin.
    exempt_alone = await world.call(
        "PUT",
        f"/identity/break-glass/{other}",
        a,
        json={"break_glass": False, "break_glass_ip_exempt": True},
        headers={"If-Match": f'"{await _version(world, other)}"'},
    )
    assert exempt_alone.json()["code"] == "break_glass_ip_exempt_needs_break_glass"


async def test_the_last_break_glass_admin_stays_while_sso_is_required(world: World) -> None:
    a = world.a
    other = await _second_admin(world, a, mfa=True)
    assert (await _mark(world, a, other)).status_code == 200
    required = await world.call(
        "PUT",
        POLICY,
        a,
        json={"sso_required": "technicians", "sso_also_require_mfa": False},
        headers={"If-Match": '"0"'},
    )
    assert required.status_code == 200, required.text
    assert (required.json()["sso_required"], required.json()["break_glass_admins"]) == (
        "technicians",
        1,
    )
    unmark = await world.call(
        "PUT",
        f"/identity/break-glass/{other}",
        a,
        json={"break_glass": False},
        headers={"If-Match": f'"{await _version(world, other)}"'},
    )
    assert (unmark.status_code, unmark.json()["code"]) == (409, "last_break_glass_admin")
    # The other tenant sees its own policy, untouched (RLS).
    assert (await world.call("GET", POLICY, world.b)).json()["sso_required"] == "off"


async def test_only_identity_managers_see_or_change_the_policy(world: World) -> None:
    a = world.a
    assert (await world.call("GET", POLICY, a, a.tech)).status_code == 403


async def test_req_sec_026_ac2_only_this_tenants_providers_ask_for_the_code(world: World) -> None:
    """Lane B: set on the tenant's own identity providers only, cleared when turned off."""
    a, b = world.a, world.b
    assert (await world.add_oidc(a)).status_code == 201
    (mine,) = set(world.admin.providers)  # the alias is Keycloak's, not in the API's answer
    assert (await world.add_oidc(b, domains=["beta.test"])).status_code == 201
    (theirs,) = set(world.admin.providers) - {mine}

    async def flow(alias: str) -> str:
        stored = await world.admin.provider(alias)
        assert stored is not None
        return str(stored.get("postBrokerLoginFlowAlias") or "")

    on = await world.call(
        "PUT",
        POLICY,
        a,
        json={"sso_required": "off", "sso_also_require_mfa": True},
        headers={"If-Match": '"0"'},
    )
    assert on.status_code == 200, on.text
    assert await flow(mine) == "supportx-otp-after-broker"
    assert await flow(theirs) == ""  # another tenant's provider is never touched
    off = await world.call(
        "PUT",
        POLICY,
        a,
        json={"sso_required": "off", "sso_also_require_mfa": False},
        headers={"If-Match": f'"{on.json()["version"]}"'},
    )
    assert off.status_code == 200, off.text
    assert await flow(mine) == ""
