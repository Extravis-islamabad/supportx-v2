"""tooling.e2e_fixtures creates and deletes only its own rows."""

import asyncio

import asyncpg
import pytest

from tooling import db_testing, e2e_fixtures, seed_dev

pytestmark = pytest.mark.db


async def _users(url: str) -> list[str]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch("SELECT email FROM users ORDER BY email")
    finally:
        await conn.close()
    return [r["email"] for r in rows]


def test_create_is_idempotent_and_delete_removes_only_fixtures(
    db_config: db_testing.DbTestConfig,
) -> None:
    # Own database: the fixtures go into the fixed Demo tenant, which other tests share.
    database = db_testing.create(db_config)
    try:
        asyncio.run(_scenario(database))
    finally:
        db_testing.destroy(db_config, database)


async def _scenario(database: db_testing.ThrowawayDatabase) -> None:
    await seed_dev.seed(database.migrator_url)
    conn = await asyncpg.connect(database.admin_url)
    await conn.execute(
        "INSERT INTO users (id, tenant_id, external_subject, email, display_name, user_type)"
        " VALUES (gen_random_uuid(), $1, 'keep', 'keep@demo.test', 'Keep', 'technician')",
        seed_dev.DEMO_TENANT_ID,
    )
    await conn.close()
    assert await e2e_fixtures.create(database.migrator_url) == e2e_fixtures.COUNT
    assert await e2e_fixtures.create(database.migrator_url) == 0
    assert len(await _users(database.admin_url)) == e2e_fixtures.COUNT + 1
    assert await e2e_fixtures.delete(database.migrator_url) == e2e_fixtures.COUNT
    assert await _users(database.admin_url) == ["keep@demo.test"]
    await _suite_records(database)


async def _work_item_config(conn: asyncpg.Connection) -> None:
    """Templates and pick-list values (WP-020c).

    Only the suite's own go; a shipped value with an "E2E" label and a default template stay.
    """
    for name, default in (("E2E outage", False), ("E2E default", True), ("Keep", False)):
        await conn.execute(
            "INSERT INTO work_item_templates (id, tenant_id, type, labels, is_default)"
            " VALUES (gen_random_uuid(), $1, 'incident', jsonb_build_object('en', $2::text),"
            " $3)",
            seed_dev.DEMO_TENANT_ID,
            name,
            default,
        )
    for code, name in (("v_e2e1", "E2E level"), ("tier_1", "E2E renamed"), ("v_keep", "Keep")):
        await conn.execute(
            "INSERT INTO work_item_reasons (tenant_id, type, list, code, labels, sort_order)"
            " VALUES ($1, 'incident', 'level', $2, jsonb_build_object('en', $3::text), 0)",
            seed_dev.DEMO_TENANT_ID,
            code,
            name,
        )


