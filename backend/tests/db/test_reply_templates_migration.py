"""Migration 0154 (reply and resolution templates; WP-046a S5a) never loses text.

An existing template keeps its text under the tenant's default language: English for a tenant
with none set, Arabic for an Arabic-first one (the coordinator). Up, down and up again while
nothing uses the new parts; once a tenant has a resolution template, the downgrade is refused
(rule 5h). Rows are seeded by SQL, never through the application.
"""

import asyncio
import json
import uuid

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0149"  # 0154's down revision while building (re-pointed at its queue turn)
AFTER = "0154"


async def _template(
    url: str, tenant: uuid.UUID, name: str, body: str, language: str | None
) -> None:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            if language is not None:
                await conn.execute(
                    "INSERT INTO tenant_settings (tenant_id, default_language, languages)"
                    " VALUES ($1, $2, ARRAY['en', $2]::varchar[])"
                    " ON CONFLICT (tenant_id) DO UPDATE SET default_language = $2",
                    tenant,
                    language,
                )
            await conn.execute(
                "INSERT INTO work_item_reply_templates (id, tenant_id, type, name, body)"
                " VALUES ($1, $2, 'incident', $3, $4)",
                uuid.uuid4(),
                tenant,
                name,
                body,
            )
    finally:
        await conn.close()


async def _bodies(url: str, tenant: uuid.UUID) -> dict[str, object]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            row = await conn.fetchrow(
                "SELECT kind, visibility, bodies, body FROM work_item_reply_templates"
                " WHERE tenant_id = $1",  # the admin role bypasses RLS: filter by tenant
                tenant,
            )
            assert row is not None
            return {
                "kind": row["kind"],
                "visibility": row["visibility"],
                "bodies": json.loads(row["bodies"]),
                "body": row["body"],
            }
    finally:
        await conn.close()


async def _resolution(url: str, tenant: uuid.UUID) -> None:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO work_item_reply_templates (id, tenant_id, type, kind, name, bodies)"
                " VALUES ($1, $2, 'incident', 'resolution', 'Restarted', '{\"en\": \"<p>x</p>\"}')",
                uuid.uuid4(),
                tenant,
            )
    finally:
        await conn.close()


def test_0154_keeps_each_text_under_the_tenant_s_default_language(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        english = asyncio.run(create_tenant(database.migrator_url, "English"))
        arabic = asyncio.run(create_tenant(database.migrator_url, "Arabic"))
        asyncio.run(_template(database.admin_url, english, "Thanks", "<p>Thanks</p>", None))
        asyncio.run(_template(database.admin_url, arabic, "شكرًا", "<p>شكرًا</p>", "ar"))
        db_testing.migrate(database.migrator_url, AFTER)
        assert asyncio.run(_bodies(database.admin_url, english)) == {
            "kind": "reply",
            "visibility": "shared",
            "bodies": {"en": "<p>Thanks</p>"},
            "body": "<p>Thanks</p>",
        }
        assert asyncio.run(_bodies(database.admin_url, arabic))["bodies"] == {"ar": "<p>شكرًا</p>"}
        # Nothing new used yet: down and up again keep the text.
        db_testing.downgrade(database.migrator_url, BEFORE)
        db_testing.migrate(database.migrator_url, AFTER)
        assert asyncio.run(_bodies(database.admin_url, english))["bodies"] == {
            "en": "<p>Thanks</p>"
        }
        asyncio.run(_resolution(database.admin_url, english))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
    finally:
        db_testing.destroy(db_config, database)
