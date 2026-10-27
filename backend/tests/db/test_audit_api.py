"""The audit log over HTTP and in the database (WP-018; REQ-AUD-001 to 010, 013; REQ-WI-021).

Real PostgreSQL and Valkey; the session is faked by headers. Uses the incidents test world (two
tenants with an admin, technicians and requesters). Tampering is done as the database superuser
on this test's throwaway database, never on dev data.
"""

import asyncio
import base64
import json
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from app.modules.audit.domain.integrity import GENESIS_HASH, chain_hash
from app.modules.audit.infra.signing import LocalSigner, new_key_config, trusted_keys
from app.modules.audit.service.erasure import erase_subject
from app.modules.audit.service.integrity import anchor, seal, verify
from app.modules.audit.service.jobs import seal_sweep
from conftest import assign_system_role, make_settings
from tests.db.test_access_api import fake_session
from tests.db.test_incidents_api import BASE, World, make_org, problem
from tests.db.test_rate_limit import valkey_url
from tests.db.test_users_api import seed_users
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]

CONSOLE = {"X-SupportX-Client": "console"}
SIGNER = LocalSigner.from_config(new_key_config("test-key-1"))
TRUSTED = trusted_keys("", SIGNER)


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    """The incidents test world (two tenants, admins, technicians, requesters)."""
    url = valkey_url()
    if url is None:
        pytest.skip("Valkey is not configured")
    app = create_app(
        make_settings(
            database_url=migrated_db.app_url,
            valkey_url=url,
            centrifugo_token_secret="audit-test-secret-" + "x" * 16,
        )
    )
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            w = World(client, migrated_db, app, a=None, b=None)  # type: ignore[arg-type]  # set below
            w.a = await make_org(w, "Alpha")
            w.b = await make_org(w, "Beta")
            yield w
            cache = app.state.policy.cache
            prefix = app.state.settings.valkey_key_prefix
            keys = [k async for k in cache.client.scan_iter(match=f"{prefix}*")]
            if keys:
                await cache.client.delete(*keys)


# --- helpers ------------------------------------------------------------------------------------


async def entries(world: World, org: Any, user: uuid.UUID, query: str = "") -> list[dict[str, Any]]:  # noqa: ANN401 - Org
    response = await world.call("GET", f"/audit/entries{query}", org, user)
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


async def by_action(world: World, org: Any, action: str) -> list[dict[str, Any]]:  # noqa: ANN401 - Org
    return await entries(world, org, org.admin, f"?action={action}&limit=200")


async def seal_all(world: World, org: Any) -> int:  # noqa: ANN401 - Org
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        return await seal(session, 500)


async def run_verify(world: World, org: Any, **values: Any) -> Any:  # noqa: ANN401 - result
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        return await verify(session, kind="on_demand", trusted_keys=TRUSTED, **values)


async def sql(world: World, statement: str, *args: Any) -> Any:  # noqa: ANN401 - asyncpg
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        return await conn.fetch(statement, *args)
    finally:
        await conn.close()


async def auditor(world: World, org: Any) -> uuid.UUID:  # noqa: ANN401 - Org
    (user,) = await seed_users(
        world.db, org.tenant, [{"user_type": "technician", "display_name": "Ayesha Auditor"}]
    )
    await assign_system_role(world.db.admin_url, org.tenant, user, "auditor")
    return user


async def new_role(world: World, org: Any, name: str) -> dict[str, Any]:  # noqa: ANN401 - Org
    created = await world.call(
        "POST",
        "/roles",
        org,
        org.admin,
        json={"name": name, "permissions": [{"permission": "roles.view", "scope": "all"}]},
        headers=CONSOLE,
    )
    assert created.status_code == 201, created.text
    return dict(created.json())


# --- REQ-AUD-001: tamper-evident, append-only, per tenant ---------------------------------------


async def test_req_aud_001_database_and_python_build_the_same_chain(world: World) -> None:
    a = world.a
    await new_role(world, a, "Chain check")
    assert await seal_all(world, a) > 0
    rows = await sql(
        world,
        "SELECT seq, entry_hash, prev_hash, chain_hash FROM audit_chain"
        " WHERE tenant_id = $1 ORDER BY seq",
        a.tenant,
    )
    previous = GENESIS_HASH
    for row in rows:
        assert row["prev_hash"] == previous
        assert row["chain_hash"] == chain_hash(a.tenant, row["seq"], previous, row["entry_hash"])
        previous = row["chain_hash"]
    assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1))