async def _suite_records(database: db_testing.ThrowawayDatabase) -> None:
    """Only "E2E …" announcements and sites (and their history) go; everything else stays."""
    conn = await asyncpg.connect(database.admin_url)
    try:
        owner = await conn.fetchval("SELECT id FROM users WHERE email = 'keep@demo.test'")
        suite_user = await conn.fetchval(
            "INSERT INTO users (id, tenant_id, external_subject, email, display_name, user_type)"
            " VALUES (gen_random_uuid(), $1, 'e2e', 'e2e.tech@demo.test', 'Erin', 'technician')"
            " RETURNING id",
            seed_dev.DEMO_TENANT_ID,
        )
        for user in (owner, suite_user):
            await conn.execute(
                "INSERT INTO field_changes (id, tenant_id, record_type, record_id,"
                " record_version, change_id, kind, field, actor_type, source, occurred_at)"
                " VALUES (gen_random_uuid(), $1, 'user', $2, 2, gen_random_uuid(),"
                " 'updated', 'signature', 'user', 'ui', now())",
                seed_dev.DEMO_TENANT_ID,
                user,
            )
        for title in ("E2E Suite note", "Keep this note"):
            record = await conn.fetchval(
                "INSERT INTO announcements (id, tenant_id, display_id, title, body, owner_id)"
                " VALUES (gen_random_uuid(), $1, $2, $3, 'b', $4) RETURNING id",
                seed_dev.DEMO_TENANT_ID,
                f"ANN-{title[:4]}",
                title,
                owner,
            )
            await conn.execute(
                "INSERT INTO field_changes (id, tenant_id, record_type, record_id,"
                " record_version, change_id, kind, field, actor_type, source, occurred_at)"
                " VALUES (gen_random_uuid(), $1, 'announcement', $2, 1, gen_random_uuid(),"
                " 'created', 'title', 'system', 'api', now())",
                seed_dev.DEMO_TENANT_ID,
                record,
            )
        for tenant in (seed_dev.DEMO_TENANT_ID, seed_dev.OTHER_TENANT_ID):
            for name in ("E2E Site North", "Head office"):
                await conn.execute(
                    "INSERT INTO sites (id, tenant_id, name) VALUES (gen_random_uuid(), $1, $2)",
                    tenant,
                    name,
                )
        # Support groups (WP-020): "E2E …" groups and their members go; others stay.
        for tenant in (seed_dev.DEMO_TENANT_ID, seed_dev.OTHER_TENANT_ID):
            for name in ("E2E Desk", "Help desk"):
                group = await conn.fetchval(
                    "INSERT INTO support_groups (id, tenant_id, name)"
                    " VALUES (gen_random_uuid(), $1, $2) RETURNING id",
                    tenant,
                    name,
                )
                if tenant == seed_dev.DEMO_TENANT_ID and name == "E2E Desk":
                    await conn.execute(
                        "INSERT INTO group_members (tenant_id, group_id, user_id)"
                        " VALUES ($1, $2, $3)",
                        tenant,
                        group,
                        owner,
                    )
        # Roles: only a soft-deleted custom "E2E …" role goes (with its permissions).
        for key, name, deleted, system in (
            ("e2e_old", "E2E reports 1", True, False),
            ("e2e_live", "E2E reports 2", False, False),
            ("helpdesk", "Helpdesk", True, False),
            ("e2e_sys", "E2E system", True, True),
        ):
            role_id = await conn.fetchval(
                "INSERT INTO roles (id, tenant_id, key, name, is_system, deleted_at)"
                " VALUES (gen_random_uuid(), $1, $2, $3, $4,"
                " CASE WHEN $5 THEN now() END) RETURNING id",
                seed_dev.DEMO_TENANT_ID,
                key,
                name,
                system,
                deleted,
            )
            await conn.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, permission, scope)"
                " VALUES ($1, $2, 'announcements.view', 'all')",
                seed_dev.DEMO_TENANT_ID,
                role_id,
            )
        await _work_item_config(conn)
    finally:
        await conn.close()

    removed = await e2e_fixtures.delete_suite_records(database.migrator_url)
    assert removed == {
        "field_changes": 2,
        "announcements": 1,
        "work_item_conversations": 0,  # with their incidents (WP-020b)
        "work_item_followers": 0,
        "work_items": 0,  # incidents: covered by the e2e run (none may remain afterwards)
        "work_item_templates": 1,
        "work_item_reasons": 1,
        "group_members": 1,
        "support_groups": 2,
        "site_members": 0,
        "sites": 2,
        "user_roles": 0,
        "roles": 1,
    }

    conn = await asyncpg.connect(database.admin_url)
    try:
        titles = await conn.fetch("SELECT title FROM announcements")
        history = await conn.fetch("SELECT record_type, field FROM field_changes ORDER BY 1")
        sites = await conn.fetch("SELECT name FROM sites ORDER BY tenant_id")
        groups = await conn.fetch("SELECT name FROM support_groups ORDER BY tenant_id")
        roles = await conn.fetch("SELECT name FROM roles ORDER BY name")
        grants = await conn.fetchval("SELECT count(*) FROM role_permissions")
    finally:
        await conn.close()
    assert [r["title"] for r in titles] == ["Keep this note"]
    # Kept: the other announcement's history and the non-suite user's.
    assert [(r["record_type"], r["field"]) for r in history] == [
        ("announcement", "title"),
        ("user", "signature"),
    ]
    assert [r["name"] for r in sites] == ["Head office", "Head office"]
    assert [r["name"] for r in groups] == ["Help desk", "Help desk"]
    assert [r["name"] for r in roles] == ["E2E reports 2", "E2E system", "Helpdesk"]
    assert grants == 3
