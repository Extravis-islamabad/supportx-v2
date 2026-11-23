"""CMDB merge, aliases and import over HTTP (WP-053 S4b; REQ-CMDB-017, 018; 0192).

With the coordinator's conditions (3) to (6) and lane C's (6) to (10): manage on both CIs, an
alias that opens the survivor only for a reader who may see it (record, picker, impact, refs),
D-092's limits and formula-safe error reports, imports as background jobs with live progress
and an Idempotency-Key, a merge preview that never shows a withheld field, a restore that warns
and moves nothing, and an import in which an unseen CI is exactly a missing one.

Real PostgreSQL and Valkey on the incident world (two organisations; the admin holds
everything). Every organisation is new for the module, so nothing here touches dev data
(rule 5h). Who else is who (roles given once, below):
    requester2  member of site S2: sees and edits S2's CIs only (cmdb.add and cmdb.manage take
                only "all", so the site view decides what they may merge)
    requester   member of site S1: sees S1's CIs only
    tech_c      sees and edits every CI, without cmdb.manage
"""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.cmdb.service import imports, links
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_api import _ci, _types
from tests.db.test_cmdb_custom_fields import _field, _role_id
from tests.db.test_cmdb_custom_fields import _rule as field_rule
from tests.db.test_cmdb_relationships import _given, _link, _rel_types
from tests.db.test_incidents_api import Org, World, field_codes, problem, role
from tests.db.test_knowledge_api import _match, _new

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

BASE = "/cmdb"
TABLES = ("cmdb_ci_aliases", "cmdb_imports")


_CAST: dict[uuid.UUID, dict[str, Any]] = {}


