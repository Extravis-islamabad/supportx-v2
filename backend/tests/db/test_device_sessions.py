"""A person's signed-in sessions: listed and ended one by one (ADR-044 item 5).

Same world as test_auth_bff (FakeIdp, in-memory Valkey, real PostgreSQL). Each browser is its own
client with its own cookie jar, as two devices would be.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import httpx
from httpx import ASGITransport, AsyncClient

from app.modules.identity_access.infra.store import public_id
from tests.db import test_auth_bff
from tests.db.test_auth_bff import CONSOLE, Bff, _grant

pytestmark = test_auth_bff.pytestmark
bff = test_auth_bff.bff  # the BFF world fixture, reused

SESSIONS = "/api/v1/auth/sessions"


@asynccontextmanager
async def _device(bff: Bff) -> AsyncIterator[AsyncClient]:
    """A second browser: same app, its own cookies."""
    transport = ASGITransport(app=bff.app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url=CONSOLE) as client:
        yield client


async def _login_on(bff: Bff, client: AsyncClient, email: str) -> None:
    mine = bff.client
    bff.client = client
    try:
        done = await bff.login(bff.user("a", email=email))
        assert done.status_code == 302, done.text
    finally:
        bff.client = mine


async def _csrf(client: AsyncClient) -> dict[str, str]:
    me = await client.get("/api/v1/auth/me")
    return {"X-CSRF-Token": str(me.json()["csrf_token"])}


async def _audited(bff: Bff, email: str) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(bff.db.admin_url)  # audit_entries has FORCED RLS
    try:
        return await conn.fetch(
            "SELECT e.action, e.actor_id = u.id AS by_self, e.object_id, e.details"
            " FROM audit_entries e JOIN users u ON u.id::text = e.object_id"
            " WHERE u.email = $1 AND e.action = 'session.ended' ORDER BY e.occurred_at",
            email,
        )
    finally:
        await conn.close()


async def test_you_see_your_sessions_and_end_another_one(bff: Bff) -> None:
    email = "two-devices@demo.test"
    await bff.login(bff.user("a", email=email))
    async with _device(bff) as phone:
        await _login_on(bff, phone, email)
        listed = await bff.client.get(SESSIONS)
        assert listed.status_code == 200, listed.text
        rows = listed.json()
        assert len(rows) == 2
        assert [r["current"] for r in rows].count(True) == 1
        this = next(r for r in rows if r["current"])
        assert this["id"] == public_id(bff.cookie() or "")
        assert all(r["client"] == "console" and r["started_at"] for r in rows)
        # The listed id is never the session id itself.
        assert bff.cookie() not in {r["id"] for r in rows}
        other = next(r for r in rows if not r["current"])
        ended = await bff.client.delete(
            f"{SESSIONS}/{other['id']}", headers=await _csrf(bff.client)
        )
        assert ended.status_code == 204, ended.text
        assert (await phone.get("/api/v1/auth/me")).status_code == 401  # at once
        assert [r["id"] for r in (await bff.client.get(SESSIONS)).json()] == [this["id"]]
        again = await bff.client.delete(
            f"{SESSIONS}/{other['id']}", headers=await _csrf(bff.client)
        )
        assert again.status_code == 404
        assert again.json()["code"] == "session_not_found"
    assert (await bff.me()).status_code == 200  # this browser stays signed in
    audit = await _audited(bff, email)
    assert len(audit) == 1
    assert audit[0]["by_self"]


async def test_ending_needs_the_csrf_token(bff: Bff) -> None:
    await bff.login(bff.user("a", email="csrf-sessions@demo.test"))
    mine = (await bff.client.get(SESSIONS)).json()[0]["id"]
    refused = await bff.client.delete(f"{SESSIONS}/{mine}")
    assert refused.status_code == 403
    assert (await bff.me()).status_code == 200


async def test_you_cannot_end_someone_elses_session(bff: Bff) -> None:
    async with _device(bff) as theirs:
        await _login_on(bff, theirs, "victim@demo.test")
        their_id = (await theirs.get(SESSIONS)).json()[0]["id"]
        await bff.login(bff.user("a", email="attacker@demo.test"))
        refused = await bff.client.delete(f"{SESSIONS}/{their_id}", headers=await _csrf(bff.client))
        assert refused.status_code == 404
        assert (await theirs.get("/api/v1/auth/me")).status_code == 200
        assert [r["id"] for r in (await bff.client.get(SESSIONS)).json()] != [their_id]


async def test_signed_out_and_expired_sessions_leave_the_list(bff: Bff) -> None:
    email = "leaving@demo.test"
    await bff.login(bff.user("a", email=email))
    async with _device(bff) as laptop:
        await _login_on(bff, laptop, email)
        out = await laptop.post("/api/v1/auth/logout", headers=await _csrf(laptop))
        assert out.status_code == 204
    assert len((await bff.client.get(SESSIONS)).json()) == 1


async def test_an_admin_lists_and_ends_a_persons_session(bff: Bff) -> None:
    person = "lost-phone@demo.test"
    async with _device(bff) as phone:
        await _login_on(bff, phone, person)
        me = (await phone.get("/api/v1/auth/me")).json()
        user_id = me["user"]["id"]
        admin = "people-admin@demo.test"
        await bff.login(bff.user("a", email=admin))
        base = f"/api/v1/identity/people/{user_id}/sessions"
        # Without people rights: refused.
        assert (await bff.client.get(base)).status_code == 403
        await _grant(bff, admin, "tenant_admin")
        await bff.login(bff.user("a", email=admin))
        listed = await bff.client.get(base)
        assert listed.status_code == 200, listed.text
        rows = listed.json()
        assert len(rows) == 1
        assert rows[0]["current"] is False  # never the admin's own browser
        ended = await bff.client.delete(f"{base}/{rows[0]['id']}", headers=await _csrf(bff.client))
        assert ended.status_code == 204, ended.text
        assert (await phone.get("/api/v1/auth/me")).status_code == 401
        missing = await bff.client.get(f"/api/v1/identity/people/{uuid.uuid4()}/sessions")
        assert missing.status_code == 404
    audit = await _audited(bff, person)
    assert len(audit) == 1
    assert not audit[0]["by_self"]


async def test_open_screens_hear_that_the_list_changed(bff: Bff) -> None:
    """Sign-in, sign-out and ending one each tell the person's own channel (no refresh, §8)."""
    told: list[tuple[uuid.UUID, uuid.UUID]] = []
    closed: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def changed(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        told.append((tenant_id, user_id))

    async def cut(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        closed.append((tenant_id, user_id))

    auth = bff.app.state.auth
    auth.sessions_changed = changed
    auth.end_realtime = cut
    email = "live-list@demo.test"
    await bff.login(bff.user("a", email=email))
    me = (await bff.me()).json()
    who = (uuid.UUID(me["tenant"]["id"]), uuid.UUID(me["user"]["id"]))
    assert told == [who]
    async with _device(bff) as other:
        await _login_on(bff, other, email)
        assert told == [who, who]
        listed = (await bff.client.get(SESSIONS)).json()
        theirs = next(r["id"] for r in listed if not r["current"])
        response: httpx.Response = await bff.client.delete(
            f"{SESSIONS}/{theirs}", headers=await _csrf(bff.client)
        )
        assert response.status_code == 204
    assert told == [who, who, who]
    assert closed == [who]  # the ended device can't keep listening
