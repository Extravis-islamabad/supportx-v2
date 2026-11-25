"""The tenant's mobile app policy at sign-in and after (WP-057 S6b; REQ-SEC-047).

- AC1: with the app switched off, its sign-in is refused before anyone is provisioned, with the
  tenant's message, cleaned, on the app's return link; logged as a policy refusal. Switching it
  off ends the tenant's mobile sessions at once; web sessions are untouched.
- The mobile session's limits come from the policy (else the web app's).
- `GET /auth/mobile/policy`: the client-enforced parts, for a mobile session only.

The fake identity provider and real PostgreSQL of test_auth_bff.py; every policy is put back.
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import asyncpg
import httpx

from app.modules.identity_access.domain.mobile import SESSION_HEADER
from tests.db import test_auth_bff
from tests.db.test_api_keys import _signed_in
from tests.db.test_auth_bff import Bff
from tests.db.test_auth_mobile import APP_RETURN, mobile_login, new_verifier, signed_in

pytestmark = test_auth_bff.pytestmark
bff = test_auth_bff.bff  # the BFF world fixture, reused


async def _as_phone(bff: Bff, phone: str, path: str) -> httpx.Response:
    """A request from the app alone: its session header, without the test browser's cookie."""
    cookies = bff.client.cookies
    bff.client.cookies = httpx.Cookies()
    try:
        return await bff.client.get(path, headers={SESSION_HEADER: phone})
    finally:
        bff.client.cookies = cookies