async def test_req_aud_001_ac1_changing_an_entry_fails_verification_and_names_it(
    world: World,
) -> None:
    a = world.a
    role = await new_role(world, a, "Tamper me")
    await seal_all(world, a)
    assert (await run_verify(world, a)).status == "passed"
    (target,) = [
        e for e in await by_action(world, a, "role.created") if e["object_id"] == role["id"]
    ]
    await sql(
        world,
        "UPDATE audit_entries SET details = '{\"grants_added\": []}'::jsonb WHERE id = $1",
        uuid.UUID(target["id"]),
    )
    result = await run_verify(world, a)
    assert result.status == "failed"
    assert str(result.finding.entry_id) == target["id"]
    assert result.finding.problem.value == "entry_changed"


async def test_req_aud_001_ac2_deleting_an_entry_is_detected(world: World) -> None:
    a = world.a
    await new_role(world, a, "Delete me")
    await seal_all(world, a)
    (row,) = await sql(
        world,
        "SELECT entry_id, entry_occurred_at FROM audit_chain WHERE tenant_id = $1"
        " ORDER BY seq LIMIT 1 OFFSET 2",
        a.tenant,
    )
    await sql(
        world,
        "DELETE FROM audit_entries WHERE id = $1 AND occurred_at = $2",
        row["entry_id"],
        row["entry_occurred_at"],
    )
    result = await run_verify(world, a)
    assert (result.status, result.finding.problem.value) == ("failed", "entry_missing")
    assert result.finding.seq == 3


async def test_req_aud_001_ac3_the_app_role_cannot_change_or_delete(world: World) -> None:
    rows = await sql(
        world,
        "SELECT t, has_table_privilege('supportx_app', t, 'UPDATE') AS u,"
        " has_table_privilege('supportx_app', t, 'DELETE') AS d,"
        " has_table_privilege('supportx_app', t, 'TRUNCATE') AS tr"
        " FROM unnest(ARRAY['audit_entries', 'audit_chain', 'audit_personal', 'audit_queue',"
        " 'audit_anchors']) AS t",
    )
    assert all(not (r["u"] or r["d"] or r["tr"]) for r in rows), [dict(r) for r in rows]
    # And the chain can only be written by the sealing function.
    (insert,) = await sql(
        world, "SELECT has_table_privilege('supportx_app', 'audit_chain', 'INSERT')"
    )
    assert insert[0] is False


async def test_req_aud_001_ac4_each_tenant_has_its_own_chain(world: World) -> None:
    a, b = world.a, world.b
    await new_role(world, a, "A only")
    await new_role(world, b, "B only")
    await seal_all(world, a)
    await seal_all(world, b)
    for org in (a, b):
        (first,) = await sql(
            world, "SELECT min(seq) AS s FROM audit_chain WHERE tenant_id = $1", org.tenant
        )
        assert first["s"] == 1
    seen_by_b = {e["id"] for e in await entries(world, b, b.admin, "?limit=200")}
    a_ids = {e["id"] for e in await entries(world, a, a.admin, "?limit=200")}
    assert seen_by_b.isdisjoint(a_ids)
    one = next(iter(a_ids))
    assert (await world.call("GET", f"/audit/entries/{one}", b, b.admin)).status_code == 404


async def test_concurrent_sealing_never_duplicates_or_skips_positions(world: World) -> None:
    a = world.a
    for i in range(30):
        await new_role(world, a, f"Busy {i}")
    await asyncio.gather(*(seal_all(world, a) for _ in range(5)))
    rows = await sql(
        world, "SELECT seq FROM audit_chain WHERE tenant_id = $1 ORDER BY seq", a.tenant
    )
    assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1))
    (pending,) = await sql(
        world, "SELECT count(*) AS n FROM audit_queue WHERE tenant_id = $1", a.tenant
    )
    assert pending["n"] == 0
    assert (await run_verify(world, a)).status == "passed"


