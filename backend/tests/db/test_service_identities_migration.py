"""Migration 0052: service identities, and a downgrade that keeps every user row (D-113).

A service identity can never be given a way to sign in, and going back turns it into a disabled
requester that cannot sign in, so history still names it and nothing is deleted.
"""

import asyncio
import uuid

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db


async def _add_service(admin_url: str, tenant: uuid.UUID, *, email: str | None) -> uuid.UUID:
    conn = await asyncpg.connect(admin_url)
    try:
        user = uuid.uuid4()
        await conn.execute(
            "INSERT INTO users (id, tenant_id, email, display_name, first_name, user_type,"
            " can_sign_in) VALUES ($1, $2, $3, 'it@alpha.test', 'it@alpha.test', 'service', false)",
            user,
            tenant,
            email,
        )
        return user
    finally:
        await conn.close()


async def _user(admin_url: str, user: uuid.UUID) -> tuple[object, ...]:
    conn = await asyncpg.connect(admin_url)
    try:
        row = await conn.fetchrow(
            "SELECT user_type, status, can_sign_in, display_name FROM users WHERE id = $1", user
        )
        assert row is not None
        return tuple(row)
    finally:
        await conn.close()


def test_service_identities_go_back_as_disabled_requesters_and_never_sign_in(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0052")
    try:
        tenant = asyncio.run(create_tenant(database.migrator_url))
        with pytest.raises(asyncpg.CheckViolationError):  # no address to sign in with
            asyncio.run(_add_service(database.admin_url, tenant, email="svc@alpha.test"))
        user = asyncio.run(_add_service(database.admin_url, tenant, email=None))
        assert asyncio.run(_user(database.admin_url, user)) == (
            "service",
            "active",
            False,
            "it@alpha.test",
        )
        db_testing.downgrade(database.migrator_url, "0049")
        assert asyncio.run(_user(database.admin_url, user)) == (
            "requester",
            "disabled",
            False,
            "it@alpha.test",
        )
        db_testing.migrate(database.migrator_url, "0052")  # and up again
    finally:
        db_testing.destroy(db_config, database)
