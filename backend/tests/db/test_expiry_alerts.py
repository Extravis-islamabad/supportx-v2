"""Tenant admins hear before a sign-in certificate or secret runs out (REQ-SEC-011; WP-057 S2b-2).

Through the real schedule step and the real notification engine:
- a SAML provider's certificates come from Keycloak (here a fake), each watched on its own;
- an alert due writes its marks and its event together, and a second run sends nothing;
- the tenant's admins are told, in the app;
- an OIDC client secret's expiry date alerts too; a draft provider is never watched.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
from sqlalchemy import text

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.identity_access.service.expiry_alerts import check_tenant
from app.modules.identity_access.tests.test_expiry import _bare, _pem
from app.modules.notifications.service.engine import dispatch
from app.shared.events import EventEnvelope
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World
from tests.db.test_notifications_api import NO_MAIL

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
EVENT = "identity_access.sign_in_secret.expiring"


class FakeKeycloak:
    """The identity provider configs Keycloak holds, by alias."""

    def __init__(self, configs: dict[str, dict[str, Any]]) -> None:
        self.configs = configs

    async def provider(self, alias: str) -> dict[str, Any] | None:
        config = self.configs.get(alias)
        return None if config is None else {"alias": alias, "config": config}


async def _provider(world: World, **values: Any) -> uuid.UUID:  # noqa: ANN401 - column values
    provider = uuid.uuid4()
    row = {
        "id": provider,
        "t": world.a.tenant,
        "alias": f"p-{provider.hex[:8]}",
        "protocol": "saml",
        "state": "on",
        "secret": None,
        **values,
    }
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await session.execute(
            text(
                "INSERT INTO sso_providers (id, tenant_id, alias, protocol, preset, display_name,"
                " state, client_secret_expires_at) VALUES (:id, :t, :alias, :protocol,"
                " :protocol, 'Acme', :state, :secret)"
            ),
            row,
        )
    return uuid.UUID(str(row["id"]))  # the caller's id when it gave one


async def _run(world: World, keycloak: FakeKeycloak, now: datetime = NOW) -> int:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        return await check_tenant(session, world.a.tenant, keycloak, now)  # type: ignore[arg-type]  # the fake has only provider()


async def _admin(world: World, query: str, *args: object) -> list[asyncpg.Record]:
    """Read as the superuser (the outbox and deliveries are not the app role's to read)."""
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        return list(await conn.fetch(query, *args))
    finally:
        await conn.close()


async def _events(world: World, provider: uuid.UUID) -> list[dict[str, Any]]:
    rows = await _admin(
        world,
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2 ORDER BY id",
        world.a.tenant,
        EVENT,
    )
    found = [json.loads(r["envelope"]) for r in rows]
    return [e for e in found if e["payload"]["provider_id"] == str(provider)]


async def test_a_certificate_running_out_tells_the_admins_once(world: World) -> None:
    soon, later = NOW + timedelta(days=5), NOW + timedelta(days=400)
    alias_id = uuid.uuid4()
    provider = await _provider(world, id=alias_id, alias=f"p-{alias_id.hex[:8]}")
    keycloak = FakeKeycloak(
        {f"p-{alias_id.hex[:8]}": {"signingCertificate": f"{_bare(_pem(soon))},{_pem(later)}"}}
    )
    assert await _run(world, keycloak) == 1  # the old certificate (7 days), not the new one
    assert await _run(world, keycloak) == 0  # never twice
    (event,) = await _events(world, provider)
    assert event["payload"]["item"] == "certificate"
    assert event["payload"]["days_left"] == 7
    # The engine tells the tenant's admins, in the app.
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(world.a.tenant)) as session:
            await dispatch(session, NO_MAIL, EventEnvelope.model_validate(event))
    finally:
        await database.dispose()
    told = await _admin(
        world,
        "SELECT user_id, channel, state FROM notification_deliveries WHERE tenant_id = $1"
        " AND event_code = 'sign_in_secret.expiring' AND record_id = $2",
        world.a.tenant,
        provider,
    )
    assert (world.a.admin, "in_app", "sent") in {
        (r["user_id"], r["channel"], r["state"]) for r in told
    }
    # A day before the end, the next alert; once run out, the last one.
    assert await _run(world, keycloak, soon - timedelta(hours=12)) == 1
    assert await _run(world, keycloak, soon + timedelta(hours=1)) == 1
    assert [e["payload"]["days_left"] for e in await _events(world, provider)] == [7, 1, 0]


async def test_a_client_secret_date_alerts_and_a_draft_is_never_watched(world: World) -> None:
    secret = await _provider(world, protocol="oidc", secret=NOW + timedelta(days=20))
    draft = await _provider(world, protocol="oidc", state="draft", secret=NOW + timedelta(days=2))
    assert await _run(world, FakeKeycloak({})) >= 1
    (event,) = await _events(world, secret)
    assert (event["payload"]["item"], event["payload"]["days_left"]) == ("client_secret", 30)
    assert await _events(world, draft) == []
