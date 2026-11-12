"""IP allow-lists at sign-in (REQ-SEC-034; WP-057 S1a; lane B's conditions 1 and 3).

The test client calls from 127.0.0.1 (httpx's ASGI transport). A tenant whose console list
does not hold that address refuses the sign-in BEFORE the person is looked up or created, ends
the Keycloak session, and records nothing about them; a person in two tenants lands in the one
that admits them; switching into the restricted tenant is refused; and a live session ends at
its next refresh once its tenant restricts the address.
"""

import uuid
from datetime import timedelta

import asyncpg

from tests.db.test_auth_bff import Bff, bff, user_rows
from tooling.db_testing import ThrowawayDatabase

__all__ = ["bff"]  # the fixture, re-used

ELSEWHERE = "10.20.0.0/16"  # an office network the test client is not in


async def _restrict(
    db: ThrowawayDatabase, tenant: uuid.UUID, column: str, ranges: list[str]
) -> None:
    conn = await asyncpg.connect(db.admin_url)
    try:
        await conn.execute(
            f"INSERT INTO identity_settings (tenant_id, {column}) VALUES ($1, $2::cidr[]) "  # noqa: S608 - a fixed column name
            f"ON CONFLICT (tenant_id) DO UPDATE SET {column} = EXCLUDED.{column}",
            tenant,
            ranges,
        )
    finally:
        await conn.close()


async def test_req_sec_034_ac1_a_sign_in_from_outside_the_console_list_is_refused(
    bff: Bff,
) -> None:
    a, _b = bff.tenants
    await _restrict(bff.db, a, "console_ip_allow", [ELSEWHERE])
    response = await bff.login(bff.user("a", email="outside@demo.test"))
    assert (response.status_code, response.json()["code"]) == (403, "ip_not_allowed")
    assert bff.cookie() is None
    assert len(bff.idp.ended_sessions) == 1  # Keycloak's own session ends too
    # Refused before the person was looked up: no row, no seat (lane B's condition 1).
    assert await user_rows(bff.db, "outside@demo.test") == []


async def test_req_sec_034_ac3_the_portal_stays_open_when_only_the_console_is_restricted(
    bff: Bff,
) -> None:
    a, _b = bff.tenants
    await _restrict(bff.db, a, "console_ip_allow", [ELSEWHERE])
    portal = await bff.login(bff.user("a", email="requester@demo.test"), app="portal")
    assert portal.status_code == 302, portal.text
    assert (await bff.me()).json()["tenant"]["id"] == str(a)


async def test_a_list_holding_the_address_lets_the_sign_in_through(bff: Bff) -> None:
    a, _b = bff.tenants
    await _restrict(bff.db, a, "console_ip_allow", ["127.0.0.0/8", ELSEWHERE])
    assert (await bff.login(bff.user("a"))).status_code == 302


async def test_a_person_in_two_tenants_lands_in_the_one_that_admits_them(bff: Bff) -> None:
    a, b = bff.tenants
    await _restrict(bff.db, a, "console_ip_allow", [ELSEWHERE])
    assert (await bff.login(bff.user("a", "b", email="both@demo.test"))).status_code == 302
    me = (await bff.me()).json()
    assert me["tenant"]["id"] == str(b)
    # Switching into the restricted tenant is refused, before anyone is looked up there.
    switched = await bff.client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": str(a)},
        headers={"X-CSRF-Token": me["csrf_token"]},
    )
    assert (switched.status_code, switched.json()["code"]) == (403, "ip_not_allowed")
    rows = await user_rows(bff.db, "both@demo.test")
    assert {r["tenant_id"] for r in rows} == {b}


async def test_a_live_session_ends_at_its_next_refresh_once_restricted(bff: Bff) -> None:
    a, _b = bff.tenants
    await bff.login(bff.user("a"))
    assert (await bff.me()).status_code == 200
    await _restrict(bff.db, a, "console_ip_allow", [ELSEWHERE])
    assert (await bff.me()).status_code == 200  # within the access token's life: unchanged
    bff.clock.advance(timedelta(minutes=6))  # the next call refreshes, and checks again
    response = await bff.me()
    assert (response.status_code, response.json()["code"]) == (403, "ip_not_allowed")
    assert (await bff.me()).json()["code"] == "unauthenticated"  # the session is gone


async def test_a_realtime_token_is_refused_once_the_tenant_restricts_the_address(bff: Bff) -> None:
    """Lane B's condition 3: what turns a session into more access checks the list too."""
    a, _b = bff.tenants
    await bff.login(bff.user("a"))
    csrf = await bff.csrf()
    await _restrict(bff.db, a, "console_ip_allow", [ELSEWHERE])
    minted = await bff.client.post(
        "/api/v1/realtime/connection-token", headers={"X-CSRF-Token": csrf}
    )
    assert (minted.status_code, minted.json()["code"]) == (403, "ip_not_allowed")