async def _sql(bff: Bff, statement: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        return await conn.fetch(statement, *args)
    finally:
        await conn.close()


@asynccontextmanager
async def _policy(bff: Bff, tenant: uuid.UUID, **columns: object) -> AsyncIterator[None]:
    """Set these mobile columns for the test, then put the defaults back."""
    names = list(columns)
    values = [json.dumps(v) if isinstance(v, dict) else v for v in columns.values()]
    placeholders = ", ".join(
        f"${i + 2}::jsonb" if isinstance(columns[n], dict) else f"${i + 2}"
        for i, n in enumerate(names)
    )
    updates = ", ".join(f"{n} = EXCLUDED.{n}" for n in names)
    await _sql(
        bff,
        f"INSERT INTO identity_settings (tenant_id, {', '.join(names)}) VALUES ($1, {placeholders})"  # noqa: S608 - column names from this file's calls
        f" ON CONFLICT (tenant_id) DO UPDATE SET {updates}",
        tenant,
        *values,
    )
    try:
        yield
    finally:
        await _sql(
            bff,
            "UPDATE identity_settings SET mobile_allowed = true, mobile_refusal_message = NULL,"
            " mobile_idle_seconds = NULL, mobile_absolute_seconds = NULL,"
            " mobile_device_unlock_required = false, mobile_unlock_after_minutes = 5"
            " WHERE tenant_id = $1",
            tenant,
        )


async def test_with_the_app_off_its_sign_in_is_refused_with_the_tenants_words(bff: Bff) -> None:
    tenant = bff.tenants[0]
    said = {"en": "Please use the\nweb console.\u202e", "ar": "استخدم وحدة التحكم على الويب."}
    async with _policy(bff, tenant, mobile_allowed=False, mobile_refusal_message=said):
        email = f"phone-{uuid.uuid4().hex[:8]}@demo.test"
        answer = await mobile_login(bff, bff.user("a", email=email), new_verifier())
        assert answer.status_code == 303, answer.text
        target = urlsplit(answer.headers["location"])
        assert f"{target.scheme}://{target.netloc}{target.path}" == APP_RETURN
        query = parse_qs(target.query)
        assert query["auth_error"] == ["mobile_not_allowed"]
        # Cleaned: one line, no direction override; plain text for the app to show as text.
        assert query["auth_message"] == ["Please use the web console."]
        assert "handoff" not in query
        # Before anyone is provisioned: no account was made for this new person.
        made = await _sql(
            bff, "SELECT id FROM users WHERE tenant_id = $1 AND email = $2", tenant, email
        )
        assert made == []
        logged = await _sql(
            bff,
            "SELECT outcome, reason FROM sign_in_events WHERE tenant_id = $1"
            " ORDER BY occurred_at DESC LIMIT 1",
            tenant,
        )
        assert (logged[0]["outcome"], logged[0]["reason"]) != ("succeeded", None)
        assert logged[0]["reason"] == "mobile_not_allowed"
        # The web apps are not the mobile app: a browser sign-in still works.
        web = await bff.login(bff.user("a", email=email))
        assert web.status_code == 302, web.text


async def test_switching_the_app_off_ends_its_sessions_but_not_the_webs(bff: Bff) -> None:
    tenant = bff.tenants[0]
    phone = await signed_in(bff, bff.user("a", email=f"p-{uuid.uuid4().hex[:6]}@demo.test"))
    before = await bff.client.get("/api/v1/auth/me", headers={SESSION_HEADER: phone})
    assert before.status_code == 200, before.text
    web = await bff.login(bff.user("a", email=f"w-{uuid.uuid4().hex[:6]}@demo.test"))
    assert web.status_code == 302
    async with _policy(bff, tenant, mobile_allowed=False):
        bff.clock.advance(timedelta(seconds=1))
        await bff.app.state.auth.end_mobile_sessions(tenant)
        after = await _as_phone(bff, phone, "/api/v1/auth/mobile/policy")
        assert (after.status_code, after.json()["code"]) == (401, "mobile_not_allowed")
        assert (await bff.me()).status_code == 200  # the browser session carries on


async def test_the_mobile_session_lasts_as_the_policy_says(bff: Bff) -> None:
    tenant = bff.tenants[0]
    async with _policy(bff, tenant, mobile_idle_seconds=600, mobile_absolute_seconds=7200):
        phone = await signed_in(bff, bff.user("a", email=f"l-{uuid.uuid4().hex[:6]}@demo.test"))
        stored = await bff.app.state.auth.store.get_session(phone)
        assert (stored["idle_seconds"], stored["absolute_seconds"]) == (600, 7200)
    # With none set, the web app's limits (the console's Appendix A defaults).
    phone = await signed_in(bff, bff.user("a", email=f"d-{uuid.uuid4().hex[:6]}@demo.test"))
    stored = await bff.app.state.auth.store.get_session(phone)
    assert stored["idle_seconds"] != 600


async def test_the_app_reads_its_policy_and_a_browser_cannot(bff: Bff) -> None:
    tenant = bff.tenants[0]
    async with _policy(
        bff, tenant, mobile_device_unlock_required=True, mobile_unlock_after_minutes=3
    ):
        phone = await signed_in(bff, bff.user("a", email=f"r-{uuid.uuid4().hex[:6]}@demo.test"))
        read = await bff.client.get("/api/v1/auth/mobile/policy", headers={SESSION_HEADER: phone})
        assert read.status_code == 200, read.text
        assert read.json() == {
            "device_unlock_required": True,
            "unlock_after_minutes": 3,
            "clear_on_sign_out": True,
        }
        web = await bff.login(bff.user("a", email=f"b-{uuid.uuid4().hex[:6]}@demo.test"))
        assert web.status_code == 302
        refused = await bff.client.get("/api/v1/auth/mobile/policy")
        assert (refused.status_code, refused.json()["code"]) == (403, "mobile_session_required")


# --- the Mobile card's own save (lane B's S6b condition 1) ---------------------------------------

MOBILE = {
    "allowed": True,
    "refusal_message": None,
    "mfa_required": False,
    "device_unlock_required": True,
    "unlock_after_minutes": 10,
    "idle_seconds": None,
    "absolute_seconds": None,
    "clear_on_sign_out": True,
}


async def _put_mobile(bff: Bff, csrf: str, version: int, **change: object) -> httpx.Response:
    return await bff.client.put(
        "/api/v1/identity/settings/mobile",
        json={**MOBILE, **change},
        headers={"X-CSRF-Token": csrf, "If-Match": f'"{version}"'},
    )


async def test_a_stale_mobile_save_is_refused_and_a_fresh_one_keeps_the_other_cards(
    bff: Bff,
) -> None:
    csrf = await _signed_in(bff)
    first = (await bff.client.get("/api/v1/identity/settings")).json()
    # The session-limits card saves meanwhile (another admin, another tab).
    limits = await bff.client.put(
        "/api/v1/identity/settings",
        json={"console_idle_seconds": 1800},
        headers={"X-CSRF-Token": csrf, "If-Match": f'"{first["version"]}"'},
    )
    assert limits.status_code == 200, limits.text
    stale = await _put_mobile(bff, csrf, first["version"])
    assert stale.status_code == 409, stale.text  # never overwrites the other card's save
    fresh = await _put_mobile(bff, csrf, limits.json()["version"])
    assert fresh.status_code == 200, fresh.text
    body = fresh.json()
    assert (body["mobile_device_unlock_required"], body["mobile_unlock_after_minutes"]) == (
        True,
        10,
    )
    assert body["console_idle_seconds"] == 1800  # the session-limits card's value is kept
    put_back = await _put_mobile(
        bff, csrf, body["version"], device_unlock_required=False, unlock_after_minutes=5
    )
    assert put_back.status_code == 200, put_back.text


async def test_the_mobile_policys_bounds_are_the_servers(bff: Bff) -> None:
    csrf = await _signed_in(bff)
    version = (await bff.client.get("/api/v1/identity/settings")).json()["version"]
    for change, field in (
        ({"unlock_after_minutes": 0}, "mobile_unlock_after_minutes"),
        ({"idle_seconds": 600}, "mobile_absolute_seconds"),  # one limit without the other
        ({"idle_seconds": 600, "absolute_seconds": 300}, "mobile_absolute_seconds"),
        ({"refusal_message": {"en": "x" * 501}}, "mobile_refusal_message"),
    ):
        refused = await _put_mobile(bff, csrf, version, **change)
        assert refused.status_code == 422, (change, refused.text)
        assert field in {e["field"] for e in refused.json()["errors"]}, refused.text
    other_language = await _put_mobile(bff, csrf, version, refusal_message={"fr": "Non"})
    assert other_language.status_code == 422  # en, ar and ur only


async def test_switching_the_app_off_through_the_card_ends_its_sessions(bff: Bff) -> None:
    phone = await signed_in(bff, bff.user("a", email=f"c-{uuid.uuid4().hex[:6]}@demo.test"))
    csrf = await _signed_in(bff)
    version = (await bff.client.get("/api/v1/identity/settings")).json()["version"]
    bff.clock.advance(timedelta(seconds=1))
    off = await _put_mobile(bff, csrf, version, allowed=False)
    assert off.status_code == 200, off.text
    try:
        after = await _as_phone(bff, phone, "/api/v1/auth/mobile/policy")
        assert (after.status_code, after.json()["code"]) == (401, "mobile_not_allowed")
    finally:
        await _put_mobile(bff, csrf, off.json()["version"], allowed=True)
