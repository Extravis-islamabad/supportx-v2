"""The security overview (WP-057 S4d): each tile equals its own screen (lane B's conditions).

1. Counts and codes only: no person's name or address anywhere in the answer.
2. Each tile's number equals what its own screen's endpoint shows (MFA, keys, service accounts).
3. The data region is the instance's setting and hidden when blank.
4. identity.manage, as the other identity reads; another tenant sees only its own numbers.
Flags are recommendations: a weak choice raises one, the recommended choice clears it.
"""

import dataclasses
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.identity_access.service.security_overview import overview
from tests.db.test_api_keys import _make, _signed_in
from tests.db.test_auth_bff import Bff, bff  # noqa: F401 - the fixture, reused
from tests.db.test_service_accounts_and_key_policy import _account, _me, _settings, _sql

pytestmark = pytest.mark.db
URL = "/api/v1/identity/security-overview"


async def _overview(world: Bff) -> dict[str, Any]:
    found = await world.client.get(URL)
    assert found.status_code == 200, found.text
    assert found.headers["cache-control"] == "no-store"
    body: dict[str, Any] = found.json()
    return body


def _codes(body: dict[str, Any]) -> set[str]:
    return {f["code"] for f in body["flags"]}


async def test_each_tile_equals_its_own_screen(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    me = await _me(bff)
    await _account(bff, csrf, me)  # one service account, owned
    made = await _make(bff, csrf, expires_at=(datetime.now(UTC) + timedelta(days=300)).isoformat())
    assert made.status_code == 201, made.text
    await _settings(bff, csrf, key_max_lifetime_days=90)  # the key is now out of policy
    body = await _overview(bff)

    # MFA: the same counts as GET /identity/mfa, over roles somebody holds.
    roles = [
        r for r in (await bff.client.get("/api/v1/identity/mfa")).json()["roles"] if r["holders"]
    ]
    assert body["mfa"] == {
        "roles": len(roles),
        "roles_required": sum(1 for r in roles if r["mode"] == "required"),
        "holders": sum(r["holders"] for r in roles),
        "enrolled": sum(r["enrolled"] for r in roles),
    }
    # Keys: the same flags as GET /api-keys.
    keys = [k for k in (await bff.client.get("/api/v1/api-keys")).json() if k["status"] == "active"]
    assert body["keys"] == {
        "active": len(keys),
        "out_of_policy": sum(1 for k in keys if k["out_of_policy"]),
        "unused": sum(1 for k in keys if k["unused"]),
    }
    assert body["keys"]["out_of_policy"] >= 1
    assert "keys_out_of_policy" in _codes(body)
    # Service accounts: the same list as GET /service-accounts.
    accounts = (await bff.client.get("/api/v1/service-accounts")).json()
    assert body["service_accounts"] == len(accounts)
    assert body["service_accounts_without_owner"] == sum(
        1 for a in accounts if a["needs_new_owner"]
    )
    # Settings: as GET /identity/settings says.
    current = (await bff.client.get("/api/v1/identity/settings")).json()
    assert body["password_min_length"] == current["password_min_length"]
    assert body["console_idle_seconds"] == current["console_idle_seconds"]


async def test_counts_and_codes_only(bff: Bff) -> None:  # noqa: F811
    """Lane B (1): no name, e-mail or address in the answer."""
    await _signed_in(bff)
    me = (await bff.me()).json()["user"]
    text = json.dumps(await _overview(bff))
    for personal in (me.get("display_name"), me.get("email"), str(me["id"])):
        if personal:
            assert personal not in text


async def test_a_weak_choice_raises_its_flag_and_the_recommended_one_clears_it(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    await _settings(bff, csrf, password_min_length=8)
    weak = await _overview(bff)
    assert "password_short" in _codes(weak)
    (flag,) = [f for f in weak["flags"] if f["code"] == "password_short"]
    assert (flag["area"], flag["severity"], flag["count"]) == ("passwords", "medium", 8)
    assert weak["recommendations"]["password_min_length"] == 12  # shown beside it, not enforced
    await _settings(bff, csrf, password_min_length=12)
    assert "password_short" not in _codes(await _overview(bff))


async def test_failed_sign_ins_are_counted_from_the_log(bff: Bff) -> None:  # noqa: F811
    await _signed_in(bff)
    (row,) = await _sql(bff, "SELECT tenant_id FROM users WHERE id = $1", uuid.UUID(await _me(bff)))
    for outcome, ago in (("failed", 1), ("failed", 2), ("locked", 1), ("failed", 9)):
        await _sql(
            bff,
            "INSERT INTO sign_in_events (id, tenant_id, occurred_at, outcome, method, app, source)"
            " VALUES ($1, $2, now() - make_interval(days => $3), $4, 'password', 'console', 'bff')",
            uuid.uuid4(),
            row["tenant_id"],
            ago,
            outcome,
        )
    body = await _overview(bff)
    assert (body["failed_sign_ins"], body["locked_sign_ins"]) == (2, 1)  # the 9-day one is out
    assert "sign_ins_locked" in _codes(body)


async def test_the_data_region_is_hidden_when_blank(bff: Bff) -> None:  # noqa: F811
    """Lane B (3): an instance setting, read only; blank hides the tile, never "unknown"."""
    await _signed_in(bff)
    assert (await _overview(bff))["data_region"] is None


async def test_identity_manage_only_and_each_tenant_its_own(bff: Bff) -> None:  # noqa: F811
    """Lane B (4): a technician is refused; tenant B sees none of tenant A's keys."""
    csrf = await _signed_in(bff)
    assert (await _make(bff, csrf)).status_code == 201
    assert (await _overview(bff))["keys"]["active"] >= 1
    tech = await bff.login(bff.user("a", email="tech@demo.test", roles=("technician",)))
    assert tech.status_code == 302, tech.text
    assert (await bff.client.get(URL)).status_code == 403
    other = await bff.login(bff.user("b", email="admin@other.test", roles=("tenant_admin",)))
    assert other.status_code == 302, other.text
    assert (await _overview(bff))["keys"]["active"] == 0


async def _as(world: Bff, keep: set[str]) -> Any:  # noqa: ANN401 - the service's Overview
    """The overview for the signed-in admin with only `keep` of their rights (a custom role)."""
    me = uuid.UUID(await _me(world))
    (row,) = await _sql(world, "SELECT tenant_id FROM users WHERE id = $1", me)
    tenant = row["tenant_id"]
    async with world.app.state.db.tenant_session(TenantContext(tenant, me)) as session:
        full = await subject_for(session, tenant, me)
        limited = dataclasses.replace(
            full, grants={k: v for k, v in full.grants.items() if k in keep}
        )
        return await overview(session, limited, world.app.state.settings, datetime.now(UTC))


async def test_identity_manage_alone_hides_the_tiles_it_may_not_see(bff: Bff) -> None:  # noqa: F811
    """Lane B (#537): no 403, no own-keys-only count; those tiles null, and no flag from them."""
    csrf = await _signed_in(bff)
    await _account(bff, csrf, await _me(bff))
    made = await _make(bff, csrf, expires_at=(datetime.now(UTC) + timedelta(days=300)).isoformat())
    assert made.status_code == 201, made.text
    await _settings(bff, csrf, key_max_lifetime_days=90)  # a key flag for those who may see it
    only = await _as(bff, {"identity.manage"})
    assert (only.keys, only.service_accounts, only.service_accounts_without_owner) == (
        None,
        None,
        None,
    )
    assert (only.failed_sign_ins, only.locked_sign_ins) == (None, None)
    assert set(only.tiles_hidden) == {"keys", "service_accounts", "sign_in_events"}
    assert not {f.area for f in only.flags} & {"keys", "service_accounts", "sign_in_events"}


async def test_with_the_key_right_the_counts_are_the_tenants_as_the_screens_show(bff: Bff) -> None:  # noqa: F811
    """Lane B (#537): identity.manage plus api_keys.manage counts every key, as GET /api-keys."""
    csrf = await _signed_in(bff)
    await _account(bff, csrf, await _me(bff))
    assert (await _make(bff, csrf)).status_code == 201
    both = await _as(bff, {"identity.manage", "api_keys.manage"})
    keys = [k for k in (await bff.client.get("/api/v1/api-keys")).json() if k["status"] == "active"]
    accounts = (await bff.client.get("/api/v1/service-accounts")).json()
    assert both.keys is not None
    assert both.keys.active == len(keys)
    assert both.service_accounts == len(accounts)
    assert set(both.tiles_hidden) == {"sign_in_events"}
