"""Migration 0206 (WP-057 S6b): the mobile app policy's columns and checks on identity_settings.

Up adds them with defaults that change nothing (a row saved before keeps the app allowed). The
checks hold: the unlock time, the two limits set together within bounds, messages keyed en, ar
or ur only. Down drops them, and refuses while a tenant has switched the app off (it would be
allowed again without anyone deciding so; rule 5h).
"""

import asyncio
import json
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0205"  # 0206's down revision


async def _tenant_with_settings(url: str) -> uuid.UUID:
    """A tenant whose settings row was saved before 0206."""
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Mobile', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO identity_settings (tenant_id, console_idle_seconds) VALUES ($1, 1800)",
                tenant,
            )
        return tenant
    finally:
        await conn.close()


async def _run(url: str, tenant: uuid.UUID, statement: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            return list(await conn.fetch(statement, *args))
    finally:
        await conn.close()


def test_0206_adds_the_policy_with_harmless_defaults_and_its_checks(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        tenant = asyncio.run(_tenant_with_settings(database.admin_url))
        db_testing.migrate(database.migrator_url, "0206")
        row = asyncio.run(
            _run(
                database.admin_url,
                tenant,
                "SELECT mobile_allowed, mobile_clear_on_sign_out, mobile_mfa_required,"
                " mobile_unlock_after_minutes, mobile_idle_seconds FROM identity_settings",
            )
        )[0]
        assert tuple(row) == (True, True, False, 5, None)  # nothing changes for anyone
        for change, value in (
            ("mobile_unlock_after_minutes = $1", 61),
            ("mobile_idle_seconds = $1", 600),  # without its absolute limit
            ("mobile_refusal_message = $1::jsonb", json.dumps({"fr": "Non"})),
        ):
            with pytest.raises(asyncpg.CheckViolationError):
                asyncio.run(
                    _run(
                        database.admin_url,
                        tenant,
                        f"UPDATE identity_settings SET {change}",  # noqa: S608 - this test's constants
                        value,
                    )
                )
        asyncio.run(
            _run(
                database.admin_url,
                tenant,
                "UPDATE identity_settings SET mobile_idle_seconds = 600,"
                " mobile_absolute_seconds = 7200, mobile_refusal_message = $1::jsonb",
                json.dumps({"en": "Use the web console.", "ur": "ویب کنسول استعمال کریں"}),
            )
        )
        db_testing.downgrade(database.migrator_url, BEFORE)
        db_testing.migrate(database.migrator_url, "0206")
        asyncio.run(
            _run(
                database.admin_url,
                tenant,
                "UPDATE identity_settings SET mobile_allowed = false",
            )
        )
        with pytest.raises(Exception, match="switched the mobile app off"):
            db_testing.downgrade(database.migrator_url, BEFORE)
    finally:
        db_testing.destroy(db_config, database)