# --- REQ-AUD-002: what is audited ---------------------------------------------------------------


async def test_req_aud_002_ac1_each_privileged_action_writes_exactly_one_entry(
    world: World,
) -> None:
    a = world.a

    async def count(action: str) -> int:
        return len(await by_action(world, a, action))

    before = {
        code: await count(code)
        for code in (
            "role.created",
            "role.updated",
            "role.deleted",
            "user.role_assigned",
            "user.role_removed",
            "site.created",
            "site.changed",
            "site.member_added",
            "site.member_removed",
            "incident.settings_changed",
            "incident.category_created",
            "incident.category_changed",
            "incident.deleted",
            "incident.restored",
            "announcement.settings_changed",
            "audit.settings_changed",
        )
    }
    role = await new_role(world, a, "Every action")
    patched = await world.call(
        "PATCH",
        f"/roles/{role['id']}",
        a,
        a.admin,
        json={"permissions": [{"permission": "users.view", "scope": "all"}]},
        headers={"If-Match": f'"{role["version"]}"'},
    )
    assert patched.status_code == 200, patched.text
    assert (
        await world.call("PUT", f"/users/{a.tech_a}/roles/{role['id']}", a, a.admin)
    ).status_code == 204
    assert (
        await world.call("DELETE", f"/users/{a.tech_a}/roles/{role['id']}", a, a.admin)
    ).status_code == 204
    deleted = await world.call(
        "DELETE",
        f"/roles/{role['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{patched.json()["version"]}"'},
    )
    assert deleted.status_code == 204, deleted.text
    site = await world.call("POST", "/organization/sites", a, a.admin, json={"name": "Audit site"})
    site_id = site.json()["id"]
    renamed = await world.call(
        "PATCH",
        f"/organization/sites/{site_id}",
        a,
        a.admin,
        json={"name": "Audit site 2"},
        headers={"If-Match": '"1"'},
    )
    assert renamed.status_code == 200, renamed.text
    assert (
        await world.call("PUT", f"/organization/sites/{site_id}/members/{a.tech_b}", a, a.admin)
    ).status_code in {200, 204}
    assert (
        await world.call("DELETE", f"/organization/sites/{site_id}/members/{a.tech_b}", a, a.admin)
    ).status_code in {200, 204}
    settings = await world.call("GET", f"{BASE}/settings", a, a.admin)
    changed = await world.call(
        "PATCH",
        f"{BASE}/settings",
        a,
        a.admin,
        json={"prefix": "INX"},
        headers={"If-Match": settings.headers["ETag"]},
    )
    assert changed.status_code == 200, changed.text
    category = await world.call(
        "POST", f"{BASE}/categories", a, a.admin, json={"labels": {"en": "Audit cat"}}
    )
    assert category.status_code == 201, category.text
    category_patch = await world.call(
        "PATCH",
        f"{BASE}/categories/{category.json()['id']}",
        a,
        a.admin,
        json={"labels": {"en": "Audit cat 2"}},
        headers={"If-Match": f'"{category.json()["version"]}"'},
    )
    assert category_patch.status_code == 200, category_patch.text
    item = await world.create(a, a.admin)
    assert (
        await world.call("DELETE", f"{BASE}/{item['id']}", a, a.admin, headers={"If-Match": '"1"'})
    ).status_code == 204
    assert (
        await world.call(
            "POST", f"{BASE}/{item['id']}/restore", a, a.admin, headers={"If-Match": '"2"'}
        )
    ).status_code == 200
    announcement = await world.call(
        "PUT",
        "/announcements/settings",
        a,
        a.admin,
        json={"require_second_publisher": True},
        headers={"If-Match": '"0"'},
    )
    assert announcement.status_code == 200, announcement.text
    audit_settings = await world.call(
        "PUT",
        "/audit/settings",
        a,
        a.admin,
        json={"read_window_minutes": 15},
        headers={"If-Match": '"0"'},
    )
    assert audit_settings.status_code == 200, audit_settings.text

    for code, was in before.items():
        assert await count(code) == was + 1, code


# --- REQ-AUD-003: what an entry shows -----------------------------------------------------------


