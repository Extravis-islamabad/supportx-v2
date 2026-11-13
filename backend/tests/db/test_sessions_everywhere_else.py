"""Your sessions: where they signed in, and signing out everywhere else (REQ-SEC-030; WP-057 S2a).

Lane B's conditions: ending a listed session is only ever your own (404 otherwise); "sign out
everywhere else" keeps this session working and ends the others at Keycloak too, except the
twin sharing this browser's Keycloak session (its console and portal), which ends here only;
the count, never the devices, is audited.
"""

import json
import uuid

import asyncpg
from httpx import AsyncClient

from tests.db.test_auth_bff import CONSOLE, PORTAL, Bff, bff

__all__ = ["bff"]  # the fixture, re-used

CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)


def _email(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}@demo.test"


async def _sign_in(bff: Bff, client: AsyncClient, user: object, *, sid: str, app: str) -> None:
    """A sign-in in `client` (a browser), its Keycloak session `sid`."""
    bff.idp.token_overrides = {"sid": sid}
    start = await client.get("/api/v1/auth/login", params={"app": app, "returnTo": "/"})
    code, state = bff.idp.issue_code(start.headers["location"], user)  # type: ignore[arg-type]
    done = await client.get(
        "/api/v1/auth/callback",
        params={"code": code, "state": state},
        headers={"User-Agent": CHROME_WINDOWS},
    )
    assert done.status_code == 302, done.text
    bff.idp.token_overrides = {}


def _browser(bff: Bff, base: str = CONSOLE) -> AsyncClient:
    """Another cookie jar: another browser, or this browser's other app (its own origin)."""
    return AsyncClient(transport=bff.client._transport, base_url=base)  # noqa: SLF001 - same app


async def test_req_sec_030_your_list_shows_where_and_on_what(bff: Bff) -> None:
    person = bff.user("a", email=_email("where"))
    await _sign_in(bff, bff.client, person, sid="kc-here", app="console")
    rows = (await bff.client.get("/api/v1/auth/sessions")).json()
    (mine,) = rows
    assert mine["current"] is True
    assert mine["device"] == "chrome:windows"  # a code the UI labels, never the raw header
    assert mine["ip"]  # the address the BFF saw
    # The test client signs in from a loopback address: the internal network, never a city (D-170).
    assert mine["place"] == {"kind": "internal", "site_id": None, "city": None, "country": None}


async def test_req_sec_030_ac2_everywhere_else_keeps_this_one_and_its_twin_locally(
    bff: Bff,
) -> None:
    person = bff.user("a", email=_email("others"))
    # This browser: console and portal (separate origins, so separate cookies), one Keycloak
    # session between them (twins).
    portal = _browser(bff, PORTAL)
    await _sign_in(bff, bff.client, person, sid="kc-this-browser", app="console")
    await _sign_in(bff, portal, person, sid="kc-this-browser", app="portal")
    # Two other browsers, each its own Keycloak session.
    laptop, phone = _browser(bff), _browser(bff)
    await _sign_in(bff, laptop, person, sid="kc-laptop", app="console")
    await _sign_in(bff, phone, person, sid="kc-phone", app="console")
    assert len((await bff.client.get("/api/v1/auth/sessions")).json()) == 4
    ended_before = list(bff.idp.ended_sessions)
    done = await bff.client.post(
        "/api/v1/auth/sessions/end-others", headers={"X-CSRF-Token": await bff.csrf()}
    )
    assert (done.status_code, done.json()) == (200, {"ended": 3})
    # This session still works; the other browsers are signed out.
    assert (await bff.me()).status_code == 200
    assert (await laptop.get("/api/v1/auth/me")).status_code == 401
    assert (await phone.get("/api/v1/auth/me")).status_code == 401
    # The twin ends here too (it is another session of yours)...
    assert (await portal.get("/api/v1/auth/me")).status_code == 401
    # ...but Keycloak ended only the two other browsers' sessions, never this browser's own.
    newly = bff.idp.ended_sessions[len(ended_before) :]
    assert len(newly) == 2
    (row,) = (await bff.client.get("/api/v1/auth/sessions")).json()
    assert row["current"] is True
    # Audited with the count only (lane B).
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        entry = await conn.fetchrow(
            "SELECT details FROM audit_entries WHERE action = 'session.ended_others'"
            " ORDER BY occurred_at DESC LIMIT 1"
        )
    finally:
        await conn.close()
    assert entry is not None
    assert json.loads(entry["details"]) == {"ended": 3}
    await laptop.aclose()
    await phone.aclose()
    await portal.aclose()


async def test_ending_a_listed_session_is_only_ever_your_own(bff: Bff) -> None:
    mine, theirs = bff.user("a", email=_email("mine")), bff.user("a", email=_email("theirs"))
    other = _browser(bff)
    await _sign_in(bff, other, theirs, sid="kc-theirs", app="console")
    (their_row,) = (await other.get("/api/v1/auth/sessions")).json()
    await _sign_in(bff, bff.client, mine, sid="kc-mine", app="console")
    refused = await bff.client.delete(
        f"/api/v1/auth/sessions/{their_row['id']}", headers={"X-CSRF-Token": await bff.csrf()}
    )
    assert (refused.status_code, refused.json()["code"]) == (404, "session_not_found")
    assert (await other.get("/api/v1/auth/me")).status_code == 200  # untouched
    await other.aclose()


async def test_ending_one_session_ends_it_at_keycloak_too(bff: Bff) -> None:
    person = bff.user("a", email=_email("one"))
    laptop = _browser(bff)
    await _sign_in(bff, laptop, person, sid="kc-laptop-one", app="console")
    await _sign_in(bff, bff.client, person, sid="kc-desk-one", app="console")
    rows = (await bff.client.get("/api/v1/auth/sessions")).json()
    (laptop_row,) = [r for r in rows if not r["current"]]
    before = len(bff.idp.ended_sessions)
    gone = await bff.client.delete(
        f"/api/v1/auth/sessions/{laptop_row['id']}", headers={"X-CSRF-Token": await bff.csrf()}
    )
    assert gone.status_code == 204
    assert len(bff.idp.ended_sessions) == before + 1  # its refresh token is spent at Keycloak
    assert (await laptop.get("/api/v1/auth/me")).status_code == 401
    await laptop.aclose()
