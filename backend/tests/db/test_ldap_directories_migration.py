"""Migration 0055: AD/LDAP directories, and a downgrade that never loses one (D-113)."""

import asyncio
import json
import uuid

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db

INSERT = (
    "INSERT INTO directory_connectors (id, tenant_id, name, source, directory_tenant, client_id,"
    " credential_kind, ldap) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)"
)


async def _insert(admin_url: str, *args: object) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(INSERT, uuid.uuid4(), *args)
    finally:
        await conn.close()


def test_ldap_directories_need_settings_entra_its_app_and_going_back_refuses_to_lose_one(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0056")
    try:
        tenant = asyncio.run(create_tenant(database.migrator_url))
        settings = json.dumps({"host": "dc1.corp.example", "port": 636})
        asyncio.run(
            _insert(database.admin_url, tenant, "Corp AD", "ldap", None, None, None, settings)
        )
        with pytest.raises(asyncpg.CheckViolationError):  # Entra without its sync app
            asyncio.run(_insert(database.admin_url, tenant, "E", "entra", None, None, None, None))
        with pytest.raises(asyncpg.CheckViolationError):  # LDAP without settings
            asyncio.run(_insert(database.admin_url, tenant, "L", "ldap", None, None, None, None))
        with pytest.raises(Exception, match="AD/LDAP directories exist"):
            db_testing.downgrade(database.migrator_url, "0051")
        asyncio.run(_delete_ldap(database.admin_url))  # a throwaway database (rule 5h)
        db_testing.downgrade(database.migrator_url, "0051")
        db_testing.migrate(database.migrator_url, "0056")  # and up again
    finally:
        db_testing.destroy(db_config, database)


async def _delete_ldap(admin_url: str) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute("DELETE FROM directory_connectors WHERE source = 'ldap'")
    finally:
        await conn.close()
