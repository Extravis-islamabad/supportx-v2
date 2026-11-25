"""Migration 0201 (group mappings; WP-057 S5c-1a) keeps today's sync and never loses data.

- **Up:**
  - a directory connector's `group_mappings` JSON becomes table rows;
  - a membership the connector's own identity made, in a group mapped from a directory group the
    person is in, becomes managed, with its source;
  - a hand-made membership in the same group stays hand-made, which is the bug this fixes: sync
    used to remove it.
- **Down** (lane B's condition 5): the JSON is rebuilt from the table, and the downgrade is
  refused while a mapping exists that the JSON can't hold (a role target).
"""

import asyncio
import json
import uuid
from typing import Any

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0203"  # 0201's down revision


async def _seed(url: str) -> dict[str, Any]:
    """A tenant, a desk and group, a directory connector with its identity, two members."""
    ids = {
        k: uuid.uuid4() for k in ("tenant", "desk", "group", "connector", "bot", "synced", "hand")
    }
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Mappings', $2)",
            ids["tenant"], f"t-{ids['tenant'].hex[:12]}",
        )  # fmt: skip
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(ids["tenant"]))
            for key, kind in (
                ("bot", "technician"),
                ("synced", "technician"),
                ("hand", "technician"),
            ):
                await conn.execute(
                    "INSERT INTO users (id, tenant_id, display_name, user_type, first_name)"
                    " VALUES ($1, $2, $3, $4, $3)",
                    ids[key], ids["tenant"], key.title(), kind,
                )  # fmt: skip
            await conn.execute(
                "INSERT INTO desks (id, tenant_id, code, labels)"
                " VALUES ($1, $2, 'it', jsonb_build_object('en', 'IT'))",
                ids["desk"], ids["tenant"],
            )  # fmt: skip
            await conn.execute(
                "INSERT INTO support_groups (id, tenant_id, name, desk_id)"
                " VALUES ($1, $2, 'Network', $3)",
                ids["group"], ids["tenant"], ids["desk"],
            )  # fmt: skip
            mappings = [
                {"external_id": "grp-net", "name": "Net team", "group_id": str(ids["group"])}
            ]
            await conn.execute(
                "INSERT INTO directory_connectors (id, tenant_id, name, group_mappings,"
                " directory_tenant, client_id, credential_kind)"
                " VALUES ($1, $2, 'Entra', $3::jsonb, 'contoso.example', 'app-1', 'secret')",
                ids["connector"], ids["tenant"], json.dumps(mappings),
            )  # fmt: skip
            await conn.execute(
                "INSERT INTO connector_identities (tenant_id, kind, instance_id, user_id)"
                " VALUES ($1, 'directory', $2, $3)",
                ids["tenant"], ids["connector"], ids["bot"],
            )  # fmt: skip
            for key, external in (("synced", "ext-synced"), ("hand", "ext-hand")):
                await conn.execute(
                    "INSERT INTO directory_people (tenant_id, connector_id, external_id, user_id)"
                    " VALUES ($1, $2, $3, $4)",
                    ids["tenant"], ids["connector"], external, ids[key],
                )  # fmt: skip
                await conn.execute(
                    "INSERT INTO directory_memberships"
                    " (tenant_id, connector_id, group_external_id, external_id)"
                    " VALUES ($1, $2, 'grp-net', $3)",
                    ids["tenant"], ids["connector"], external,
                )  # fmt: skip
            # The synced person's membership was made by the connector's identity; the other
            # person was added by hand (another person), though also in the directory group.
            for key, made_by in (("synced", ids["bot"]), ("hand", ids["synced"])):
                await conn.execute(
                    "INSERT INTO group_members (tenant_id, group_id, user_id, created_by)"
                    " VALUES ($1, $2, $3, $4)",
                    ids["tenant"], ids["group"], ids[key], made_by,
                )  # fmt: skip
    finally:
        await conn.close()
    return ids


async def _query(url: str, tenant: uuid.UUID, sql: str, *args: Any) -> list[asyncpg.Record]:  # noqa: ANN401 - asyncpg args
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            return list(await conn.fetch(sql, *args))
    finally:
        await conn.close()


def test_0201_backfills_keeps_hand_made_access_and_downgrades_safely(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        ids = asyncio.run(_seed(database.admin_url))
        tenant = ids["tenant"]
        db_testing.migrate(database.migrator_url, "0201")

        rows = asyncio.run(_query(database.admin_url, tenant, "SELECT * FROM idp_group_mappings"))
        assert [
            (r["source_kind"], r["source_id"], r["external_group_id"], r["group_id"]) for r in rows
        ] == [("directory", ids["connector"], "grp-net", ids["group"])]
        assert rows[0]["external_name"] == "Net team"
        mapping = rows[0]["id"]
        members = {
            r["user_id"]: r["managed"]
            for r in asyncio.run(
                _query(database.admin_url, tenant, "SELECT user_id, managed FROM group_members")
            )
        }
        assert members == {ids["synced"]: True, ids["hand"]: False}  # hand-made stays hand-made
        sources = asyncio.run(
            _query(
                database.admin_url,
                tenant,
                "SELECT user_id, target_id, mapping_id FROM access_sources",
            )
        )
        assert [(s["user_id"], s["target_id"], s["mapping_id"]) for s in sources] == [
            (ids["synced"], ids["group"], mapping)
        ]

        # A role target can't go back into the JSON: the downgrade refuses, and nothing changes.
        role = uuid.uuid4()
        asyncio.run(
            _query(
                database.admin_url, tenant,
                "WITH r AS (INSERT INTO roles (id, tenant_id, key, name)"
                " VALUES ($1, $2, $3, 'Admins') RETURNING id) INSERT INTO idp_group_mappings"
                " (id, tenant_id, source_kind, source_id, external_group_id, role_id)"
                " SELECT gen_random_uuid(), $2, 'directory', $4, 'grp-admins', id FROM r",
                role, tenant, f"custom_{role.hex[:8]}", ids["connector"],
            )
        )  # fmt: skip
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)

        # Without it, the downgrade rebuilds the JSON from the table (a renamed mapping included).
        asyncio.run(
            _query(
                database.admin_url, tenant,
                "UPDATE idp_group_mappings SET deleted_at = now() WHERE role_id IS NOT NULL",
            )
        )  # fmt: skip
        asyncio.run(
            _query(
                database.admin_url, tenant,
                "UPDATE idp_group_mappings SET external_name = 'Network team' WHERE id = $1",
                mapping,
            )
        )  # fmt: skip
        db_testing.downgrade(database.migrator_url, BEFORE)
        kept = asyncio.run(
            _query(database.admin_url, tenant, "SELECT group_mappings FROM directory_connectors")
        )
        assert json.loads(kept[0]["group_mappings"]) == [
            {"external_id": "grp-net", "name": "Network team", "group_id": str(ids["group"])}
        ]
        db_testing.migrate(database.migrator_url, "0201")  # and up again
    finally:
        db_testing.destroy(db_config, database)
