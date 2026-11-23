"""Confirm who you are before a sensitive action (REQ-SEC-027; WP-057 S2a).

AC1: a sensitive change 20 minutes after sign-in asks for confirmation; within the window it does
not. AC2: a failed confirmation changes nothing and is in the sign-in log. Lane B's conditions:
the confirmation never makes a session, is single use, must come from the same browser and the
same person, its auth_time must be fresh, and a new Keycloak session replaces (and ends) the old.
"""

import json
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import asyncpg
import httpx

from app.modules.identity_access.service import confirm
from app.modules.identity_access.tests.fake_idp import FakeUser
from tests.db.test_auth_bff import Bff, bff

__all__ = ["bff"]  # the fixture, re-used

GUARDED = "/api/v1/identity/network-rules"
OPEN_LISTS: dict[str, list[str]] = {
    "console_ip_allow": [],
    "portal_ip_allow": [],
    "api_ip_allow": [],
}


def _admin(bff: Bff, tag: str = "admin") -> FakeUser:
    return bff.user(
        "a", email=f"{tag}-{uuid.uuid4().hex[:8]}@demo.test", roles=("tenant_admin", "technician")
    )


async def _guarded(bff: Bff) -> httpx.Response:
    current = await bff.client.get(GUARDED)
    version = current.json()["version"]
    return await bff.client.put(
        GUARDED,
        json=OPEN_LISTS,
        headers={"X-CSRF-Token": await bff.csrf(), "If-Match": f'"{version}"'},
    )


ATTEMPT = "attempt-0123456789abcdef"  # the opener's id, echoed to /confirmed


async def _confirm(bff: Bff, person: FakeUser) -> httpx.Response:
    """Start a confirmation in this browser and finish it at the fake Keycloak as `person`."""
    started = await bff.client.get(
        "/api/v1/auth/confirm", params={"returnTo": "/admin/security", "attempt": ATTEMPT}
    )
    assert started.status_code == 302, started.text
    query = parse_qs(urlsplit(started.headers["location"]).query)
    assert (query["prompt"], query["max_age"]) == (["login"], ["0"])  # authenticated now
    code, state = bff.idp.issue_code(started.headers["location"], person)
    return await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})


def _status(done: httpx.Response) -> str:
    assert done.status_code == 303, done.text
    landing = urlsplit(done.headers["location"])
    assert landing.path.endswith("/confirmed")
    query = parse_qs(landing.query)
    # The opener's pop-up listener matches its own attempt; the way back is the page it was on.
    assert (query["attempt"], query["returnTo"]) == ([ATTEMPT], ["/admin/security"])
    return query["status"][0]


async def test_req_sec_027_ac1_fresh_passes_stale_asks_and_a_confirmation_lets_it_through(
    bff: Bff,
) -> None:
    admin = _admin(bff)
    assert (await bff.login(admin)).status_code == 302
    cookie = bff.cookie()
    assert (await _guarded(bff)).status_code == 200  # just signed in: within the window
    bff.clock.advance(timedelta(minutes=20))
    asked = await _guarded(bff)
    assert (asked.status_code, asked.json()["code"]) == (403, "reauth_required")
    assert _status(await _confirm(bff, admin)) == "ok"
    assert bff.cookie() == cookie  # the same session, never a new one
    assert (await _guarded(bff)).status_code == 200


async def test_req_sec_027_ac2_another_person_or_a_stale_sign_in_changes_nothing(
    bff: Bff,
) -> None:
    admin = _admin(bff)
    await bff.login(admin)
    bff.clock.advance(timedelta(minutes=20))
    # Someone else signs in at the confirmation: refused.
    assert _status(await _confirm(bff, _admin(bff, "other"))) == "failed"
    assert (await _guarded(bff)).json()["code"] == "reauth_required"
    # Keycloak answering with an old auth_time (no real re-authentication): refused too.
    bff.idp.token_overrides = {"auth_time": int(bff.clock.now().timestamp()) - 3600}
    assert _status(await _confirm(bff, admin)) == "failed"
    bff.idp.token_overrides = {}
    assert (await _guarded(bff)).json()["code"] == "reauth_required"
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        logged = await conn.fetchval(
            "SELECT count(*) FROM sign_in_events WHERE reason = 'reauth_failed'"
        )
    finally:
        await conn.close()
    assert logged == 2  # AC2: both in the sign-in log


