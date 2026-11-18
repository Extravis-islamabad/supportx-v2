"""Migration 0181 (redacting a CI snapshot's custom value; ADR-052): up, down and up again.

The migration only makes (and drops) one migrator-owned SECURITY DEFINER function that the app
role may run; no data step, so the downgrade never touches a row (rule 5h).
"""

import asyncio

import asyncpg
import pytest

from app.shared.db.rls import APP_ROLE
from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0180"  # 0181's down revision for now (re-pointed with it at the lane's queue turn)
SIGNATURE = "cmdb_redact_version_custom(uuid, text)"


async def _function(url: str) -> tuple[bool, bool] | None:
    """(SECURITY DEFINER, the app role may run it), or None when the function is absent."""
    conn = await asyncpg.connect(url)
    try:
        found = await conn.fetchrow(
            "SELECT p.prosecdef, has_function_privilege($1, p.oid, 'EXECUTE') AS runs"
            " FROM pg_proc p WHERE p.oid = to_regprocedure($2)",
            APP_ROLE,
            SIGNATURE,
        )
        return None if found is None else (bool(found["prosecdef"]), bool(found["runs"]))
    finally:
        await conn.close()


def test_0181_makes_the_definer_and_its_downgrade_drops_it(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_function(database.admin_url)) is None
        db_testing.migrate(database.migrator_url, "0181")
        assert asyncio.run(_function(database.admin_url)) == (True, True)
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_function(database.admin_url)) is None
        db_testing.migrate(database.migrator_url, "0181")
        assert asyncio.run(_function(database.admin_url)) == (True, True)
    finally:
        db_testing.destroy(db_config, database)