async def _cast(world: World) -> dict[str, Any]:
    """The roles of the module's docstring, given once per tenant (a module's roles add up)."""
    a = world.a
    if a.tenant in _CAST:
        return _CAST[a.tenant]
    s2_role = await role(
        world, a, "S2 CMDB manager",
        [("cmdb.view", "site"), ("cmdb.add", "all"), ("cmdb.edit", "site"),
         ("cmdb.manage", "all")],
    )  # fmt: skip
    assigned = await world.call("PUT", f"/users/{a.requester2}/roles/{s2_role}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    await _given(world, a, a.requester, "S1 CMDB viewer", [("cmdb.view", "site")])
    await _given(
        world, a, a.tech_c, "CMDB editor, all seen, no manage",
        [("cmdb.view", "all"), ("cmdb.edit", "all")],
    )  # fmt: skip
    # A field is clear for a person while any of their roles has no rule: requester2's two.
    _CAST[a.tenant] = {"roles": [s2_role, await _role_id(world, a, "requester")]}
    return _CAST[a.tenant]


async def _made(
    world: World,
    org: Org,
    name: str,
    type_code: str = "server",
    **extra: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    made = await _ci(world, org, name, type_code, **extra)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _get(world: World, org: Org, ci_id: str, user: uuid.UUID) -> httpx.Response:
    return await world.call("GET", f"{BASE}/cis/{ci_id}", org, user)


async def _merge(
    world: World,
    org: Org,
    survivor: dict[str, Any],
    merged: dict[str, Any],
    *,
    user: uuid.UUID | None = None,
    choices: dict[str, str] | None = None,
) -> httpx.Response:
    return await world.call(
        "POST",
        f"{BASE}/merges",
        org,
        user or org.admin,
        json={
            "survivor_id": survivor["id"],
            "survivor_version": survivor["version"],
            "merged_id": merged["id"],
            "merged_version": merged["version"],
            "choices": choices or {},
        },
        headers=_new(),
    )


async def _fresh(world: World, org: Org, ci: dict[str, Any]) -> dict[str, Any]:
    found = await _get(world, org, ci["id"], org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


# --- tenant isolation (rule a) --------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
async def test_s4b_tables_are_isolated_by_rls(world: World, table: str) -> None:
    a, b = world.a, world.b
    keep = await _made(world, a, "RLS keep")
    dupe = await _made(world, a, "RLS dupe")
    assert (await _merge(world, a, keep, dupe)).status_code == 201
    started = await _upload(world, a, b"Name\nRLS row\n", type_code="server")
    assert started.status_code == 201, started.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() > 0  # noqa: S608 - fixed table names
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert seen.scalar_one() == 0
        changed = await session.execute(
            text(f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert changed.rowcount == 0
    # Over HTTP too: B never opens A's merged CI nor A's import.
    assert problem(await _get(world, b, dupe["id"], b.admin)) == (404, "cmdb_ci_not_found")
    other = await world.call("GET", f"{BASE}/imports/{started.json()['id']}", b, b.admin)
    assert problem(other) == (404, "cmdb_import_not_found")


# --- merge (REQ-CMDB-017) -------------------------------------------------------------------------


async def test_merging_collapses_duplicate_links_and_both_ids_open_the_survivor(
    world: World,
) -> None:
    """AC1: two links to the same service end as one; AC2: both IDs open the survivor."""
    a = world.a
    service = await _made(world, a, "Payroll service", "business_service")
    keep = await _made(world, a, "Payroll app", "application", description=None)
    dupe = await _made(world, a, "Payroll app (old)", "application", description="Kept text")
    other = await _made(world, a, "Payroll db", "database")
    for ci in (keep, dupe):
        assert (await _link(world, a, ci, "depends_on", [service])).status_code == 201
    assert (await _link(world, a, dupe, "depends_on", [other])).status_code == 201
    keep, dupe = await _fresh(world, a, keep), await _fresh(world, a, dupe)
    preview = await world.call(
        "GET", f"{BASE}/merges/preview", a, a.admin,
        params={"first": keep["id"], "second": dupe["id"]},
    )  # fmt: skip
    assert preview.status_code == 200, preview.text
    sides = {f["field"]: f["side"] for f in preview.json()["fields"]}
    assert sides["description"] == "merged"  # the survivor has none
    assert sides["name"] == "survivor"
    done = await _merge(world, a, keep, dupe)
    assert done.status_code == 201, done.text
    body = done.json()
    assert body["survivor"]["description"] == "Kept text"
    assert body["moved"]["relationships"] == 1  # the db; the second service link collapsed
    links_now = await world.sql(
        "SELECT from_ci_id, to_ci_id FROM cmdb_relationships"
        " WHERE tenant_id = $1 AND deleted_at IS NULL AND (from_ci_id = $2 OR from_ci_id = $3)",
        a.tenant,
        uuid.UUID(keep["id"]),
        uuid.UUID(dupe["id"]),
    )
    pairs = sorted((str(r["from_ci_id"]), str(r["to_ci_id"])) for r in links_now)
    assert pairs == sorted([(keep["id"], service["id"]), (keep["id"], other["id"])])
    # AC2: the merged CI's ID opens the survivor; its display ID finds it in the picker.
    merged = await _get(world, a, dupe["id"], a.admin)
    assert problem(merged) == (404, "cmdb_ci_merged")
    assert merged.json()["params"]["survivor_id"] == keep["id"]
    picked = await world.call(
        "GET", f"{BASE}/cis/picker", a, a.admin, params={"search": dupe["display_id"]}
    )
    assert [c["id"] for c in picked.json()["items"]] == [keep["id"]]
    # History: each side names the other by ID only, never by name.
    history = await world.call("GET", f"{BASE}/cis/{keep['id']}/history", a, a.admin)
    lines = [c for e in history.json()["items"] for c in e["changes"]]
    assert any(c["field"] == "merged_from" and c["new"] == {"ci_id": dupe["id"]} for c in lines)
    assert "Payroll app (old)" not in str([c for c in lines if c["field"] == "merged_from"])
    # One audit entry with the mapping.
    entries = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = 'cmdb.ci_merged'"
        " AND object_id = $2",
        a.tenant,
        keep["id"],
    )
    assert len(entries) == 1


async def test_a_merge_calls_the_links_port_with_both_ids_only(world: World) -> None:
    """Lane A's contract: (session, from, to, *, source) -> int, IDs only (pinned until S5)."""
    a = world.a
    calls: list[tuple[uuid.UUID, uuid.UUID, str]] = []

    async def port(
        session: Any,  # noqa: ANN401 - the session, unused here
        from_ci_id: uuid.UUID,
        to_ci_id: uuid.UUID,
        *,
        source: str = "system",
    ) -> int:
        del session
        calls.append((from_ci_id, to_ci_id, source))
        return 3

    keep = await _made(world, a, "Port keep")
    dupe = await _made(world, a, "Port dupe")
    links.register_ci_links(port)
    try:
        done = await _merge(world, a, keep, dupe)
    finally:
        links.clear_ci_links()
    assert done.status_code == 201, done.text
    # The person's own source (the console here), passed on by keyword.
    assert calls == [(uuid.UUID(dupe["id"]), uuid.UUID(keep["id"]), "ui")]
    assert done.json()["moved"]["work_items"] == 3
    # Without a port (before S5) nothing moves and the merge still succeeds.
    third = await _made(world, a, "Port third")
    keep = await _fresh(world, a, keep)
    assert (await _merge(world, a, keep, third)).json()["moved"]["work_items"] == 0


async def test_a_merge_needs_manage_on_both_cis(world: World) -> None:
    """The coordinator's (3): unseen is 404, seen but not managed is 403; the admin may."""
    a = world.a
    await _cast(world)
    s1 = await _made(world, a, "Manage S1", site_id=str(a.s1))
    s2 = await _made(world, a, "Manage S2", site_id=str(a.s2))
    s2b = await _made(world, a, "Manage S2 b", site_id=str(a.s2))
    # requester2 manages S2 only and never sees S1: the S1 CI is a CI that exists nowhere.
    unseen = await _merge(world, a, s2, s1, user=a.requester2)
    nowhere = await _merge(world, a, s2, {**s1, "id": str(uuid.uuid4())}, user=a.requester2)
    assert problem(unseen) == problem(nowhere) == (404, "cmdb_ci_not_found")
    # tech_c sees both but may not manage CIs: 403, never a merge.
    assert (await _merge(world, a, s1, s2, user=a.tech_c)).status_code == 403
    # Negative control: within their own site, requester2 merges.
    assert (await _merge(world, a, s2, s2b, user=a.requester2)).status_code == 201


async def test_an_alias_never_opens_a_survivor_the_reader_cannot_see(world: World) -> None:
    """The coordinator's (3), lane C (8): record, picker, impact and refs read as nowhere."""
    a = world.a
    await _cast(world)
    survivor = await _made(world, a, "Hidden survivor", site_id=str(a.s1))
    merged = await _made(world, a, "Seen duplicate", site_id=str(a.s2))
    assert (await _merge(world, a, survivor, merged)).status_code == 201
    nowhere = str(uuid.uuid4())
    # requester2 sees S2 only: the merged CI's ID is a CI that exists nowhere.
    seen = await _get(world, a, merged["id"], a.requester2)
    none = await _get(world, a, nowhere, a.requester2)
    assert problem(seen) == problem(none) == (404, "cmdb_ci_not_found")
    assert survivor["id"] not in seen.text
    picked = await world.call(
        "GET", f"{BASE}/cis/picker", a, a.requester2, params={"search": merged["display_id"]}
    )
    assert picked.json()["items"] == []
    impact = await world.call(
        "GET", f"{BASE}/cis/{merged['id']}/impact", a, a.requester2, params={"depth": 1}
    )
    impact_none = await world.call(
        "GET", f"{BASE}/cis/{nowhere}/impact", a, a.requester2, params={"depth": 1}
    )
    assert problem(impact) == problem(impact_none)
    from app.modules.cmdb import ci_refs  # noqa: PLC0415 - the public port under test
    from app.modules.identity_access import subject_for  # noqa: PLC0415

    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        narrowed = await subject_for(session, a.tenant, a.requester2)
        refs = await ci_refs(session, narrowed, [uuid.UUID(merged["id"]), uuid.UUID(nowhere)])
        assert refs[uuid.UUID(merged["id"])].gone
        assert refs[uuid.UUID(nowhere)].gone
        assert refs[uuid.UUID(merged["id"])].name is None
        # Negative control: the admin's ref is the survivor's.
        admin = await subject_for(session, a.tenant, a.admin)
        found = (await ci_refs(session, admin, [uuid.UUID(merged["id"])]))[uuid.UUID(merged["id"])]
        assert str(found.id) == survivor["id"]
        assert found.name == "Hidden survivor"
    # Negative control: the admin is sent to the survivor.
    assert problem(await _get(world, a, merged["id"], a.admin)) == (404, "cmdb_ci_merged")


async def test_the_preview_never_shows_a_masked_field_and_it_stays_the_survivors(
    world: World,
) -> None:
    """Lane C (9): neither side's value, no choice for it, and the survivor keeps its own."""
    a = world.a
    cast = await _cast(world)
    secret = (await _field(world, a, f"Licence key {uuid.uuid4().hex[:4]}", None))["key"]
    for role_id in cast["roles"]:
        await field_rule(world, a, role_id, f"custom.{secret}", "masked")
    at_s2 = {"site_id": str(a.s2)}
    keep = await _made(world, a, "Masked keep", custom={secret: "KEEP-111"}, **at_s2)
    dupe = await _made(world, a, "Masked dupe", custom={secret: "DUPE-222"}, **at_s2)
    preview = await world.call(
        "GET", f"{BASE}/merges/preview", a, a.requester2,
        params={"first": keep["id"], "second": dupe["id"]},
    )  # fmt: skip
    assert preview.status_code == 200, preview.text
    assert f"custom.{secret}" not in {f["field"] for f in preview.json()["fields"]}
    assert "KEEP-111" not in preview.text
    assert "DUPE-222" not in preview.text
    refused = await _merge(
        world, a, keep, dupe, user=a.requester2, choices={f"custom.{secret}": "merged"}
    )
    assert refused.status_code == 422
    assert field_codes(refused)[f"choices.custom.{secret}"] == "unknown_field"
    assert (await _merge(world, a, keep, dupe, user=a.requester2)).status_code == 201
    kept = await _fresh(world, a, keep)
    assert kept["custom"][secret] == "KEEP-111"
    # Negative control: the admin, unmasked, is offered the field.
    other = await _made(world, a, "Masked other", custom={secret: "OTHER-333"})
    third = await _made(world, a, "Masked third")
    seen = await world.call(
        "GET", f"{BASE}/merges/preview", a, a.admin,
        params={"first": other["id"], "second": third["id"]},
    )  # fmt: skip
    assert f"custom.{secret}" in {f["field"] for f in seen.json()["fields"]}


async def test_a_restore_after_a_merge_warns_and_moves_nothing_back(world: World) -> None:
    """Lane C (10): 409 first; with the confirmation it comes back alone, the alias ended."""
    a = world.a
    service = await _made(world, a, "Restore service", "business_service")
    keep = await _made(world, a, "Restore keep", "application")
    dupe = await _made(world, a, "Restore dupe", "application")
    assert (await _link(world, a, dupe, "depends_on", [service])).status_code == 201
    dupe = await _fresh(world, a, dupe)
    assert (await _merge(world, a, keep, dupe)).status_code == 201
    binned = await world.call("GET", f"{BASE}/cis/trash", a, a.admin)
    version = next(c["version"] for c in binned.json()["items"] if c["id"] == dupe["id"])
    warned = await world.call(
        "POST", f"{BASE}/cis/{dupe['id']}/restore", a, a.admin, headers=_match(version)
    )
    assert problem(warned) == (409, "cmdb_ci_restore_merged")
    assert warned.json()["params"]["display_id"] == keep["display_id"]
    back = await world.call(
        "POST", f"{BASE}/cis/{dupe['id']}/restore", a, a.admin,
        params={"confirm_merged": "true"}, headers=_match(version),
    )  # fmt: skip
    assert back.status_code == 200, back.text
    # It opens itself again; the link stays with the survivor.
    assert (await _get(world, a, dupe["id"], a.admin)).status_code == 200
    held = await world.sql(
        "SELECT from_ci_id FROM cmdb_relationships WHERE tenant_id = $1 AND to_ci_id = $2"
        " AND deleted_at IS NULL",
        a.tenant,
        uuid.UUID(service["id"]),
    )
    assert [str(r["from_ci_id"]) for r in held] == [keep["id"]]


async def test_cis_of_two_types_are_never_merged(world: World) -> None:
    a = world.a
    app = await _made(world, a, "Type app", "application")
    db = await _made(world, a, "Type db", "database")
    assert problem(await _merge(world, a, app, db)) == (409, "cmdb_merge_types_differ")


# --- import (REQ-CMDB-018) ------------------------------------------------------------------------


async def _upload(
    world: World,
    org: Org,
    content: bytes,
    *,
    kind: str = "cis",
    mode: str = "add_update",
    match_on: str = "name",
    type_code: str | None = None,
    dry_run: bool = True,
    user: uuid.UUID | None = None,
    key: str | None = None,
) -> httpx.Response:
    params: dict[str, Any] = {
        "name": "cmdb.csv", "kind": kind, "mode": mode, "match_on": match_on,
        "dry_run": str(dry_run).lower(),
    }  # fmt: skip
    if type_code is not None:
        params["type_id"] = (await _types(world, org))[type_code]["id"]
    headers = {**_new(), "Content-Type": "application/octet-stream"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return await world.call(
        "POST", f"{BASE}/imports", org, user or org.admin, params=params, content=content,
        headers=headers,
    )  # fmt: skip


async def _worked(
    world: World, org: Org, started: httpx.Response, user: uuid.UUID | None = None
) -> dict[str, Any]:
    assert started.status_code == 201, started.text
    await imports.run_tenant(world.app.state.db, org.tenant)
    found = await world.call(
        "GET", f"{BASE}/imports/{started.json()['id']}", org, user or org.admin
    )
    assert found.status_code == 200, found.text
    return dict(found.json())


async def _count_named(world: World, org: Org, name: str) -> int:
    rows = await world.sql(
        "SELECT count(*) AS n FROM cmdb_cis WHERE tenant_id = $1 AND name = $2"
        " AND deleted_at IS NULL",
        org.tenant,
        name,
    )
    return int(rows[0]["n"])


async def test_a_dry_run_changes_nothing_then_the_run_adds_and_a_reimport_duplicates_nothing(
    world: World,
) -> None:
    """AC2, and a dry run first; progress goes to the importer's own channel."""
    a = world.a
    name = f"Imported server {uuid.uuid4().hex[:6]}"
    sheet = f"Name,Description,Criticality\n{name},From a file,high\n".encode()
    checked = await _worked(world, a, await _upload(world, a, sheet, type_code="server"))
    assert checked["status"] == "checked"
    assert (checked["created_count"], checked["failed_count"]) == (1, 0)
    assert await _count_named(world, a, name) == 0
    run = await world.call(
        "POST",
        f"{BASE}/imports/{checked['id']}/run",
        a,
        a.admin,
        headers=_match(checked["version"]),
    )
    assert run.status_code == 200, run.text
    await imports.run_tenant(world.app.state.db, a.tenant)
    assert await _count_named(world, a, name) == 1
    again = await _worked(
        world, a, await _upload(world, a, sheet, type_code="server", dry_run=False)
    )
    assert (again["created_count"], again["unchanged_count"]) == (0, 1)
    assert await _count_named(world, a, name) == 1  # no duplicate
    events = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1"
        " AND envelope->>'event_type' = 'cmdb.import.progressed'"
        " AND envelope->'payload'->>'import_id' = $2",
        a.tenant,
        checked["id"],
    )
    assert events[0]["n"] >= 3  # queued, running, checked, then the run's own


async def test_an_upload_with_the_same_idempotency_key_makes_one_import(world: World) -> None:
    a = world.a
    key = f"cmdb-import-{uuid.uuid4().hex}"
    first = await _upload(world, a, b"Name\nOnce\n", type_code="server", key=key)
    second = await _upload(world, a, b"Name\nOnce\n", type_code="server", key=key)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_a_relationship_row_naming_an_unseen_or_missing_ci_is_refused_alike(
    world: World,
) -> None:
    """AC1: reported, never half-imported; lane C (6), (7): unseen reads exactly as missing."""
    a = world.a
    await _cast(world)
    seen = await _made(
        world, a, f"Seen app {uuid.uuid4().hex[:4]}", "application", site_id=str(a.s2)
    )
    unseen = await _made(
        world, a, f"Unseen db {uuid.uuid4().hex[:4]}", "database", site_id=str(a.s1)
    )
    with_unseen = f"From,Relationship,To\n{seen['display_id']},depends_on,{unseen['display_id']}\n"
    with_none = f"From,Relationship,To\n{seen['display_id']},depends_on,CI-999999\n"
    answers = []
    for sheet in (with_unseen, with_none):
        job = await _worked(
            world, a,
            await _upload(world, a, sheet.encode(), kind="relationships", match_on="display_id",
                          user=a.requester2),
            user=a.requester2,
        )  # fmt: skip
        answers.append(
            (
                job["created_count"],
                job["updated_count"],
                job["unchanged_count"],
                job["failed_count"],
                [(p["row"], p["field"], p["code"]) for p in job["problems"]],
            )
        )
    assert answers[0] == answers[1] == (0, 0, 0, 1, [(2, "to", "not_found")])
    links_made = await world.sql(
        "SELECT count(*) AS n FROM cmdb_relationships WHERE tenant_id = $1 AND from_ci_id = $2",
        a.tenant,
        uuid.UUID(seen["id"]),
    )
    assert links_made[0]["n"] == 0
    # Negative control: the admin sees both, so the same row links them; a re-import adds no twin.
    for expected in ((1, 0), (0, 1)):
        job = await _worked(
            world, a,
            await _upload(world, a, with_unseen.encode(), kind="relationships",
                          match_on="display_id", dry_run=False),
        )  # fmt: skip
        assert (job["created_count"], job["unchanged_count"]) == expected


async def test_a_ci_row_naming_an_unseen_ci_reads_as_one_that_exists_nowhere(world: World) -> None:
    """Lane C (6), (7): update by display ID is not_found; an add naming one is row_conflict."""
    a = world.a
    await _cast(world)
    unseen = await _made(world, a, f"Out of sight {uuid.uuid4().hex[:4]}", site_id=str(a.s1))
    for mode, code in (("update", "not_found"), ("add", "row_conflict")):
        jobs = []
        for display_id in (unseen["display_id"], "CI-999998"):
            sheet = f"Display ID,Name\n{display_id},Renamed\n".encode()
            job = await _worked(
                world, a,
                await _upload(world, a, sheet, mode=mode, match_on="display_id",
                              type_code="server", user=a.requester2),
                user=a.requester2,
            )  # fmt: skip
            jobs.append(
                (
                    job["created_count"],
                    job["updated_count"],
                    job["failed_count"],
                    [(p["field"], p["code"]) for p in job["problems"]],
                )
            )
        assert jobs[0] == jobs[1] == (0, 0, 1, [("display_id", code)]), mode
    assert (await _fresh(world, a, unseen))["name"] == unseen["name"]
    # Negative control: the admin updates it by the same row.
    sheet = f"Display ID,Name\n{unseen['display_id']},Renamed by admin\n".encode()
    job = await _worked(
        world, a,
        await _upload(world, a, sheet, mode="update", match_on="display_id", type_code="server",
                      dry_run=False),
    )  # fmt: skip
    assert job["updated_count"] == 1


async def test_a_file_over_d092s_limits_is_refused_whole(world: World) -> None:
    """The coordinator's (4): columns over the cap end the import; nothing is read."""
    a = world.a
    wide = (",".join(f"c{n}" for n in range(60)) + "\n" + ",".join("x" * 60) + "\n").encode()
    job = await _worked(world, a, await _upload(world, a, wide, type_code="server"))
    assert (job["status"], job["failure"]) == ("failed", "cmdb_import_too_many_columns")
    server = (await _types(world, a))["server"]["id"]
    not_xlsx = await world.call(
        "POST", f"{BASE}/imports", a, a.admin,
        params={"name": "cmdb.xlsx", "kind": "cis", "type_id": server},
        content=b"not a zip", headers={**_new(), "Content-Type": "application/octet-stream"},
    )  # fmt: skip
    assert problem(not_xlsx) == (422, "cmdb_import_file_not_readable")


async def test_the_refused_rows_download_is_formula_safe_and_never_holds_a_value(
    world: World,
) -> None:
    """The coordinator's (4): codes in words; no cell opens as a formula; no value from the file."""
    a = world.a
    sheet = b'Name,State\n=HYPERLINK("x"),no_such_state\n'
    job = await _worked(world, a, await _upload(world, a, sheet, type_code="server"))
    assert job["failed_count"] == 1
    csv_file = await world.call(
        "GET", f"{BASE}/imports/{job['id']}/problems", a, a.admin, params={"language": "en"}
    )
    assert csv_file.status_code == 200
    assert csv_file.headers["content-type"].startswith("text/csv")
    body = csv_file.text.lstrip("﻿")
    assert "HYPERLINK" not in body
    assert "no_such_state" not in body
    for line in body.splitlines():
        for cell in line.split(","):
            assert cell[:1] not in {"=", "+", "-", "@", "\t", "\r"}, cell


async def test_only_the_importer_reads_an_import(world: World) -> None:
    a = world.a
    started = await _upload(world, a, b"Name\nMine\n", type_code="server")
    other = await world.call("GET", f"{BASE}/imports/{started.json()['id']}", a, a.lead)
    assert other.status_code in {403, 404}
    assert "Mine" not in other.text


async def test_an_import_needs_the_rights_for_its_mode(world: World) -> None:
    a = world.a
    # tech_a (a built-in technician) may view CIs but not add them.
    refused = await _upload(
        world, a, b"Name\nNope\n", mode="add", type_code="server", user=a.tech_a
    )
    assert refused.status_code == 403


async def test_relationship_types_are_named_by_their_code(world: World) -> None:
    a = world.a
    types = await _rel_types(world, a)
    assert "depends_on" in types
    app = await _made(world, a, f"Code app {uuid.uuid4().hex[:4]}", "application")
    db = await _made(world, a, f"Code db {uuid.uuid4().hex[:4]}", "database")
    sheet = f"From,Relationship,To\n{app['display_id']},no_such_type,{db['display_id']}\n".encode()
    job = await _worked(
        world, a, await _upload(world, a, sheet, kind="relationships", match_on="display_id")
    )
    assert [(p["field"], p["code"]) for p in job["problems"]] == [
        ("relationship", "cmdb_import_relationship_type_unknown")
    ]
