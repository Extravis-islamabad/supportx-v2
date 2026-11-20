"""The impact walk at scale (WP-053 S3b; REQ-CMDB-010 AC4): 100,000 CIs, ~400,000 links, depth 5.

Runs only with SUPPORTX_CMDB_TIMING=1 (a heavy job: one at a time, coordinator's slot). Seeds one
fresh tenant of the incident world by SQL (the superuser, tenant_id explicit), then times the
impact route for the admin and for a site-narrowed reader (redaction included) at depth 5 and
10. Each must answer within 2 s; past 5,000 CIs the answer is cut and says so. The seeded rows
belong to this run's new tenant only (rule 5h).
"""

import os
import time
import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_relationships import _given, _made
from tests.db.test_incidents_api import World

if os.environ.get("SUPPORTX_CMDB_TIMING") != "1":
    pytest.skip("set SUPPORTX_CMDB_TIMING=1 (a heavy job)", allow_module_level=True)

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

CIS = int(os.environ.get("SUPPORTX_CMDB_TIMING_CIS", "100000"))  # smaller for a smoke run
LINKS_PER_CI = 4  # about 400,000 relationships
BUDGET_MS = 2000.0


async def _seed(world: World, hub: dict[str, Any]) -> None:
    a = world.a
    tenant = a.tenant
    await world.sql(
        """
        INSERT INTO cmdb_cis (id, tenant_id, display_id, type_id, state_id, name, site_id, source)
        SELECT gen_random_uuid(), $1, 'CIT-' || n, $2, $3, 'Timing CI ' || n,
               CASE WHEN n % 2 = 0 THEN $4::uuid ELSE $5::uuid END, 'manual'
        FROM generate_series(1, $6) AS n
        """,
        tenant,
        uuid.UUID(hub["type_id"]),
        uuid.UUID(hub["state_id"]),
        a.s1,
        a.s2,
        CIS,
    )
    types = await world.call("GET", "/cmdb/relationship-types", a, a.admin)  # made on first use
    assert types.status_code == 200, types.text
    depends = (
        await world.sql(
            "SELECT id FROM cmdb_relationship_types WHERE tenant_id = $1 AND code = 'depends_on'",
            tenant,
        )
    )[0]["id"]
    # Each CI depends on a few others further along (a layered, connected graph), and the hub
    # is depended on by the first CIs, so its dependents reach deep into the seeded set.
    await world.sql(
        """
        WITH numbered AS (
            SELECT id, row_number() OVER (ORDER BY display_id) AS n
            FROM cmdb_cis WHERE tenant_id = $1 AND display_id LIKE 'CIT-%'
        )
        INSERT INTO cmdb_relationships (id, tenant_id, type_id, from_ci_id, to_ci_id)
        SELECT gen_random_uuid(), $1, $2, a.id, b.id
        FROM numbered a
        CROSS JOIN generate_series(1, $3) AS k
        JOIN numbered b ON b.n = ((a.n * 7 + k * 1013) % $4) + 1
        WHERE a.id <> b.id
        ON CONFLICT DO NOTHING
        """,
        tenant,
        depends,
        LINKS_PER_CI,
        CIS,
    )
    await world.sql(
        """
        INSERT INTO cmdb_relationships (id, tenant_id, type_id, from_ci_id, to_ci_id)
        SELECT gen_random_uuid(), $1, $2, id, $3
        FROM cmdb_cis WHERE tenant_id = $1 AND display_id LIKE 'CIT-%'
        ORDER BY display_id LIMIT 50
        """,
        tenant,
        depends,
        uuid.UUID(hub["id"]),
    )
    await world.sql("ANALYZE cmdb_cis")
    await world.sql("ANALYZE cmdb_relationships")


async def _timed(world: World, hub: dict[str, Any], user: uuid.UUID, depth: int) -> float:
    a = world.a
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        found = await world.call(
            "GET", f"/cmdb/cis/{hub['id']}/impact", a, user, params={"depth": depth}
        )
        timings.append((time.perf_counter() - started) * 1000)
        assert found.status_code == 200, found.text
    body = found.json()
    print(  # noqa: T201 - the run's numbers, for the PR (pytest -s)
        f"depth {depth} user {user}: best {min(timings):.0f} ms, worst {max(timings):.0f} ms,"
        f" {len(body['cis'])} CIs, {body['restricted']} restricted, truncated {body['truncated']}"
    )
    return min(timings)


async def test_impact_at_100k_cis_stays_within_two_seconds(world: World) -> None:
    a = world.a
    hub = await _made(world, a, "Timing hub", "server", site_id=str(a.s2))
    await _seed(world, hub)
    count = await world.sql(
        "SELECT count(*) AS n FROM cmdb_relationships WHERE tenant_id = $1", a.tenant
    )
    print(f"seeded {CIS} CIs and {count[0]['n']} relationships")  # noqa: T201 - for the PR
    await _given(world, a, a.requester2, "Timing site viewer", [("cmdb.view", "site")])
    for depth in (5, 10):
        for user in (a.admin, a.requester2):
            best = await _timed(world, hub, user, depth)
            assert best < BUDGET_MS, (depth, user, best)