async def test_req_aud_003_ac1_role_change_shows_grants_actor_and_ip(world: World) -> None:
    a = world.a
    role = await new_role(world, a, "Grants")
    response = await world.call(
        "PATCH",
        f"/roles/{role['id']}",
        a,
        a.admin,
        json={"permissions": [{"permission": "users.view", "scope": "all"}]},
        headers={"If-Match": f'"{role["version"]}"', **CONSOLE},
    )
    assert response.status_code == 200, response.text
    (entry,) = [
        e for e in await by_action(world, a, "role.updated") if e["object_id"] == role["id"]
    ]
    assert entry["details"]["grants_added"] == ["users.view:all"]
    assert entry["details"]["grants_removed"] == ["roles.view:all"]
    assert (entry["actor_id"], entry["actor_name"], entry["client"]) == (
        str(a.admin),
        "Alpha Admin",
        "console",
    )
    # AC3: the request ID leads to the trace.
    assert entry["request_id"] == response.headers["X-Request-ID"]
    detail = (await world.call("GET", f"/audit/entries/{entry['id']}", a, a.admin)).json()
    assert detail["personal"][0]["subject_id"] == str(a.admin)
    assert detail["personal"][0]["ip"]  # the test client's address
    assert len(detail["entry_hash"]) == 64
    assert "grants" not in json.dumps(detail["personal"])  # personal values are only personal


# --- REQ-AUD-004: reads of sensitive data -------------------------------------------------------


async def test_req_aud_004_sensitive_reads_are_logged_once_per_window(world: World) -> None:
    a = world.a

    async def reads() -> list[dict[str, Any]]:
        found = await by_action(world, a, "read.access_information")
        return [e for e in found if e["actor_id"] == str(a.admin)]

    before = len(await reads())
    assert (await world.call("GET", "/roles", a, a.admin)).status_code == 200
    assert len(await reads()) == before + 1  # AC1
    assert (await world.call("GET", "/roles", a, a.admin)).status_code == 200
    assert len(await reads()) == before + 1  # same window: coalesced
    # AC2: opening an incident is an everyday read, never logged.
    item = await world.create(a, a.admin)
    assert (await world.get(a, a.admin, item)).status_code == 200
    logged = await entries(world, a, a.admin, "?category=reads&limit=200")
    assert not [e for e in logged if e["object_id"] == item["id"]]
    # AC3: switching a category off stops logging it; switching it on starts again.
    off = await world.call(
        "PUT",
        "/audit/settings",
        a,
        a.admin,
        json={"read_categories": ["audit_log"]},
        headers={"If-Match": '"0"'},
    )
    assert off.status_code == 200, off.text
    assert off.json()["read_categories"] == ["audit_log"]
    role_id = (await world.call("GET", "/roles", a, a.admin)).json()[0]["id"]
    assert (await world.call("GET", f"/roles/{role_id}", a, a.admin)).status_code == 200
    assert len(await reads()) == before + 1
    on = await world.call(
        "PUT",
        "/audit/settings",
        a,
        a.admin,
        json={"read_categories": ["audit_log", "access_information"]},
        headers={"If-Match": '"1"'},
    )
    assert on.status_code == 200, on.text
    assert (await world.call("GET", f"/roles/{role_id}", a, a.admin)).status_code == 200
    assert len(await reads()) == before + 2


# --- REQ-AUD-005: refused attempts --------------------------------------------------------------


async def test_req_aud_005_refusals_are_logged_and_probing_alerts_once(world: World) -> None:
    a = world.a
    for i in range(10):
        refused = await world.call(
            "POST",
            "/roles",
            a,
            a.tech_a,
            json={"name": f"Nope {i}", "permissions": []},
        )
        assert refused.status_code == 403
    attempts = [
        e
        for e in await entries(world, a, a.admin, f"?actor_id={a.tech_a}&outcome=refused&limit=200")
        if e["action"] == "role.created"
    ]
    assert len(attempts) == 10  # AC1
    assert attempts[0]["reason_code"] == "permission_denied"
    alerts = [
        e
        for e in await by_action(world, a, "audit.probing_detected")
        if e["object_id"] == str(a.tech_a)
    ]
    assert len(alerts) == 1  # AC2: one alert, not one per refusal
    assert alerts[0]["details"]["refusals"] >= 10
    await world.call("POST", "/roles", a, a.tech_a, json={"name": "Eleventh", "permissions": []})
    again = [
        e
        for e in await by_action(world, a, "audit.probing_detected")
        if e["object_id"] == str(a.tech_a)
    ]
    assert len(again) == 1  # at most once an hour


