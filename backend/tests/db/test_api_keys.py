"""API keys end to end (WP-041; REQ-INT-019, 021, 023; D-128), through the real resolver.

Keys are made in a signed-in browser session (the BFF test world) and used with
`Authorization: Bearer sxk_…` from a client that holds no cookie.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import asyncpg
import httpx
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.identity_access.domain import api_keys as rules
from app.modules.identity_access.service.realtime import ROUTES
from app.shared.events import EventEnvelope
from tests.db.test_auth_bff import CONSOLE, Bff, bff  # noqa: F401 - the fixture, reused

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.db

ADMIN = ("tenant_admin", "technician")


async def _signed_in(world: Bff, *roles: str, email: str = "admin@demo.test") -> str:
    # D-129: a requester-only person signs in on the portal (the console sends them there).
    app = "portal" if roles == ("requester",) else "console"
    response = await world.login(world.user("a", email=email, roles=roles or ADMIN), app=app)
    assert response.status_code == 302, response.text
    return await world.csrf()


async def _make(world: Bff, csrf: str, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    payload = {"name": "Nightly export", "scopes": ["users:read"], **body}
    return await world.client.post(
        "/api/v1/api-keys",
        json=payload,
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
    )


def _as_key(world: Bff, key: str) -> httpx.AsyncClient:
    """A client with no session at all, only the key."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=world.app, raise_app_exceptions=False),
        base_url=CONSOLE,
        headers={"Authorization": f"Bearer {key}"},
    )


