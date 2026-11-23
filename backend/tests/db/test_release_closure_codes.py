"""A release's own closure codes (WP-058b S4; REQ-REL-050; seed version 5).

- A new tenant's releases close with release codes (completed, rolled back, …), never an
  incident's "fixed" or "workaround".
- A tenant seeded before them is topped up once: the release codes are added, and an
  incident-style code is switched off only while untouched and unused. A code a release closed
  with, or one the tenant renamed, stays on. One audit entry; a second read changes nothing.
"""

import json
from typing import Any

import asyncpg

from app.modules.work_items.domain.templates import RELEASE_CLOSURE_CODES
from tests.db.test_incidents_api import World, world
from tests.db.test_releases_api import REL, a_release

__all__ = ["world"]  # the fixture, re-used

INCIDENT_STYLE = (
    "fixed",
    "workaround",
    "no_fault_found",
    "duplicate",
    "user_error",
    "confirmed_by_requester",
)


async def _codes(world: World) -> dict[str, bool]:
    a = world.a
    got = await world.call("GET", f"{REL}/settings", a, a.admin)
    assert got.status_code == 200, got.text
    return {v["code"]: v["disabled"] for v in got.json()["closure_codes"]}


async def _audits(world: World) -> list[dict[str, Any]]:
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        rows = await conn.fetch(
            "SELECT details FROM audit_entries WHERE tenant_id = $1"
            " AND action = 'work_item.settings_topped_up'",
            world.a.tenant,
        )
    finally:
        await conn.close()
    found = [
        json.loads(r["details"]) if isinstance(r["details"], str) else r["details"] for r in rows
    ]
    return [d for d in found if "closure_codes_added" in d]


async def test_req_rel_050_a_new_tenant_s_releases_close_with_release_codes(world: World) -> None:
    codes = await _codes(world)
    assert list(codes) == list(RELEASE_CLOSURE_CODES)
    assert not any(codes.values())


async def test_an_older_tenant_is_topped_up_once_keeping_used_and_renamed_codes(
    world: World,
) -> None:
    a = world.a
    item = await a_release(world, a)  # seeds the release settings at the current version
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        # What a tenant seeded before version 5 has: an incident's closure codes on releases.
        await conn.execute(
            "DELETE FROM work_item_reasons WHERE tenant_id = $1 AND type = 'release'"
            " AND list = 'closure_code'",
            a.tenant,
        )
        for i, code in enumerate(INCIDENT_STYLE):
            await conn.execute(
                "INSERT INTO work_item_reasons (tenant_id, type, list, code, sort_order)"
                " VALUES ($1, 'release', 'closure_code', $2, $3)",
                a.tenant,
                code,
                i,
            )
        # Renamed by the tenant, and used by a release: both must stay on.
        await conn.execute(
            'UPDATE work_item_reasons SET labels = \'{"en": "Patched"}\'::jsonb'
            " WHERE tenant_id = $1 AND type = 'release' AND code = 'workaround'",
            a.tenant,
        )
        await conn.execute(
            "UPDATE work_items SET closure_code = 'fixed' WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            item["id"],
        )
        await conn.execute(
            "UPDATE work_item_type_settings SET seed_version = 4"
            " WHERE tenant_id = $1 AND type = 'release'",
            a.tenant,
        )
    finally:
        await conn.close()

    codes = await _codes(world)
    assert set(RELEASE_CLOSURE_CODES) <= set(codes)
    assert not any(codes[c] for c in RELEASE_CLOSURE_CODES)
    assert codes["fixed"] is False  # a release closed with it
    assert codes["workaround"] is False  # the tenant renamed it
    for untouched in ("no_fault_found", "duplicate", "user_error", "confirmed_by_requester"):
        assert codes[untouched] is True, untouched
    [entry] = await _audits(world)
    assert entry["type"] == "release"
    assert sorted(entry["closure_codes_added"]) == sorted(RELEASE_CLOSURE_CODES)
    assert entry["closure_codes_disabled"] == sorted(
        ["confirmed_by_requester", "duplicate", "no_fault_found", "user_error"]
    )
    # A second read changes nothing: no new audit entry, the same codes.
    assert await _codes(world) == codes
    assert len(await _audits(world)) == 1