# --- REQ-AUD-006: linked with field history -----------------------------------------------------


async def test_req_aud_006_ac1_entry_and_history_link_each_other(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    assert (
        await world.call("DELETE", f"{BASE}/{item['id']}", a, a.admin, headers={"If-Match": '"1"'})
    ).status_code == 204
    (entry,) = [
        e for e in await by_action(world, a, "incident.deleted") if e["object_id"] == item["id"]
    ]
    assert entry["change_id"] is not None
    history = await sql(
        world,
        "SELECT DISTINCT change_id FROM field_changes WHERE record_id = $1 AND kind = 'deleted'",
        uuid.UUID(item["id"]),
    )
    assert str(history[0]["change_id"]) == entry["change_id"]
    linked = await entries(world, a, a.admin, f"?change_id={entry['change_id']}")
    assert [e["id"] for e in linked] == [entry["id"]]


# --- REQ-AUD-007: search ------------------------------------------------------------------------


async def test_req_aud_007_ac1_filter_by_actor_and_last_seven_days(world: World) -> None:
    a = world.a
    await new_role(world, a, "Recent")
    old = await new_role(world, a, "Old one")
    (old_entry,) = [
        e for e in await by_action(world, a, "role.created") if e["object_id"] == old["id"]
    ]
    await sql(
        world,
        "UPDATE audit_entries SET occurred_at = occurred_at - interval '20 days' WHERE id = $1",
        uuid.UUID(old_entry["id"]),
    )
    week = json.dumps({"field": "occurred_at", "op": "last_n_days", "value": 7})
    found = await entries(world, a, a.admin, f"?actor_id={a.admin}&filter={week}&limit=200")
    assert found
    assert all(e["actor_id"] == str(a.admin) for e in found)
    assert old_entry["id"] not in {e["id"] for e in found}


# --- REQ-AUD-008: who may read; separation of duties --------------------------------------------


async def test_req_aud_008_who_may_read_and_auditors_change_nothing(world: World) -> None:
    a = world.a
    who = await auditor(world, a)
    for user in (a.lead, a.tech_a, a.requester):
        assert problem(await world.call("GET", "/audit/entries", a, user)) == (404, "not_found")
    assert (await world.call("GET", "/audit/entries", a, who)).status_code == 200
    assert (await world.call("GET", "/audit/status", a, who)).status_code == 200
    # Auditors verify, but cannot change settings, roles or anything else.
    started = await world.call("POST", "/audit/verification-runs", a, who, json={})
    assert started.status_code == 202, started.text
    assert problem(
        await world.call(
            "PUT",
            "/audit/settings",
            a,
            who,
            json={"retention_days": 365},
            headers={"If-Match": '"0"'},
        )
    ) == (404, "not_found")
    assert (
        await world.call("POST", "/roles", a, who, json={"name": "x", "permissions": []})
    ).status_code == 403
    refusals = await entries(world, a, a.admin, f"?actor_id={who}&outcome=refused")
    assert {e["action"] for e in refusals} == {"audit.settings_changed", "role.created"}


# --- REQ-AUD-010: verification ------------------------------------------------------------------


async def test_req_aud_010_clean_run_counts_and_a_broken_chain_alerts_once(world: World) -> None:
    a = world.a
    await new_role(world, a, "Verify")
    await seal_all(world, a)
    clean = await run_verify(world, a)
    assert clean.status == "passed"
    assert clean.entries_checked > 0  # AC1
    status = (await world.call("GET", "/audit/status", a, a.admin)).json()
    assert status["alert"] is None
    (row,) = await sql(
        world,
        "SELECT entry_id FROM audit_chain WHERE tenant_id = $1 ORDER BY seq DESC LIMIT 1",
        a.tenant,
    )
    await sql(world, "UPDATE audit_entries SET outcome = 'failed' WHERE id = $1", row["entry_id"])
    broken = await run_verify(world, a)
    assert broken.status == "failed"
    assert str(broken.finding.entry_id) == str(row["entry_id"])  # AC2
    alerts = await by_action(world, a, "audit.verification_failed")
    assert len([e for e in alerts if e["object_id"] == str(broken.run_id)]) == 1
    status = (await world.call("GET", "/audit/status", a, a.admin)).json()
    assert status["alert"] == "entry_changed"  # the banner stays until a full run passes
    runs = (await world.call("GET", "/audit/verification-runs", a, a.admin)).json()
    assert runs[0]["first_broken_entry_id"] == str(row["entry_id"])


async def test_unsealed_entries_show_pending_and_alert_after_the_limit(world: World) -> None:
    a = world.a
    role = await new_role(world, a, "Pending")
    (entry,) = [
        e for e in await by_action(world, a, "role.created") if e["object_id"] == role["id"]
    ]
    assert entry["seq"] is None  # "pending seal" until the sealer runs
    await sql(
        world,
        "UPDATE audit_queue SET occurred_at = occurred_at - interval '10 minutes'"
        " WHERE entry_id = $1",
        uuid.UUID(entry["id"]),
    )
    await sql(  # the entry too, so the sealer still finds it (time travel, not tampering)
        world,
        "UPDATE audit_entries SET occurred_at = occurred_at - interval '10 minutes' WHERE id = $1",
        uuid.UUID(entry["id"]),
    )
    status = (await world.call("GET", "/audit/status", a, a.admin)).json()
    assert (status["pending_overdue"], status["alert"]) == (1, "unsealed_overdue")
    settings = make_settings(database_url=world.db.app_url)
    await seal_sweep(world.app.state.db, settings)  # seals it; nothing is lost
    sealed = [e for e in await by_action(world, a, "role.created") if e["object_id"] == role["id"]]
    assert sealed[0]["seq"] is not None


# --- anchors and key rotation -------------------------------------------------------------------


async def test_anchors_sign_detect_truncation_and_survive_key_rotation(world: World) -> None:
    a = world.a
    await new_role(world, a, "Anchor")
    await seal_all(world, a)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        first = await anchor(session, SIGNER, every=timedelta(0))
    assert first is not None
    assert (await run_verify(world, a)).status == "passed"
    # Rotation: a new key signs from now on; the old key stays trusted for old anchors.
    new_signer = LocalSigner.from_config(new_key_config("test-key-2"))
    rotated = trusted_keys(f"test-key-1:{base64.b64encode(SIGNER.public_key).decode()}", new_signer)
    await new_role(world, a, "After rotation")
    await seal_all(world, a)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await anchor(session, new_signer, every=timedelta(0)) is not None
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await verify(session, kind="on_demand", trusted_keys=rotated)).status == "passed"
    # Without the old key, its anchor is not trusted.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        untrusted = await verify(
            session, kind="on_demand", trusted_keys=trusted_keys("", new_signer)
        )
    assert untrusted.finding is not None
    assert untrusted.finding.problem.value == "anchor_signature"
    # Truncation: delete the newest entry and its link; the newest anchor gives it away.
    (last,) = await sql(
        world,
        "SELECT seq, entry_id, entry_occurred_at FROM audit_chain WHERE tenant_id = $1"
        " ORDER BY seq DESC LIMIT 1",
        a.tenant,
    )
    await sql(
        world, "DELETE FROM audit_chain WHERE tenant_id = $1 AND seq = $2", a.tenant, last["seq"]
    )
    await sql(world, "DELETE FROM audit_entries WHERE id = $1", last["entry_id"])
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        truncated = await verify(session, kind="on_demand", trusted_keys=rotated)
    assert truncated.finding is not None
    assert truncated.finding.problem.value == "anchor_beyond_chain"


