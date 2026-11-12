"""Single sign-on required at sign-in (REQ-SEC-009, REQ-SEC-026; WP-057 S1b).

AC1: with it required, a password sign-in is refused (the sign-in page offering no password is
Keycloak's organization redirect). AC3: a break-glass admin with MFA still gets in, which is
audited and alerts the other admins (an outbox event); without MFA they are refused. Requesters
are out of scope when only technicians are required. The method comes from the verified
token's `sx_idp` (lane B's condition 2) and is logged.
"""

import uuid

import asyncpg

from tests.db.test_auth_bff import Bff, bff
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


async def test_req_sec_009_ac1_a_password_sign_in_is_refused_and_sso_is_let_in(bff: Bff) -> None:
    a, _b = bff.tenants
    await _require(bff.db, a, "everyone")
    by_password = await bff.login(bff.user("a", email=_email("pw")))
    assert (by_password.status_code, by_password.json()["code"]) == (403, "sso_required")
    assert bff.cookie() is None
    assert len(bff.idp.ended_sessions) == 1  # Keycloak's own session ends too
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
