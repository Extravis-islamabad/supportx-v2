"""Realtime tokens over HTTP: who may connect and join which channel (WP-011, §8.2).

Real PostgreSQL and Valkey; the session is faked by headers like the access tests. Centrifugo
itself is not needed here: it verifies what these endpoints sign (see the integration and e2e
tests for forged and expired tokens).
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.tenancy import SESSION_RESOLVER_STATE
from app.main import create_app
from app.shared.realtime.tokens import decode_unverified
from conftest import make_settings
from tests.db.test_access_api import MANAGER_GRANTS, Org, fake_session, make_org
from tests.db.test_rate_limit import valkey_url
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]

SECRET = "realtime-test-secret-" + "x" * 16


@dataclass
class RT:
    client: AsyncClient
    a: Org
    b: Org
    app: FastAPI

    async def call(
        self,
        method: str,
        path: str,
        org: Org,
        user: uuid.UUID | None,
        **kw: Any,  # noqa: ANN401 - httpx options
    ) -> httpx.Response:
        headers = {"X-Test-Tenant": str(org.tenant)}
        if user is not None:
            headers["X-Test-User"] = str(user)
        return await self.client.request(method, f"/api/v1{path}", headers=headers, **kw)

    async def subscribe(self, org: Org, user: uuid.UUID, channel: str) -> httpx.Response:
        return await self.call(
            "POST", "/realtime/subscription-token", org, user, json={"channel": channel}
        )


@pytest_asyncio.fixture
async def rt(migrated_db: ThrowawayDatabase) -> AsyncIterator[RT]:
    url = valkey_url()
    if url is None:
        pytest.skip("Valkey is not configured")
    app: FastAPI = create_app(
        make_settings(
            database_url=migrated_db.app_url, valkey_url=url, centrifugo_token_secret=SECRET
        )
    )
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            world = RT(
                client, await make_org(migrated_db, "RtA"), await make_org(migrated_db, "RtB"), app
            )
            for org in (world.a, world.b):
                created = await world.call(
                    "POST",
                    "/roles",
                    org,
                    org.admin,
                    json={"name": "Access manager", "permissions": MANAGER_GRANTS},
                )
                assert created.status_code == 201, created.text
                assigned = await world.call(
                    "PUT", f"/users/{org.manager}/roles/{created.json()['id']}", org, org.admin
                )
                assert assigned.status_code == 204, assigned.text
            yield world
            cache = app.state.policy.cache
            keys = [
                k
                async for k in cache.client.scan_iter(
                    match=f"{app.state.settings.valkey_key_prefix}*"
                )
            ]
            if keys:
                await cache.client.delete(*keys)


def denied(response: httpx.Response) -> bool:
    return response.status_code == 403 and response.json()["code"] == "realtime_channel_denied"


# --- connection ----------------------------------------------------------------------------------


async def test_signed_in_users_get_a_short_connection_token(rt: RT) -> None:
    response = await rt.call("POST", "/realtime/connection-token", rt.a, rt.a.requester)
    assert response.status_code == 200
    body = response.json()
    claims = decode_unverified(body["token"])
    assert claims["sub"] == f"{rt.a.tenant}:{rt.a.requester}"
    assert claims["exp"] - claims["iat"] == body["expires_in"] == 900
    assert claims["info"] == {"user_id": str(rt.a.requester), "name": "RtA Requester"}
    assert set(claims) == {"sub", "aud", "iss", "iat", "exp", "info"}  # nothing else leaks


async def test_no_session_no_token(rt: RT) -> None:
    response = await rt.call("POST", "/realtime/connection-token", rt.a, None)
    assert response.status_code == 401


# --- subscriptions ------------------------------------------------------------------------------


async def test_own_channels_are_allowed(rt: RT) -> None:
    a = rt.a
    for channel in (f"t:{a.tenant}:user:{a.requester}", f"t:{a.tenant}:broadcast"):
        response = await rt.subscribe(a, a.requester, channel)
        assert response.status_code == 200, response.text
        claims = decode_unverified(response.json()["token"])
        assert claims["channel"] == channel
        assert claims["sub"] == f"{a.tenant}:{a.requester}"
        assert "override" not in claims  # no presence on these


async def test_own_record_comes_with_presence(rt: RT) -> None:
    a = rt.a
    response = await rt.subscribe(a, a.requester, f"t:{a.tenant}:users:{a.requester}")
    assert response.status_code == 200
    assert decode_unverified(response.json()["token"])["override"]["presence"] == {"value": True}


async def test_another_tenants_channels_are_refused(rt: RT) -> None:
    a, b = rt.a, rt.b
    for channel in (
        f"t:{b.tenant}:broadcast",
        f"t:{b.tenant}:user:{a.admin}",
        f"t:{b.tenant}:users:{b.tech}",
        f"t:{b.tenant}:queue:users",
    ):
        assert denied(await rt.subscribe(a, a.admin, channel)), channel


async def test_someone_elses_personal_channel_is_refused(rt: RT) -> None:
    a = rt.a
    assert denied(await rt.subscribe(a, a.admin, f"t:{a.tenant}:user:{a.requester}"))


async def test_records_follow_the_policy_layer(rt: RT) -> None:
    a = rt.a
    tech_record = f"t:{a.tenant}:users:{a.tech}"
    # Requesters hold no users.view: another user's record is refused, the list too.
    assert denied(await rt.subscribe(a, a.requester, tech_record))
    assert denied(await rt.subscribe(a, a.requester, f"t:{a.tenant}:queue:users"))
    # The admin (all scope) may follow both; a user ID that does not exist is refused.
    assert (await rt.subscribe(a, a.admin, tech_record)).status_code == 200
    assert (await rt.subscribe(a, a.admin, f"t:{a.tenant}:queue:users")).status_code == 200
    assert denied(await rt.subscribe(a, a.admin, f"t:{a.tenant}:users:{uuid.uuid4()}"))


@pytest.mark.parametrize(
    "channel",
    [
        "not-a-channel",
        "t:{tenant}:unknown_kind:1",
        "t:{tenant}:users:not-a-uuid",
        "t:{tenant}:queue:nonexistent_list",
        "t:{tenant}:queue:users.site.{fake}",
        "t:{tenant}:broadcast:extra",
    ],
)
async def test_unknown_or_malformed_channels_are_refused(rt: RT, channel: str) -> None:
    a = rt.a
    name = channel.format(tenant=a.tenant, fake=uuid.uuid4())
    assert denied(await rt.subscribe(a, a.admin, name))


async def test_live_list_channels_depend_on_the_users_grants(rt: RT) -> None:
    a = rt.a
    admin = (await rt.call("GET", "/realtime/lists/users", a, a.admin)).json()
    assert admin == {"channels": [f"t:{a.tenant}:queue:users"]}
    requester = (await rt.call("GET", "/realtime/lists/users", a, a.requester)).json()
    assert requester == {"channels": []}
    roles = (await rt.call("GET", "/realtime/lists/roles", a, a.manager)).json()
    assert roles == {"channels": [f"t:{a.tenant}:queue:roles"]}
    assert (await rt.call("GET", "/realtime/lists/nothing", a, a.admin)).status_code == 404


async def test_a_removed_role_stops_the_next_subscription(rt: RT) -> None:
    a = rt.a
    channel = f"t:{a.tenant}:queue:users"
    assert (await rt.subscribe(a, a.manager, channel)).status_code == 200
    roles = (await rt.call("GET", "/roles", a, a.admin)).json()
    manager_role = next(r["id"] for r in roles if r["name"] == "Access manager")
    removed = await rt.call("DELETE", f"/users/{a.manager}/roles/{manager_role}", a, a.admin)
    assert removed.status_code == 204
    assert denied(await rt.subscribe(a, a.manager, channel))
    assert denied(await rt.subscribe(a, a.manager, f"t:{a.tenant}:users:{a.tech}"))


async def test_not_configured_is_a_clear_503(migrated_db: ThrowawayDatabase) -> None:
    app = create_app(make_settings(database_url=migrated_db.app_url))
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        org = await make_org(migrated_db, "RtC")
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/realtime/connection-token",
                headers={"X-Test-Tenant": str(org.tenant), "X-Test-User": str(org.admin)},
            )
    assert (response.status_code, response.json()["code"]) == (503, "realtime_not_configured")