# --- REQ-AUD-013: erasure keeps the chain verifiable --------------------------------------------


async def test_req_aud_013_erasure_removes_personal_data_and_the_chain_still_verifies(
    world: World,
) -> None:
    b = world.b  # its own tenant: no other test tampers with it
    person = b.lead
    for i in range(3):
        await world.call("GET", "/roles", b, b.admin)
        await world.call("POST", "/roles", b, person, json={"name": f"Try {i}", "permissions": []})
    await seal_all(world, b)
    before = await entries(world, b, b.admin, f"?actor_id={person}&limit=200")
    assert before
    (personal,) = await sql(
        world,
        "SELECT count(*) AS n FROM audit_personal WHERE tenant_id = $1 AND subject_id = $2",
        b.tenant,
        person,
    )
    assert personal["n"] > 0
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        removed = await erase_subject(session, person)
    assert removed == personal["n"]
    (left,) = await sql(
        world,
        "SELECT count(*) AS n FROM audit_personal WHERE tenant_id = $1 AND subject_id = $2",
        b.tenant,
        person,
    )
    assert left["n"] == 0
    await seal_all(world, b)
    assert (await run_verify(world, b)).status == "passed"  # AC1
    after = await entries(world, b, b.admin, f"?actor_id={person}&limit=200")
    assert {e["id"] for e in before} <= {e["id"] for e in after}  # AC2: still grouped
    detail = (await world.call("GET", f"/audit/entries/{before[0]['id']}", b, b.admin)).json()
    assert detail["personal"] == []
    assert len(await by_action(world, b, "audit.subject_erased")) == 1


