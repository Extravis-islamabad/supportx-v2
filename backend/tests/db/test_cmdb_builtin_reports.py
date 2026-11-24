"""The CMDB's built-in reports (lane C, on lane B's sources from #606; REQ-CMDB-032, REQ-RPT-015).

- "CIs by type and state" and "CI relationships" run for the admin and name every type, state
  and relationship type in the reader's language, never as an ID.
- Their totals are what the reader may see: the CI report adds up to the CMDB list's own count,
  and a relationship to a CI the reader may not see is not counted (the sources' narrowing,
  ADR-053).
- They are filed under the CMDB in the library, for those who may see CIs only.

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h).
"""

import uuid
from typing import Any

import httpx
import pytest

from app.modules.analytics.domain.builtin import BUILTIN
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_api import _types
from tests.db.test_cmdb_relationships import _link
from tests.db.test_cmdb_reports import CI_RIGHTS, _listed
from tests.db.test_incidents_api import CONSOLE, Org, World
from tests.db.test_resource_access import _edition, _holding, _made, _rule

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

CIS = "cmdb_cis_by_type_and_state"
RELATIONSHIPS = "cmdb_relationships_by_type"


async def _run(world: World, org: Org, user: uuid.UUID, code: str) -> httpx.Response:
    definition = BUILTIN[code].definition.model_dump(mode="json")
    return await world.call(
        "POST",
        "/reports/run",
        org,
        user,
        json={"definition": definition, "language": "ar"},
        headers=CONSOLE,
    )


def _total(body: dict[str, Any]) -> int:
    return sum(int(row["values"][0]) for row in body["rows"])


async def test_the_cmdb_built_ins_run_and_name_their_values(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    tag = uuid.uuid4().hex[:6]
    app = await _made(world, a, f"Built-in server {tag}", "server")
    db = await _made(world, a, f"Built-in database {tag}", "database")
    assert (await _link(world, a, app, "depends_on", [db])).status_code == 201

    ran = await _run(world, a, a.admin, CIS)
    assert ran.status_code == 200, ran.text
    body = ran.json()
    assert _total(body) == len(await _listed(world, a, a.admin))  # the list's own count
    types = {row["keys"][0] for row in body["rows"]}
    states = {row["keys"][1] for row in body["rows"]}
    assert set(body["names"]["type_id"]) == types  # every one named, none as an ID
    assert set(body["names"]["state_id"]) == states

    ran = await _run(world, a, a.admin, RELATIONSHIPS)
    assert ran.status_code == 200, ran.text
    body = ran.json()
    assert _total(body) >= 1
    assert set(body["names"]["type_id"]) == {row["keys"][0] for row in body["rows"]}


async def test_a_narrowed_reader_counts_only_what_they_may_see(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    tag = uuid.uuid4().hex[:6]
    app = await _made(world, a, f"Narrow server {tag}", "server")
    other = await _made(world, a, f"Narrow server two {tag}", "server")
    hidden = await _made(world, a, f"Narrow database {tag}", "database")
    assert (await _link(world, a, app, "depends_on", [hidden])).status_code == 201
    assert (await _link(world, a, app, "connected_to", [other])).status_code == 201

    admin = await _run(world, a, a.admin, RELATIONSHIPS)
    assert admin.status_code == 200, admin.text
    async with _holding(world, a, a.requester, [*CI_RIGHTS, ("reports.view", "all")]) as narrowed:
        made = await _rule(world, a, narrowed, "ci", {"type_ids": [types["server"]["id"]]})
        assert made.status_code == 201, made.text
        await _edition(world, a, "enterprise")  # drops the cached subjects
        cis = await _run(world, a, a.requester, CIS)
        assert cis.status_code == 200, cis.text
        assert _total(cis.json()) == len(await _listed(world, a, a.requester))
        assert set(cis.json()["names"]["type_id"]) == {types["server"]["id"]}
        rels = await _run(world, a, a.requester, RELATIONSHIPS)
        assert rels.status_code == 200, rels.text
        # The link to the hidden database is not counted; the admin counts it.
        assert _total(rels.json()) < _total(admin.json())


async def test_the_library_files_them_under_the_cmdb_for_ci_viewers_only(world: World) -> None:
    a = world.a
    listed = await world.call("GET", "/reports/library", a, a.admin)
    assert listed.status_code == 200, listed.text
    folders = {r["code"]: r["folder"] for r in listed.json()["builtin"]}
    assert folders.get(CIS) == "cmdb"
    assert folders.get(RELATIONSHIPS) == "cmdb"
    # A requester holds no CMDB right: neither report is offered to them.
    requester = await world.call("GET", "/reports/library", a, a.requester)
    if requester.status_code == 200:
        offered = {r["code"] for r in requester.json()["builtin"]}
        assert not {CIS, RELATIONSHIPS} & offered
    else:
        assert requester.status_code == 403, requester.text