async def test_a_confirmation_is_single_use_and_from_this_browser_only(bff: Bff) -> None:
    admin = _admin(bff)
    await bff.login(admin)
    started = await bff.client.get("/api/v1/auth/confirm")
    code, state = bff.idp.issue_code(started.headers["location"], admin)
    # Another browser (no login binding) finishing it: refused, and the state is spent.
    stranger = httpx.AsyncClient(transport=bff.client._transport, base_url=str(bff.client.base_url))  # noqa: SLF001 - same app
    refused = await stranger.get("/api/v1/auth/callback", params={"code": code, "state": state})
    assert refused.status_code in {302, 303, 400}
    replay = await bff.client.get("/api/v1/auth/callback", params={"code": code, "state": state})
    assert replay.status_code in {302, 400}  # invalid_login_state: never confirmed twice
    assert "status=ok" not in replay.headers.get("location", "")
    await stranger.aclose()


async def test_a_new_keycloak_session_replaces_and_ends_the_old_one(bff: Bff) -> None:
    admin = _admin(bff)
    bff.idp.token_overrides = {"sid": "kc-before"}
    await bff.login(admin)
    bff.clock.advance(timedelta(minutes=20))
    before = len(bff.idp.ended_sessions)
    bff.idp.token_overrides = {"sid": "kc-after"}
    assert _status(await _confirm(bff, admin)) == "ok"
    bff.idp.token_overrides = {}
    assert len(bff.idp.ended_sessions) == before + 1  # the old chain ended (lane B A5)
    assert (await _guarded(bff)).status_code == 200


def test_only_a_well_formed_attempt_id_is_echoed() -> None:
    assert confirm.safe_attempt(ATTEMPT) == ATTEMPT
    for bad in (
        None,
        "",
        "short",
        "<script>alert(1)</script>-padding",
        "a" * 65,
        "x&status=ok-0000",
    ):
        assert confirm.safe_attempt(bad) is None


async def _change_person(bff: Bff, user_id: str, change: dict[str, str]) -> httpx.Response:
    current = await bff.client.get(f"/api/v1/users/{user_id}")
    assert current.status_code == 200, current.text
    return await bff.client.patch(
        f"/api/v1/users/{user_id}/person",
        json=change,
        headers={"X-CSRF-Token": await bff.csrf(), "If-Match": current.headers["etag"]},
    )


async def test_a_different_sign_in_email_needs_a_recent_confirmation(bff: Bff) -> None:
    """Lane B (#479): the address is where password resets go, so changing it asks first."""
    admin = _admin(bff)
    await bff.login(admin)
    me = (await bff.me()).json()["user"]["id"]
    bff.clock.advance(timedelta(minutes=20))
    moved = f"moved-{uuid.uuid4().hex[:8]}@demo.test"
    asked = await _change_person(bff, me, {"email": moved})
    assert (asked.status_code, asked.json()["code"]) == (403, "reauth_required")
    # Any other field, or the same address sent back, needs nothing.
    assert (await _change_person(bff, me, {"job_title": "Service owner"})).status_code == 200
    assert (await _change_person(bff, me, {"email": admin.email})).status_code == 200
    # Once confirmed, the new address is saved.
    assert _status(await _confirm(bff, admin)) == "ok"
    changed = await _change_person(bff, me, {"email": moved})
    assert changed.status_code == 200, changed.text
    assert changed.json()["email"] == moved
    # The audit entry names the change (never the address).
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        details = await conn.fetch(
            "SELECT details FROM audit_entries WHERE action = 'user.changed' AND object_id = $1",
            me,
        )
    finally:
        await conn.close()
    flagged = [json.loads(row["details"]) for row in details]
    assert sum(1 for d in flagged if d.get("sign_in_email_changed")) == 1  # the moved one only
    assert all(moved not in json.dumps(d) for d in flagged)
