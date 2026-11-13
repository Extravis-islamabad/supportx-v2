"""Expiry marks are isolated per tenant and append-only (WP-057 S2b-2, migration 0158; rule 5a).

Also: a copied invite link's token hash is exactly 32 bytes and unique per tenant.
"""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used


async def _provider(world: World, tenant: uuid.UUID) -> uuid.UUID:
    provider = uuid.uuid4()
    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        await session.execute(
            text(
                "INSERT INTO sso_providers (id, tenant_id, alias, protocol, preset, display_name)"
                " VALUES (:i, :t, :a, 'saml', 'saml', 'Acme')"
            ),
            {"i": provider, "t": tenant, "a": f"acme-{provider.hex[:8]}"},
        )
    return provider


async def _mark(world: World, tenant: uuid.UUID, provider: uuid.UUID, threshold: int = 30) -> None:
    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        await session.execute(
            text(
                "INSERT INTO security_expiry_marks (tenant_id, id, provider_id, item, threshold)"
                " VALUES (:t, :i, :p, 'client_secret', :h)"
            ),
            {"t": tenant, "i": uuid.uuid4(), "p": provider, "h": threshold},
        )


async def test_tenant_b_neither_sees_nor_writes_tenant_as_marks(world: World) -> None:
    mine = await _provider(world, world.a.tenant)
    await _mark(world, world.a.tenant, mine)
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        seen = await session.execute(
            text("SELECT count(*) FROM security_expiry_marks WHERE tenant_id = :a"),
            {"a": world.a.tenant},
        )
        assert seen.scalar_one() == 0
    with pytest.raises(DBAPIError):  # writing a row for tenant A
        await _mark(world, world.b.tenant, mine, 7)


async def test_a_mark_is_sent_once_and_never_changed(world: World) -> None:
    mine = await _provider(world, world.a.tenant)
    await _mark(world, world.a.tenant, mine, 7)
    with pytest.raises(DBAPIError):  # the same alert again
        await _mark(world, world.a.tenant, mine, 7)
    with pytest.raises(DBAPIError):  # append-only for the application role
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await session.execute(text("DELETE FROM security_expiry_marks"))
    with pytest.raises(DBAPIError):  # not a threshold
        await _mark(world, world.a.tenant, mine, 14)


async def test_a_link_token_hash_is_32_bytes_and_unique_per_tenant(world: World) -> None:
    ids = [uuid.uuid4(), uuid.uuid4()]
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        for invitation in ids:
            await session.execute(
                text(
                    "INSERT INTO invitations (id, tenant_id, user_id, email, sent_at, expires_at)"
                    " VALUES (:i, :t, :u, :e, now(), now() + interval '7 days')"
                ),
                {"i": invitation, "t": world.a.tenant, "u": world.a.tech_a, "e": "t@acme.test"},
            )
    with pytest.raises(DBAPIError):  # not a SHA-256
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await session.execute(
                text("UPDATE invitations SET link_token_hash = :h WHERE id = :i"),
                {"h": os.urandom(16), "i": ids[0]},
            )
    digest = os.urandom(32)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await session.execute(
            text("UPDATE invitations SET link_token_hash = :h WHERE id = :i"),
            {"h": digest, "i": ids[0]},
        )
    with pytest.raises(DBAPIError):  # the same token on two invitations
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await session.execute(
                text("UPDATE invitations SET link_token_hash = :h WHERE id = :i"),
                {"h": digest, "i": ids[1]},
            )
