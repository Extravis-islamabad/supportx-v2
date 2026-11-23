"""Single sign-on required at sign-in (REQ-SEC-009, REQ-SEC-026; WP-057 S1b).

AC1: with it required, a password sign-in is refused (the sign-in page offering no password is
Keycloak's organization redirect). AC3: a break-glass admin with MFA still gets in, which is
audited and alerts the other admins (an outbox event); without MFA they are refused. Requesters
are out of scope when only technicians are required. The method comes from the verified
token's `sx_idp` (lane B's condition 2) and is logged.
"""

import json
import uuid

import asyncpg
import pytest

from app.core.database import Database, create_engine
from app.core.errors import RateLimited
from app.core.tenancy import TenantContext
from app.modules.identity_access.bff import routes
from app.modules.notifications.service.engine import dispatch
from app.shared.api.ratelimit import AddressLimit
from app.shared.events import EventEnvelope
from tests.db.test_auth_bff import Bff, bff
from tests.db.test_notifications_api import NO_MAIL
from tooling.db_testing import ThrowawayDatabase

__all__ = ["bff"]  # the fixture, re-used


async def _sql(db: ThrowawayDatabase, statement: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(db.admin_url)
    try:
        return await conn.fetch(statement, *args)
    finally:
        await conn.close()


async def _require(db: ThrowawayDatabase, tenant: uuid.UUID, rule: str) -> None:
    await _sql(
        db,
        "INSERT INTO identity_settings (tenant_id, sso_required) VALUES ($1, $2) "
        "ON CONFLICT (tenant_id) DO UPDATE SET sso_required = EXCLUDED.sso_required",
        tenant,
        rule,
    )


def _email(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}@demo.test"


async def _provider(db: ThrowawayDatabase, tenant: uuid.UUID, alias: str) -> None:
    """The tenant's own identity provider `alias` (a brokered sign-in may only enter its owner)."""
    await _sql(
        db,
        "INSERT INTO sso_providers (id, tenant_id, alias, protocol, preset, display_name, state,"
        " created_at, updated_at) VALUES (gen_random_uuid(), $1, $2, 'oidc', 'entra', $2, 'on',"
        " now(), now()) ON CONFLICT (tenant_id, alias) DO NOTHING",
        tenant,
        alias,
    )


async def test_req_sec_009_ac1_a_password_sign_in_is_refused_and_sso_is_let_in(bff: Bff) -> None:
    a, _b = bff.tenants
    await _require(bff.db, a, "everyone")
    by_password = await bff.login(bff.user("a", email=_email("pw")))
    assert (by_password.status_code, by_password.json()["code"]) == (403, "sso_required")
    assert bff.cookie() is None
    assert len(bff.idp.ended_sessions) == 1  # Keycloak's own session ends too
    await _provider(bff.db, a, "acme-entra")
    sso = bff.user("a", email=_email("sso"), identity_provider="acme-entra")
    assert (await bff.login(sso)).status_code == 302
    rows = await _sql(
        bff.db,
        "SELECT outcome, reason, method, identity_provider FROM sign_in_events "
        "WHERE tenant_id = $1 ORDER BY occurred_at",
        a,
    )
    assert [tuple(r) for r in rows] == [
        ("failed", "sso_required", "password", None),
        ("success", None, "single_sign_on", "acme-entra"),
    ]


async def test_requesters_are_out_of_scope_when_only_technicians_are_required(bff: Bff) -> None:
    a, _b = bff.tenants
    await _require(bff.db, a, "technicians")
    requester = bff.user("a", email=_email("req"), roles=("requester",))
    assert (await bff.login(requester, app="portal")).status_code == 302


async def test_req_sec_009_ac3_a_break_glass_admin_gets_in_audited_and_alerted(bff: Bff) -> None:
    a, _b = bff.tenants
    email = _email("glass")
    # Another tenant admin, known to the tenant, who must hear of it.
    other = bff.user("a", email=_email("other-admin"), roles=("tenant_admin", "technician"))
    assert (await bff.login(other)).status_code == 302
    await bff.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": await bff.csrf()})
    admin = bff.user("a", email=email, roles=("tenant_admin", "technician"))
    assert (await bff.login(admin)).status_code == 302  # known to the tenant first
    await bff.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": await bff.csrf()})
    await _require(bff.db, a, "everyone")
    # Break-glass without MFA: refused.
    await _sql(bff.db, "UPDATE users SET break_glass = true WHERE email = $1", email)
    no_mfa = await bff.login(admin)
    assert (no_mfa.status_code, no_mfa.json()["code"]) == (403, "break_glass_needs_mfa")
    # With MFA: in, audited, and the other admins are told (the outbox event).
    await _sql(bff.db, "UPDATE users SET mfa_enrolled_at = now() WHERE email = $1", email)
    assert (await bff.login(admin)).status_code == 302
    audited = await _sql(
        bff.db,
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a,
        "session.break_glass_sign_in",
    )
    assert audited[0]["n"] == 1
    alerted = await _sql(
        bff.db,
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1 AND event_type = $2",
        a,
        "identity_access.break_glass.signed_in",
    )
    assert alerted[0]["n"] == 1
    # ...and the engine really delivers it: the other admin is told in the app (and by e-mail
    # once mail is set up), the emergency admin is not (a missing message template once made
    # this raise, so no admin was ever told).
    told = await _deliver(bff, a, "identity_access.break_glass.signed_in")
    assert ("break_glass.signed_in", other.email, "in_app", "sent") in told
    assert all(row[1] != email for row in told)


async def test_a_mobile_sso_sign_in_carries_its_method_and_is_let_in(bff: Bff) -> None:
    """Lane B: the app's tokens come from the console client (ADR-044), with `sx_idp` too."""
    from tests.db.test_auth_mobile import handoff_of, mobile_login, new_verifier  # noqa: PLC0415

    a, _b = bff.tenants
    await _require(bff.db, a, "everyone")
    await _provider(bff.db, a, "acme-entra")
    sso = bff.user("a", email=_email("phone"), identity_provider="acme-entra")
    answer = await mobile_login(bff, sso, new_verifier())
    assert handoff_of(answer)  # the hand-off back to the app: let in
    password = bff.user("a", email=_email("phone-pw"))
    refused = await mobile_login(bff, password, new_verifier())
    assert "auth_error=sso_required" in refused.headers["location"]
    rows = await _sql(
        bff.db,
        "SELECT outcome, method, app FROM sign_in_events WHERE tenant_id = $1 ORDER BY occurred_at",
        a,
    )
    assert [tuple(r) for r in rows] == [
        ("success", "single_sign_on", "mobile"),
        ("failed", "password", "mobile"),
    ]


async def test_a_break_glass_sign_in_over_its_budget_ends_both_sessions(
    bff: Bff, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lane B (#459): over the budget, ours ends and Keycloak's too, as the other refusals."""
    a, _b = bff.tenants
    email = _email("budget")
    admin = bff.user("a", email=email, roles=("tenant_admin", "technician"))
    assert (await bff.login(admin)).status_code == 302
    await bff.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": await bff.csrf()})
    await _require(bff.db, a, "everyone")
    await _sql(
        bff.db,
        "UPDATE users SET break_glass = true, mfa_enrolled_at = now() WHERE email = $1",
        email,
    )

    async def spent(request: object, response: object) -> AddressLimit:
        del request, response
        return AddressLimit(refusal=RateLimited(code="rate_limited"), headers={})

    monkeypatch.setattr(routes, "_BREAK_GLASS_LIMIT", spent)
    ended_before = len(bff.idp.ended_sessions)
    refused = await bff.login(admin)
    assert refused.status_code == 429, refused.text
    assert len(bff.idp.ended_sessions) == ended_before + 1  # Keycloak's session ended too
    assert (await bff.client.get("/api/v1/auth/me")).status_code == 401  # and ours never began


async def _deliver(bff: Bff, tenant: uuid.UUID, event_type: str) -> set[tuple[str, str, str, str]]:
    """Hand the tenant's events of `event_type` to the notification engine; what it delivered."""
    rows = await _sql(
        bff.db,
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2",
        tenant,
        event_type,
    )
    database = Database(create_engine(bff.db.app_url, application_name="test"))
    try:
        for row in rows:
            envelope = EventEnvelope.model_validate(json.loads(row["envelope"]))
            async with database.tenant_session(TenantContext(tenant)) as session:
                await dispatch(session, NO_MAIL, envelope)
    finally:
        await database.dispose()
    found = await _sql(
        bff.db,
        "SELECT d.event_code, u.email, d.channel, d.state FROM notification_deliveries d"
        " JOIN users u ON u.tenant_id = d.tenant_id AND u.id = d.user_id WHERE d.tenant_id = $1",
        tenant,
    )
    return {(r["event_code"], r["email"], r["channel"], r["state"]) for r in found}


# --- a brokered sign-in enters only the tenant owning its provider --------------------------------


async def test_a_provider_of_another_tenant_cannot_open_this_one(bff: Bff) -> None:
    """Every tenant shares one realm; tenant B's provider landing on an account of tenant A must
    never open tenant A: refused before anyone is looked up or created, and logged."""
    a, b = bff.tenants
    await _provider(bff.db, b, "b-idp")
    person = bff.user("a", email=_email("elsewhere"), identity_provider="b-idp")
    refused = await bff.login(person)
    assert (refused.status_code, refused.json()["code"]) == (403, "sso_provider_not_this_tenant")
    assert bff.cookie() is None
    made = await _sql(
        bff.db,
        "SELECT count(*) AS n FROM users WHERE tenant_id = $1 AND email = $2",
        a,
        person.email,
    )
    assert made[0]["n"] == 0


async def test_a_brokered_session_holds_only_its_providers_tenant(bff: Bff) -> None:
    """A person in both tenants signs in through tenant B's provider: the session opens B, its
    tenant list holds only B, and a switch to A is refused."""
    a, b = bff.tenants
    await _provider(bff.db, b, "b-idp-2")
    person = bff.user("a", "b", email=_email("both"), identity_provider="b-idp-2")
    assert (await bff.login(person)).status_code == 302
    me = (await bff.me()).json()
    assert me["tenant"]["id"] == str(b)
    assert [t["id"] for t in me["tenants"]] == [str(b)]
    switched = await bff.client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": str(a)},
        headers={"X-CSRF-Token": await bff.csrf()},
    )
    assert switched.status_code == 403
    assert (await bff.me()).json()["tenant"]["id"] == str(b)


async def test_a_password_sign_in_still_sees_every_tenant(bff: Bff) -> None:
    a, b = bff.tenants
    person = bff.user("a", "b", email=_email("pw-both"))
    assert (await bff.login(person)).status_code == 302
    tenants = {t["id"] for t in (await bff.me()).json()["tenants"]}
    assert tenants == {str(a), str(b)}


# --- D-177: an existing account's first sign-in through a provider is audited as a link ----------


async def _links(bff: Bff, tenant: uuid.UUID) -> list[asyncpg.Record]:
    return await _sql(
        bff.db,
        "SELECT object_type, object_id, details FROM audit_entries"
        " WHERE tenant_id = $1 AND action = 'identity_provider.account_linked'",
        tenant,
    )


async def test_d177_an_existing_accounts_first_provider_sign_in_is_audited_once(bff: Bff) -> None:
    a, _b = bff.tenants
    await _provider(bff.db, a, "a-link-idp")
    email = _email("linked")
    assert (await bff.login(bff.user("a", email=email))).status_code == 302  # by password
    before = len(await _links(bff, a))
    brokered = bff.user("a", email=email, identity_provider="a-link-idp")
    assert (await bff.login(brokered)).status_code == 302
    rows = await _links(bff, a)
    assert len(rows) == before + 1
    (row,) = rows[before:]
    assert row["object_type"] == "user"
    assert json.loads(row["details"])["identity_provider"] == "a-link-idp"
    person = await _sql(
        bff.db, "SELECT id FROM users WHERE tenant_id = $1 AND email = $2", a, email
    )
    assert row["object_id"] == str(person[0]["id"])
    # Signing in through the same provider again is no new link.
    assert (await bff.login(brokered)).status_code == 302
    assert len(await _links(bff, a)) == before + 1


async def test_d177_a_new_person_through_a_provider_is_no_link(bff: Bff) -> None:
    a, _b = bff.tenants
    await _provider(bff.db, a, "a-new-idp")
    before = len(await _links(bff, a))
    fresh = bff.user("a", email=_email("fresh"), identity_provider="a-new-idp")
    assert (await bff.login(fresh)).status_code == 302
    assert len(await _links(bff, a)) == before
