"""Service accounts and the key policy (WP-057 S4a; REQ-SEC-036, REQ-SEC-037).

- The policy applies to new keys, the limit shown with the refusal (SEC-037 AC1); a stricter
  policy flags older keys and counts them before saving, never revokes them (the coordinator).
- Keys unused for the set time are listed (SEC-037 AC3).
- A service account's key acts as the account: what it makes names the account (SEC-036 AC2),
  and it never signs in. Its owner's deactivation flags it for hand-over (SEC-036 AC3).
- Another tenant sees none of it.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from app.core.tenancy import TenantContext
from app.modules.identity_access.service import service_account_handover
from app.shared.events import EventEnvelope
from tests.db.test_api_keys import _as_key, _make, _signed_in
from tests.db.test_auth_bff import Bff, bff  # noqa: F401 - the fixture, reused

pytestmark = pytest.mark.db


async def _settings(world: Bff, csrf: str, **values: Any) -> None:  # noqa: ANN401 - JSON
    current = (await world.client.get("/api/v1/identity/settings")).json()
    saved = await world.client.put(
        "/api/v1/identity/settings",
        json=values,
        headers={"X-CSRF-Token": csrf, "If-Match": f'"{current["version"]}"'},
    )
    assert saved.status_code == 200, saved.text


async def _sql(world: Bff, statement: str, *args: Any) -> list[asyncpg.Record]:  # noqa: ANN401
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        return list(await conn.fetch(statement, *args))
    finally:
        await conn.close()


async def _me(world: Bff) -> str:
    me = await world.me()
    assert me.status_code == 200, me.text
    return str(me.json()["user"]["id"])


def _days(n: int) -> str:
    return (datetime.now(UTC) + timedelta(days=n)).isoformat()


async def test_a_key_longer_than_the_policy_is_refused_with_the_limit(bff: Bff) -> None:  # noqa: F811
    """SEC-037 AC1: with a 90-day maximum, a one-year key is refused, the limit shown."""
    csrf = await _signed_in(bff)
    await _settings(bff, csrf, key_max_lifetime_days=90)
    refused = await _make(bff, csrf, expires_at=_days(365))
    assert refused.status_code == 422, refused.text
    (error,) = refused.json()["errors"]
    assert (error["code"], error["params"]) == ("api_key_expiry_too_far", {"max_days": 90})
    assert (await _make(bff, csrf, expires_at=_days(60))).status_code == 201


async def test_a_required_ip_range_refuses_a_key_without_one(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    await _settings(bff, csrf, keys_require_ip_range=True)
    refused = await _make(bff, csrf)
    assert refused.json()["errors"][0]["code"] == "api_key_ip_range_required", refused.text
    assert (await _make(bff, csrf, ip_allowlist=["10.0.0.0/8"])).status_code == 201


async def test_a_stricter_policy_flags_older_keys_and_never_revokes_them(bff: Bff) -> None:  # noqa: F811
    """The coordinator: counted before saving, listed after, still working."""
    csrf = await _signed_in(bff)
    made = (await _make(bff, csrf, expires_at=_days(300))).json()
    impact = await bff.client.get(
        "/api/v1/api-keys/policy-impact",
        params={"key_max_lifetime_days": 90, "keys_require_ip_range": "true"},
    )
    assert impact.status_code == 200, impact.text
    assert impact.json() == {"keys": 1, "lifetime_over_policy": 1, "no_ip_range": 1}
    await _settings(bff, csrf, key_max_lifetime_days=90, keys_require_ip_range=True)
    (row,) = [k for k in (await bff.client.get("/api/v1/api-keys")).json() if k["id"] == made["id"]]
    assert row["status"] == "active"
    assert sorted(row["out_of_policy"]) == ["lifetime_over_policy", "no_ip_range"]
    async with _as_key(bff, made["key"]) as api:
        assert (await api.get("/api/v1/users")).status_code == 200  # flagged, never revoked


async def test_a_key_unused_for_the_set_time_is_listed(bff: Bff) -> None:  # noqa: F811
    """SEC-037 AC3: made 100 days ago and never used, with a 90-day setting."""
    csrf = await _signed_in(bff)
    made = (await _make(bff, csrf)).json()
    fresh = (await _make(bff, csrf, name="Fresh")).json()
    await _sql(
        bff,
        "UPDATE api_keys SET created_at = now() - interval '100 days' WHERE id = $1",
        uuid.UUID(made["id"]),
    )
    listed = {k["id"]: k for k in (await bff.client.get("/api/v1/api-keys")).json()}
    assert listed[made["id"]]["unused"] is True
    assert listed[fresh["id"]]["unused"] is False


async def _account(world: Bff, csrf: str, owner: str, name: str = "Nightly sync") -> dict[str, Any]:
    made = await world.client.post(
        "/api/v1/service-accounts",
        json={"name": name, "description": "Pulls tickets into the data lake", "owner_id": owner},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert made.status_code == 201, made.text
    body: dict[str, Any] = made.json()
    return body


async def test_what_a_service_accounts_key_makes_names_the_account(bff: Bff) -> None:  # noqa: F811
    """SEC-036 AC1-AC2: no sign-in, no seat; its key acts as it and history names it."""
    csrf = await _signed_in(bff)
    admin = await _me(bff)
    account = await _account(bff, csrf, admin)
    assert account["managed_here"] is True
    assert account["needs_new_owner"] is False
    roles = (await bff.client.get(f"/api/v1/service-accounts/{account['id']}/roles")).json()
    technician = next(r for r in roles["offered"] if r["key"] == "technician")
    given = await bff.client.put(
        f"/api/v1/service-accounts/{account['id']}/roles/{technician['id']}",
        headers={"X-CSRF-Token": csrf},
    )
    assert given.status_code == 204, given.text
    (user,) = await _sql(
        bff,
        "SELECT can_sign_in, user_type, email FROM users WHERE id = $1",
        uuid.UUID(account["id"]),
    )
    assert (user["can_sign_in"], user["user_type"], user["email"]) == (False, "service", None)
    key = (
        await _make(bff, csrf, owner_id=account["id"], scopes=["incidents:read", "incidents:write"])
    ).json()["key"]
    async with _as_key(bff, key) as api:
        created = await api.post(
            "/api/v1/incidents",
            # A service account is never a requester: it records for a person.
            json={
                "subject": "From the data lake",
                "requester_id": admin,
                "confirm_lose_access": True,
                "keep_following": True,
            },
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
    assert created.status_code == 201, created.text
    (row,) = await _sql(
        bff, "SELECT created_by FROM work_items WHERE id = $1", uuid.UUID(created.json()["id"])
    )
    assert str(row["created_by"]) == account["id"]


async def test_an_owners_deactivation_flags_the_account_for_hand_over(bff: Bff) -> None:  # noqa: F811
    """SEC-036 AC3 (REQ-ADM-011): flagged, the event raised, the account still working."""
    csrf = await _signed_in(bff)
    owner = await bff.login(bff.user("a", email="owner@demo.test", roles=("technician",)))
    assert owner.status_code == 302, owner.text
    csrf = await _signed_in(bff)  # back as the admin
    (owner_row,) = await _sql(
        bff, "SELECT id, tenant_id FROM users WHERE email = 'owner@demo.test'"
    )
    account = await _account(bff, csrf, str(owner_row["id"]))
    await _sql(bff, "UPDATE users SET status = 'disabled' WHERE id = $1", owner_row["id"])
    listed = (await bff.client.get("/api/v1/service-accounts")).json()
    (shown,) = [a for a in listed if a["id"] == account["id"]]
    assert (shown["needs_new_owner"], shown["active"]) == (True, True)
    envelope = EventEnvelope.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "identity_access.user.status_changed",
            "schema_version": 1,
            "tenant_id": str(owner_row["tenant_id"]),
            "aggregate_type": "user",
            "aggregate_id": str(owner_row["id"]),
            "aggregate_version": 2,
            "occurred_at": datetime.now(UTC).isoformat(),
            "actor": {"type": "system", "id": "test"},
            "payload": {"user_id": str(owner_row["id"]), "status": "disabled"},
        }
    )
    async with bff.app.state.db.tenant_session(TenantContext(owner_row["tenant_id"])) as session:
        await service_account_handover.on_status_changed(envelope, session)
    events = await _sql(
        bff,
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'identity_access.service_account.needs_owner'",
        owner_row["tenant_id"],
    )
    payloads = [json.loads(e["envelope"])["payload"] for e in events]
    assert {"service_account_id": account["id"], "previous_owner_id": str(owner_row["id"])} in [
        {k: p[k] for k in ("service_account_id", "previous_owner_id")} for p in payloads
    ]


async def test_another_tenant_sees_no_service_account(bff: Bff) -> None:  # noqa: F811
    """Tenant isolation: tenant B's admin lists none of tenant A's service accounts."""
    csrf = await _signed_in(bff)
    account = await _account(bff, csrf, await _me(bff))
    other = await bff.login(bff.user("b", email="admin@other.test", roles=("tenant_admin",)))
    assert other.status_code == 302, other.text
    listed = await bff.client.get("/api/v1/service-accounts")
    assert listed.status_code == 200, listed.text
    assert account["id"] not in {a["id"] for a in listed.json()}
    missing = await bff.client.get(f"/api/v1/service-accounts/{account['id']}")
    assert missing.status_code == 404, missing.text