def _code(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json().get("code", "")


async def test_req_int_019_ac1_a_key_is_shown_once_then_only_its_last_four(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    made = await _make(bff, csrf)
    assert made.status_code == 201, made.text
    key = made.json()["key"]
    assert rules.parse_key(key) is not None
    assert made.json()["last_four"] == key[-4:]
    listed = (await bff.client.get("/api/v1/api-keys")).json()
    assert [k["last_four"] for k in listed] == [key[-4:]]
    assert all("key" not in k and "secret_hash" not in k for k in listed)
    # 90 days by default.
    expires = datetime.fromisoformat(made.json()["expires_at"])
    assert timedelta(days=89) < expires - datetime.now(UTC) <= rules.DEFAULT_LIFETIME


async def test_req_int_021_a_key_needs_the_scope_and_never_does_more_than_its_owner(
    bff: Bff,  # noqa: F811
) -> None:
    csrf = await _signed_in(bff)
    key = (await _make(bff, csrf, scopes=["users:read"])).json()["key"]
    async with _as_key(bff, key) as api:
        assert (await api.get("/api/v1/users")).status_code == 200
        # AC1: a read key on a create gets 403 with the scope it lacks.
        refused = await api.post(
            "/api/v1/users",
            json={"first_name": "Nope", "user_type": "requester"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert _code(refused) == (403, "api_scope_missing")
        assert refused.json()["params"] == {"scope": "users:write"}
        # Never the browser-only routes, and never a key that makes keys.
        assert _code(await api.get("/api/v1/api-keys")) == (403, "api_key_not_allowed")
        made_by_key = await api.post(
            "/api/v1/api-keys",
            json={"name": "x", "scopes": ["users:read"]},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert _code(made_by_key) == (403, "api_key_not_allowed")


async def test_a_requesters_key_cannot_exceed_the_requester(bff: Bff) -> None:  # noqa: F811
    admin_csrf = await _signed_in(bff)
    settings = await bff.client.get("/api/v1/identity/settings")
    allowed = await bff.client.put(
        "/api/v1/identity/settings",
        json={"people_may_create_keys": True},
        headers={"X-CSRF-Token": admin_csrf, "If-Match": f'"{settings.json()["version"]}"'},
    )
    assert allowed.status_code == 200, allowed.text
    csrf = await _signed_in(bff, "requester", email="requester@demo.test")
    key = (await _make(bff, csrf, scopes=["users:read", "users:write"])).json()["key"]
    async with _as_key(bff, key) as api:
        # The scope is there, the owner's permission is not: the owner's rule wins.
        assert _code(await api.get("/api/v1/users"))[0] == 403


async def test_a_key_outside_its_scope_is_told_which_scope_it_lacks(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)  # the owner may list incidents; the key only reads users
    key = (await _make(bff, csrf, scopes=["users:read"])).json()["key"]
    async with _as_key(bff, key) as api:
        refused = await api.get("/api/v1/incidents")
    assert _code(refused) == (403, "api_scope_missing")
    assert refused.json()["params"] == {"scope": "incidents:read"}


async def test_a_key_is_not_allowed_on_the_realtime_token_route(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    key = (await _make(bff, csrf)).json()["key"]
    async with _as_key(bff, key) as api:
        refused = await api.post(
            "/api/v1/realtime/subscription-token", json={"channel": "t:x:users"}
        )
    assert _code(refused) == (403, "api_key_not_allowed")


async def test_req_int_019_ac2_a_revoked_key_is_refused_on_its_next_call(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    made = (await _make(bff, csrf)).json()
    async with _as_key(bff, made["key"]) as api:
        assert (await api.get("/api/v1/users")).status_code == 200
        revoked = await bff.client.post(
            f"/api/v1/api-keys/{made['id']}/revoke", headers={"X-CSRF-Token": csrf}
        )
        assert revoked.json()["status"] == "revoked"
        assert _code(await api.get("/api/v1/users")) == (401, "api_key_revoked")


async def test_a_key_made_and_revoked_writes_outbox_events_without_its_text(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    made = (await _make(bff, csrf)).json()
    await bff.client.post(f"/api/v1/api-keys/{made['id']}/revoke", headers={"X-CSRF-Token": csrf})
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        rows = await conn.fetch(
            "SELECT envelope::text AS raw, envelope->'payload'->>'change' AS change"
            " FROM outbox_events WHERE event_type = 'identity_access.api_key.changed'"
            " AND aggregate_id = $1 ORDER BY id",
            made["id"],
        )
    finally:
        await conn.close()
    assert [r["change"] for r in rows] == ["created", "revoked"]
    # sxk_<tenant>_<key id>_<secret>: the IDs are base32 (no "_"), the secret base64url (may have
    # "_"), so split at the first three. rsplit took a short tail that could appear by chance.
    secret = made["key"].split("_", 3)[3]
    assert len(secret) >= 40
    assert all(secret not in r["raw"] and made["key"] not in r["raw"] for r in rows)
    # Live (rule c): key managers' list and the owner's own channel, IDs only.
    route = next(r for r in ROUTES if "identity_access.api_key.changed" in r.event_types)
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["raw"]))
    effects = await route.route(envelope, cast("AsyncSession", None))  # the route reads nothing
    channels = sorted(p.channel.name for p in effects.publications if p.ids)
    tenant = envelope.tenant_id
    assert channels == sorted([f"t:{tenant}:queue:api_keys", f"t:{tenant}:user:{made['owner_id']}"])
    assert {p.ids for p in effects.publications if p.ids} == {(made["id"],)}


async def test_req_int_019_ac3_another_address_is_refused_and_written_down(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    made = (await _make(bff, csrf, ip_allowlist=["10.0.0.0/8"])).json()
    async with _as_key(bff, made["key"]) as api:  # the test client calls from 127.0.0.1
        assert _code(await api.get("/api/v1/users")) == (403, "api_key_ip_refused")
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        rows = await conn.fetch(
            "SELECT action, object_id FROM audit_entries WHERE action = 'api_key.refused'"
        )
    finally:
        await conn.close()
    assert [(r["action"], r["object_id"]) for r in rows] == [("api_key.refused", made["id"])]


async def test_req_int_019_ac4_expiry_is_required_unless_the_tenant_allows_none(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    refused = await _make(bff, csrf, never_expires=True)
    assert refused.status_code == 422
    assert refused.json()["errors"][0]["code"] == "api_key_expiry_required"
    too_far = await _make(
        bff, csrf, expires_at=(datetime.now(UTC) + timedelta(days=400)).isoformat()
    )
    assert too_far.json()["errors"][0]["code"] == "api_key_expiry_too_far"
    settings = (await bff.client.get("/api/v1/identity/settings")).json()
    await bff.client.put(
        "/api/v1/identity/settings",
        json={"allow_non_expiring_keys": True},
        headers={"X-CSRF-Token": csrf, "If-Match": f'"{settings["version"]}"'},
    )
    allowed = await _make(bff, csrf, never_expires=True)
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["expires_at"] is None


async def test_the_key_screens_learn_what_they_may_offer_and_hear_when_it_changes(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    rules = (await bff.client.get("/api/v1/api-keys/rules")).json()
    assert rules == {
        "may_create": True,
        "manages_keys": True,
        "never_expires_allowed": False,
        "default_lifetime_days": 90,
        "max_lifetime_days": 366,
    }
    settings = (await bff.client.get("/api/v1/identity/settings")).json()
    saved = await bff.client.put(
        "/api/v1/identity/settings",
        json={"people_may_create_keys": True},
        headers={"X-CSRF-Token": csrf, "If-Match": f'"{settings["version"]}"'},
    )
    assert saved.status_code == 200, saved.text
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        raw = await conn.fetchval(
            "SELECT envelope::text FROM outbox_events"
            " WHERE event_type = 'identity_access.identity_settings.changed'"
            " ORDER BY id DESC LIMIT 1"
        )
    finally:
        await conn.close()
    route = next(r for r in ROUTES if "identity_access.identity_settings.changed" in r.event_types)
    effects = await route.route(
        EventEnvelope.model_validate(json.loads(raw)), cast("AsyncSession", None)
    )
    signals = [p for p in effects.publications if p.channel.kind == "broadcast"]
    assert [(p.type, p.ids) for p in signals] == [("api_keys.rules_changed", ())]
    # A requester, now allowed their own keys, but not a key manager.
    await _signed_in(bff, "requester", email="requester@demo.test")
    mine = (await bff.client.get("/api/v1/api-keys/rules")).json()
    assert (mine["may_create"], mine["manages_keys"]) == (True, False)


async def test_an_inactive_owner_or_a_tampered_key_is_refused(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    made = (await _make(bff, csrf)).json()
    key: str = made["key"]
    parsed = rules.parse_key(key)
    assert parsed is not None
    _, tenant_b = bff.tenants
    # The tenant inside the key is part of what it proves: another tenant finds no such key.
    forged = rules.make_key(tenant_b, parsed.key_id).text[: -len(parsed.secret)] + parsed.secret
    for bad in (key[:-1] + ("A" if key[-1] != "A" else "B"), forged, "sxk_nonsense"):
        async with _as_key(bff, bad) as api:
            assert _code(await api.get("/api/v1/users")) == (401, "api_key_invalid"), bad
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        owner = await conn.fetchval(
            "SELECT owner_id FROM api_keys WHERE id = $1", uuid.UUID(made["id"])
        )
        await conn.execute("UPDATE users SET status = 'disabled' WHERE id = $1", owner)
    finally:
        await conn.close()
    async with _as_key(bff, key) as api:
        assert _code(await api.get("/api/v1/users")) == (401, "api_key_owner_inactive")


async def test_req_int_023_one_idempotency_key_makes_one_api_key(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())}
    body = {"name": "Once", "scopes": ["users:read"]}
    first = await bff.client.post("/api/v1/api-keys", json=body, headers=headers)
    again = await bff.client.post("/api/v1/api-keys", json=body, headers=headers)
    assert first.json()["id"] == again.json()["id"]
    assert first.json()["key"] is not None
    assert again.json()["key"] is None  # the key text is never stored, not even for replays
    assert len((await bff.client.get("/api/v1/api-keys")).json()) == 1


async def test_api_keys_are_isolated_by_rls(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    made = (await _make(bff, csrf)).json()
    tenant_a, tenant_b = bff.tenants
    async with bff.app.state.db.tenant_session(TenantContext(tenant_b)) as session:
        assert await session.scalar(text("SELECT count(*) FROM api_keys")) == 0
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO api_keys (id, tenant_id, owner_id, name, scopes, secret_hash,"
                    " last_four) VALUES (:id, :other, :owner, 'x', ARRAY['users:read'], ''::bytea,"
                    " 'abcd')"
                ),
                {"id": uuid.uuid4(), "other": tenant_a, "owner": uuid.UUID(made["owner_id"])},
            )
    async with bff.app.state.db.tenant_session(TenantContext(tenant_a)) as session:
        assert await session.scalar(text("SELECT count(*) FROM api_keys")) == 1


async def _service_identity(world: Bff, name: str, *, status: str = "active") -> uuid.UUID:
    conn = await asyncpg.connect(world.db.admin_url)  # users has FORCED RLS
    try:
        user_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO users (id, tenant_id, display_name, first_name, user_type, can_sign_in,"
            " status)"
            " VALUES ($1, $2, $3, $3, 'service', false, $4)",
            user_id,
            world.tenants[0],
            name,
            status,
        )
        return user_id
    finally:
        await conn.close()


async def test_peo_14_key_managers_choose_owners_from_the_service_identities(bff: Bff) -> None:  # noqa: F811
    """The owner picker's own list: active service identities only, never people (WP-040 s2)."""
    jira = await _service_identity(bff, "Jira connector")
    await _service_identity(bff, "Removed connector", status="disabled")
    csrf = await _signed_in(bff)
    listed = await bff.client.get("/api/v1/api-keys/owners")
    assert listed.status_code == 200, listed.text
    assert listed.json() == [{"id": str(jira), "display_name": "Jira connector"}]
    # The one offered is the one the server accepts.
    made = await _make(bff, csrf, owner_id=str(jira))
    assert made.status_code == 201, made.text
    # The people list still never shows them.
    people = await bff.client.get("/api/v1/users")
    assert str(jira) not in {p["id"] for p in people.json()["items"]}


async def test_peo_14_only_key_managers_see_the_service_identities(bff: Bff) -> None:  # noqa: F811
    await _service_identity(bff, "Jira connector")
    await _signed_in(bff, "technician", email="tech-owners@demo.test")
    refused = await bff.client.get("/api/v1/api-keys/owners")
    assert refused.status_code == 403
