"""Migration 0155 (template form layouts and rules; WP-046a S5b) is reversible and safe.

Up, down and up again while nothing uses the new columns; once a tenant's template has a form
rule, the downgrade is refused (rule 5h). Rows are written by SQL, never through the app.
"""

import asyncio
import json
import uuid

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0149"  # 0155's down revision while building (re-pointed at its queue turn)
AFTER = "0155"


async def _template(url: str, tenant: uuid.UUID) -> uuid.UUID:
    """A desk and an incident template of the tenant's own, written by SQL."""
    desk, template = uuid.uuid4(), uuid.uuid4()
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO desks (id, tenant_id, code, labels)"
                " VALUES ($1, $2, 'forms', '{}'::jsonb)",
                desk,
                tenant,
            )
            await conn.execute(
                "INSERT INTO work_item_templates (id, tenant_id, type, labels, desk_id)"
                " VALUES ($1, $2, 'incident', '{\"en\": \"Forms\"}'::jsonb, $3)",
                template,
                tenant,
                desk,
            )
        return template
    finally:
        await conn.close()


async def _add_rule(url: str, tenant: uuid.UUID, template: uuid.UUID) -> None:
    rule = [{"id": "r", "when": {"field": "impact", "op": "is_null"}, "then": []}]
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "UPDATE work_item_templates SET form_rules = $1::jsonb"
                " WHERE tenant_id = $2 AND id = $3",
                json.dumps(rule),
                tenant,
                template,
            )
    finally:
        await conn.close()


async def _columns(url: str, tenant: uuid.UUID) -> set[tuple[object, object]]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT layout, form_rules FROM work_item_templates WHERE tenant_id = $1", tenant
        )
        return {(r["layout"], r["form_rules"]) for r in rows}
    finally:
        await conn.close()


def test_0155_is_reversible_until_rules_are_used(db_config: db_testing.DbTestConfig) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        tenant = asyncio.run(create_tenant(database.migrator_url, "Forms"))
        template = asyncio.run(_template(database.admin_url, tenant))
        db_testing.migrate(database.migrator_url, AFTER)
        # An existing template: no layout (one plain list) and no rules.
        assert asyncio.run(_columns(database.admin_url, tenant)) == {(None, "[]")}
        db_testing.downgrade(database.migrator_url, BEFORE)
        db_testing.migrate(database.migrator_url, AFTER)
        asyncio.run(_add_rule(database.admin_url, tenant, template))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
    finally:
        db_testing.destroy(db_config, database)