# --- settings -------------------------------------------------------------------------------------


async def test_settings_limits_versions_and_their_audit_trail(world: World) -> None:
    b = world.b
    current = await world.call("GET", "/audit/settings", b, b.admin)
    body = current.json()
    assert (body["retention_days"], body["read_window_minutes"], body["refusal_threshold"]) == (
        1095,
        10,
        10,
    )
    too_short = await world.call(
        "PUT",
        "/audit/settings",
        b,
        b.admin,
        json={"retention_days": 30},
        headers={"If-Match": current.headers["ETag"]},
    )
    assert too_short.status_code == 422
    assert too_short.json()["errors"][0]["params"] == {"min": 365, "max": 3650}
    changed = await world.call(
        "PUT",
        "/audit/settings",
        b,
        b.admin,
        json={"retention_days": 730},
        headers={"If-Match": current.headers["ETag"]},
    )
    assert changed.status_code == 200, changed.text
    stale = await world.call(
        "PUT",
        "/audit/settings",
        b,
        b.admin,
        json={"retention_days": 900},
        headers={"If-Match": current.headers["ETag"]},
    )
    assert problem(stale) == (409, "version_conflict")
    done = [
        e for e in await by_action(world, b, "audit.settings_changed") if e["outcome"] == "done"
    ]
    (entry,) = done
    failed = await entries(world, b, b.admin, "?action=audit.settings_changed&outcome=failed")
    assert {e["reason_code"] for e in failed} == {"validation_failed", "version_conflict"}
    assert entry["details"]["changes"] == {"retention_days": {"old": 1095, "new": 730}}
    assert entry["change_id"] is not None


async def test_on_demand_verification_is_requested_and_audited(world: World) -> None:
    b = world.b
    started = await world.call("POST", "/audit/verification-runs", b, b.admin, json={})
    assert started.status_code == 202, started.text
    run = started.json()
    assert run["status"] == "running"
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        done = await verify(
            session, kind="on_demand", trusted_keys=TRUSTED, run_id=uuid.UUID(run["id"])
        )
    assert done.run_id == uuid.UUID(run["id"])
    (requested,) = await by_action(world, b, "audit.verification_requested")
    assert requested["object_id"] == run["id"]
    backwards = await world.call(
        "POST",
        "/audit/verification-runs",
        b,
        b.admin,
        json={"range_from": "2026-10-02T00:00:00Z", "range_to": "2026-10-01T00:00:00Z"},
    )
    assert backwards.status_code == 422


async def test_sessions_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    await new_role(world, a, "RLS")
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in (
            "audit_entries",
            "audit_chain",
            "audit_personal",
            "audit_queue",
            "audit_anchors",
        ):
            rows = (await session.execute(text(f"SELECT tenant_id FROM {table}"))).all()  # noqa: S608 - fixed names
            assert {r[0] for r in rows} <= {b.tenant}, table
