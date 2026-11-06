"""Migration 0104: `merged_into` joins the link kinds without dropping anyone else's.

Lane C's 0098 widens the same check (release link kinds). Whichever lands first, both sets must
survive. Here another lane's code is put on the live check before 0104 runs. The test proves:
- 0104 keeps that code and adds its own;
- 0104's downgrade removes only `merged_into`.
"""

import asyncio
import re

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

CHECK = "ck_work_item_links_kind_code"
OTHER = "zz_other_lane"


async def _codes(admin_url: str) -> list[str]:
    conn = await asyncpg.connect(admin_url)
    try:
        definition = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = $1", CHECK
        )
    finally:
        await conn.close()
    return re.findall(r"'([a-z_]+)'::", str(definition))


async def _add_other(admin_url: str) -> None:
    """What another lane's widening migration does: add a code to the live check."""
    now = await _codes(admin_url)
    codes = ", ".join(f"'{c}'" for c in [*now, OTHER])
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(f"ALTER TABLE work_item_links DROP CONSTRAINT {CHECK}")
        await conn.execute(
            f"ALTER TABLE work_item_links ADD CONSTRAINT {CHECK} CHECK (kind IN ({codes}))"
        )
    finally:
        await conn.close()


def test_merged_into_keeps_other_lanes_kinds_both_ways(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0078")
    try:
        asyncio.run(_add_other(database.admin_url))
        db_testing.migrate(database.migrator_url, "0104")
        after = asyncio.run(_codes(database.admin_url))
        assert {"related", "follows", "caused_by", OTHER, "merged_into"} <= set(after)
        db_testing.downgrade(database.migrator_url, "0078")
        back = asyncio.run(_codes(database.admin_url))
        assert "merged_into" not in back
        assert {"related", "follows", "caused_by", OTHER} <= set(back)
    finally:
        db_testing.destroy(db_config, database)
