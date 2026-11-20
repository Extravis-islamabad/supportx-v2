"""Fine-grained access at the remaining choke points (ADR-053; lane C 1-5; the coordinator).

- One write per verb on a CI outside the set: update, delete, restore, copy, and a relationship
  to an unseen target, each 404.
- The picker (search) and the home counts never show or count an unseen record.
- The asset report source's rows and an aggregate count leave unseen assets out.
- A queued bulk job uses the person's rules as they are when it runs, and names no unseen asset.
- Realtime: a CI moving out of a reader's set sends no new values, and their refetch is 404.
- Erasure holdings: the true totals stay, plus how many the eraser can't see; counts only.
- Writes are checked like reads: a create or a move that puts the record outside the person's
  set is 403 out_of_scope, for assets and CIs (create, site move, change of type).
- One's own holdings (/assets/mine) stay listed; the record and the picker stay narrowed.
- The loan register, bookings and an audit's items name no unseen asset; a loan's status still
  counts every line (open while only an unseen line is out). Availability is the shared pool
  (D-179) and names no asset.

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h).
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.tenancy import TenantContext
from app.modules.assets.service.bulk_jobs import run_asset_bulk_jobs
from app.modules.cmdb.service.realtime import ROUTES
from app.modules.identity_access.service.person_data import person_holdings
from app.shared.events import EventEnvelope
from app.shared.reporting import ports as reporting
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_asset_audits_api import _hold, _mine, _plan, _start
from tests.db.test_asset_bookings_api import _book, _day
from tests.db.test_asset_bulk_merge_import_api import _bulk, _run
from tests.db.test_asset_loans_api import _loan, _loanable
from tests.db.test_assets_api import _add as add_asset
from tests.db.test_assets_api import _product
from tests.db.test_cmdb_api import _types
from tests.db.test_incidents_api import World, problem
from tests.db.test_knowledge_api import _match, _new
from tests.db.test_resource_access import _edition, _holding, _made, _rule

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

CI_RIGHTS = [
    ("cmdb.view", "all"),
    ("cmdb.add", "all"),
    ("cmdb.edit", "all"),
    ("cmdb.delete", "all"),
]


async def test_every_write_on_an_unseen_ci_is_404(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    seen = await _made(world, a, "Writable server", "server")
    hidden = await _made(world, a, "Hidden database", "database")
    binned = await _made(world, a, "Binned database", "database")
    removed = await world.call(
        "DELETE", f"/cmdb/cis/{binned['id']}", a, a.admin, headers=_match(binned["version"])
    )
    assert removed.status_code == 204, removed.text
    rels = (await world.call("GET", "/cmdb/relationship-types", a, a.admin)).json()["items"]
    depends = next(t for t in rels if t["code"] == "depends_on")
    async with _holding(world, a, a.requester, CI_RIGHTS) as narrowed:
        made = await _rule(world, a, narrowed, "ci", {"type_ids": [types["server"]["id"]]})
        assert made.status_code == 201, made.text
        me = a.requester
        tries = {
            "update": await world.call(
                "PATCH", f"/cmdb/cis/{hidden['id']}", a, me, json={"name": "x"},
                headers=_match(hidden["version"]),
            ),
            "delete": await world.call(
                "DELETE", f"/cmdb/cis/{hidden['id']}", a, me, headers=_match(hidden["version"])
            ),
            "restore": await world.call(
                "POST", f"/cmdb/cis/{binned['id']}/restore", a, me,
                headers=_match(binned["version"] + 1),  # the removal's version: 404, not 428
            ),
            "copy": await world.call("POST", f"/cmdb/cis/{hidden['id']}/copy", a, me),
            "link": await world.call(
                "POST", f"/cmdb/cis/{seen['id']}/relationships", a, me,
                json={"type_id": depends["id"], "direction": "forward", "targets": [hidden["id"]]},
            ),
        }  # fmt: skip
        for verb, answer in tries.items():
            assert answer.status_code == 404, (verb, answer.text)
            # The problem names nothing of the record (`instance` echoes the caller's own URL).
            shown = {k: v for k, v in answer.json().items() if k != "instance"}
            assert hidden["id"] not in json.dumps(shown), verb


async def test_the_picker_and_the_home_counts_leave_unseen_records_out(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    tag = uuid.uuid4().hex[:6]
    await _made(world, a, f"Pick server {tag}", "server")
    await _made(world, a, f"Pick database {tag}", "database")
    product = await _product(world, a, "laptop", f"Count laptop {tag}")
    near = await add_asset(
        world, a, {"name": "Near laptop", "product_id": product, "site_id": str(a.s1)}
    )
    far = await add_asset(
        world, a, {"name": "Far laptop", "product_id": product, "site_id": str(a.s2)}
    )
    assert near.status_code == 201, near.text
    assert far.status_code == 201, far.text
    grants = [("cmdb.view", "all"), ("assets.view", "all")]
    async with _holding(world, a, a.requester, grants) as narrowed:
        for resource, criteria in (
            ("ci", {"type_ids": [types["server"]["id"]]}),
            ("asset", {"site_ids": [str(a.s1)]}),
        ):
            assert (await _rule(world, a, narrowed, resource, criteria)).status_code == 201
        picked = await world.call("GET", "/cmdb/cis/picker", a, a.requester, params={"search": tag})
        assert picked.status_code == 200, picked.text
        assert f"Pick server {tag}" in picked.text
        assert f"Pick database {tag}" not in picked.text
        counts = (await world.call("GET", "/assets/type-counts", a, a.requester)).json()
        everyone = (await world.call("GET", "/assets/type-counts", a, a.admin)).json()
        assert json.dumps(counts) != json.dumps(everyone)  # the far laptop isn't counted
        assert far.json()["id"] not in json.dumps(counts)


async def test_the_report_source_rows_and_counts_leave_unseen_assets_out(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    product = await _product(world, a, "laptop", f"Report laptop {uuid.uuid4().hex[:6]}")
    near = (
        await add_asset(world, a, {"name": "Rep near", "product_id": product, "site_id": str(a.s1)})
    ).json()
    far = (
        await add_asset(world, a, {"name": "Rep far", "product_id": product, "site_id": str(a.s2)})
    ).json()
    async with _holding(world, a, a.requester, [("assets.view", "all")]) as narrowed:
        made = await _rule(world, a, narrowed, "asset", {"site_ids": [str(a.s1)]})
        assert made.status_code == 201, made.text
        subject = await world.app.state.policy.subject(a.tenant, a.requester)
        provider = reporting._PROVIDERS["asset"]  # noqa: SLF001 - the registered source
        async with world.app.state.db.tenant_session(
            TenantContext(a.tenant, a.requester)
        ) as session:
            source = await provider.source(session, subject)
            rows = source.rows.subquery()
            ids = set((await session.scalars(select(rows.c.id))).all())
            total = await session.scalar(select(func.count()).select_from(rows))
        assert uuid.UUID(near["id"]) in ids
        assert uuid.UUID(far["id"]) not in ids
        assert total == len(ids)


async def test_a_queued_bulk_job_uses_the_rules_when_it_runs(world: World) -> None:
    """Lane C 3: queued before the rule, run after it; the unseen asset is skipped, unnamed."""
    a = world.a
    await _edition(world, a, "enterprise")
    product = await _product(world, a, "laptop", f"Bulk rule laptop {uuid.uuid4().hex[:6]}")
    near = (
        await add_asset(
            world,
            a,
            {
                "name": "Bulk near",
                "product_id": product,
                "site_id": str(a.s1),
                "tag": f"BN-{uuid.uuid4().hex[:5]}",
            },
        )
    ).json()
    far = (
        await add_asset(
            world,
            a,
            {
                "name": "Bulk far",
                "product_id": product,
                "site_id": str(a.s2),
                "tag": f"BF-{uuid.uuid4().hex[:5]}",
            },
        )
    ).json()
    grants = [("assets.view", "all"), ("assets.manage", "all")]
    async with _holding(world, a, a.requester, grants) as narrowed:
        body = {
            "action": "edit",
            "asset_ids": [near["id"], far["id"]],
            "changes": {"description": "Bulk-edited"},
        }
        started = await _bulk(world, a, a.requester, body)
        assert started.status_code == 202, started.text
        made = await _rule(world, a, narrowed, "asset", {"site_ids": [str(a.s1)]})
        assert made.status_code == 201, made.text
        await _run(world, run_asset_bulk_jobs)
        job = (
            await world.call("GET", f"/assets/bulk-jobs/{started.json()['id']}", a, a.requester)
        ).json()
        assert far["tag"] not in json.dumps(job)  # the job never names the unseen asset
        rows = await world.sql(
            "SELECT id, description FROM assets WHERE tenant_id = $1 AND id = ANY($2::uuid[])",
            a.tenant,
            [uuid.UUID(near["id"]), uuid.UUID(far["id"])],
        )
        described = {str(r["id"]): r["description"] for r in rows}
        assert described[near["id"]] == "Bulk-edited"
        assert described[far["id"]] != "Bulk-edited"


async def test_a_ci_moving_out_of_a_readers_set_sends_no_values(world: World) -> None:
    """Lane C 5: the update's messages carry IDs and field names only; the refetch is 404."""
    a = world.a
    await _edition(world, a, "enterprise")
    ci = await _made(world, a, "Moving server", "server", site_id=str(a.s1))
    async with _holding(world, a, a.requester, [("cmdb.view", "all")]) as narrowed:
        made = await _rule(world, a, narrowed, "ci", {"site_ids": [str(a.s1)]})
        assert made.status_code == 201, made.text
        assert (await world.call("GET", f"/cmdb/cis/{ci['id']}", a, a.requester)).status_code == 200
        moved = await world.call(
            "PATCH", f"/cmdb/cis/{ci['id']}", a, a.admin,
            json={"site_id": str(a.s2), "description": "Secret new text"},
            headers=_match(ci["version"]),
        )  # fmt: skip
        assert moved.status_code == 200, moved.text
        rows = await world.sql(
            "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
            " AND event_type = 'cmdb.ci.updated' AND aggregate_id = $2 ORDER BY id DESC LIMIT 1",
            a.tenant,
            ci["id"],
        )
        envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            for spec in ROUTES:
                if envelope.event_type in spec.event_types:
                    effects = await spec.route(envelope, session)
                    sent = repr(effects.publications)
                    assert "Secret new text" not in sent
                    # Payloads carry IDs and changed field NAMES only (rule c): never the new site.
                    # A site channel's name may hold its own ID; only that site's people subscribe.
                    for publication in effects.publications:
                        assert str(a.s2) not in repr((publication.ids, publication.fields))
        refetch = await world.call("GET", f"/cmdb/cis/{ci['id']}", a, a.requester)
        assert problem(refetch) == (404, "cmdb_ci_not_found")


async def test_erasure_holdings_keep_true_totals_and_count_what_the_eraser_cant_see(
    world: World,
) -> None:
    """The coordinator 2026-11-20: totals stay true; `*_outside_view` counts; never an ID."""
    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    person = a.tech_b
    owned_seen = await _made(world, a, "Erased owner's server", "server", owner_user_id=str(person))
    owned_hidden = await _made(world, a, "Erased owner's db", "database", owner_user_id=str(person))
    product = await _product(world, a, "laptop", f"Held laptop {uuid.uuid4().hex[:6]}")
    held: list[dict[str, Any]] = []
    for name, site in (("Held near", a.s1), ("Held far", a.s2)):
        asset = (
            await add_asset(world, a, {"name": name, "product_id": product, "site_id": str(site)})
        ).json()
        given = await world.call(
            "PUT", f"/assets/{asset['id']}/holder", a, a.admin,
            json={"kind": "user", "id": str(person)}, headers=_match(asset["version"]),
        )  # fmt: skip
        assert given.status_code == 200, given.text
        held.append(asset)
    grants = [("cmdb.view", "all"), ("assets.view", "all")]
    async with _holding(world, a, a.requester, grants) as narrowed:
        for resource, criteria in (
            ("ci", {"type_ids": [types["server"]["id"]]}),
            ("asset", {"site_ids": [str(a.s1)]}),
        ):
            assert (await _rule(world, a, narrowed, resource, criteria)).status_code == 201
        eraser = await world.app.state.policy.subject(a.tenant, a.requester)
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            plain = await person_holdings(session, person)
            counted = await person_holdings(session, person, eraser)
        assert counted["cmdb_cis_owned"] == plain["cmdb_cis_owned"] >= 2  # the true total
        assert counted["cmdb_cis_owned_outside_view"] >= 1
        assert counted["assets_held"] == plain["assets_held"] >= 2
        assert counted["assets_held_outside_view"] >= 1
        assert "cmdb_cis_owned_outside_view" not in plain  # only with an eraser
        flat = json.dumps(counted)
        for record in (owned_seen, owned_hidden, *held):
            assert record["id"] not in flat
            assert record["name"] not in flat


async def test_record_references_never_name_an_unseen_ci_or_asset(world: World) -> None:
    """The path other modules' mentions and links read records through (`ci_refs`,
    `asset_refs`): an unseen CI or asset is hidden, never named."""
    from app.modules.assets import asset_refs  # noqa: PLC0415 - the public interface under test
    from app.modules.cmdb import ci_refs  # noqa: PLC0415

    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    seen_ci = await _made(world, a, "Ref server", "server")
    hidden_ci = await _made(world, a, "Ref database", "database")
    product = await _product(world, a, "laptop", f"Ref laptop {uuid.uuid4().hex[:6]}")
    near = (
        await add_asset(world, a, {"name": "Ref near", "product_id": product, "site_id": str(a.s1)})
    ).json()
    far = (
        await add_asset(world, a, {"name": "Ref far", "product_id": product, "site_id": str(a.s2)})
    ).json()
    grants = [("cmdb.view", "all"), ("assets.view", "all")]
    async with _holding(world, a, a.requester, grants) as narrowed:
        for resource, criteria in (
            ("ci", {"type_ids": [types["server"]["id"]]}),
            ("asset", {"site_ids": [str(a.s1)]}),
        ):
            assert (await _rule(world, a, narrowed, resource, criteria)).status_code == 201
        subject = await world.app.state.policy.subject(a.tenant, a.requester)
        async with world.app.state.db.tenant_session(
            TenantContext(a.tenant, a.requester)
        ) as session:
            cis = await ci_refs(
                session, subject, [uuid.UUID(seen_ci["id"]), uuid.UUID(hidden_ci["id"])]
            )
            assets = await asset_refs(
                session, subject, [uuid.UUID(near["id"]), uuid.UUID(far["id"])]
            )
        assert cis[uuid.UUID(seen_ci["id"])].name == "Ref server"
        assert "Ref database" not in repr(cis)
        assert assets[uuid.UUID(far["id"])].hidden is True
        assert assets[uuid.UUID(far["id"])].name is None
        assert assets[uuid.UUID(near["id"])].name == "Ref near"


async def test_an_import_never_reaches_an_asset_outside_the_importers_set(world: World) -> None:
    """A new row at an unseen site is refused; an update matching an unseen asset is refused;
    the job names neither; the unseen asset is untouched."""
    from app.modules.assets.service.imports import run_asset_imports  # noqa: PLC0415
    from tests.db.test_asset_bulk_merge_import_api import _import  # noqa: PLC0415

    a = world.a
    await _edition(world, a, "enterprise")
    tag = uuid.uuid4().hex[:6]
    product_name = f"Import rule laptop {tag}"
    types = (await world.call("GET", "/assets/product-types", a, a.admin)).json()
    laptop = next(t["id"] for t in types if t["api_name"] == "laptop")
    made = await world.call(
        "POST", "/assets/products", a, a.admin,
        json={"product_type_id": laptop, "name": product_name}, headers=_new(),
    )  # fmt: skip
    assert made.status_code == 201, made.text
    unseen = (
        await add_asset(
            world, a,
            {"name": f"Unseen {tag}", "product_id": made.json()["id"], "site_id": str(a.s2),
             "serial_number": f"UNSEEN-{tag}"},
        )
    ).json()  # fmt: skip
    sites = {
        s["id"]: s["name"]
        for s in (await world.call("GET", "/organization/sites", a, a.admin)).json()
    }
    grants = [("assets.view", "all"), ("assets.manage", "all")]
    async with _holding(world, a, a.requester, grants) as narrowed:
        rule = await _rule(world, a, narrowed, "asset", {"site_ids": [str(a.s1)]})
        assert rule.status_code == 201, rule.text
        csv = (
            "Name,Product,Serial number,Location,Site\n"
            f"Far new,{product_name},FAR-{tag},,{sites[str(a.s2)]}\n"
            f"Taken over,{product_name},UNSEEN-{tag},Moved,{sites[str(a.s1)]}\n"
            f"Near new,{product_name},NEAR-{tag},,{sites[str(a.s1)]}\n"
        ).encode()
        started = await _import(world, a, csv, user=a.requester)
        assert started.status_code == 201, started.text
        await _run(world, run_asset_imports)
        # An import job is its starter's own: read it as them.
        found = await world.call("GET", f"/assets/imports/{started.json()['id']}", a, a.requester)
        assert found.status_code == 200, found.text
        checked = dict(found.json())
        problems = {p["row"] for p in checked["problems"]}
        assert {2, 3} <= problems  # the unseen site and the unseen match: refused
        assert 4 not in problems
        flat = json.dumps(checked)
        assert unseen["id"] not in flat
        assert f"Unseen {tag}" not in flat
        after = await world.sql(
            "SELECT name, location, site_id FROM assets WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            uuid.UUID(unseen["id"]),
        )
        assert (after[0]["name"], after[0]["location"], after[0]["site_id"]) == (
            f"Unseen {tag}",
            unseen["location"],
            a.s2,
        )


async def test_the_erased_holder_notice_names_only_what_every_recipient_may_see(
    world: World,
) -> None:
    """One message to the asset managers names only assets all of them may see (ADR-053)."""
    from app.modules.assets.service.notifications import SOURCE  # noqa: PLC0415

    a = world.a
    await _edition(world, a, "enterprise")
    product = await _product(world, a, "laptop", f"Notice laptop {uuid.uuid4().hex[:6]}")
    tag = uuid.uuid4().hex[:5]
    near = (
        await add_asset(
            world,
            a,
            {
                "name": "Notice near",
                "product_id": product,
                "site_id": str(a.s1),
                "tag": f"NN-{tag}",
            },
        )
    ).json()
    far = (
        await add_asset(
            world,
            a,
            {"name": "Notice far", "product_id": product, "site_id": str(a.s2), "tag": f"NF-{tag}"},
        )
    ).json()
    grants = [("assets.view", "all"), ("assets.manage", "all")]
    async with _holding(world, a, a.requester, grants) as narrowed:
        rule = await _rule(world, a, narrowed, "asset", {"site_ids": [str(a.s1)]})
        assert rule.status_code == 201, rule.text
        payload = {
            "person_id": str(a.tech_b),
            "asset_ids": [near["id"], far["id"]],
            "assets_held": 2,
        }
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            context = await SOURCE._held_context(  # noqa: SLF001 - the context under test
                session, "asset.erased_holder_items", payload
            )
        assert context is not None
        recipients = context.relatives["asset_managers"]
        assert a.requester in recipients  # the narrowed manager sees one of them
        sent = repr(context.variables)
        assert f"NN-{tag}" in sent
        assert f"NF-{tag}" not in sent  # not every recipient may see it: never named
        assert context.variables["holdings.count"] == 2  # the true count


def _outside(answer: Any) -> None:  # noqa: ANN401 - httpx response
    """The refusal of a write that would leave the record outside the person's set."""
    assert answer.status_code == 403, answer.text
    assert answer.json()["params"]["reason"] == "out_of_scope", answer.text


async def test_a_write_that_puts_a_record_outside_the_set_is_refused(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    server, database = types["server"]["id"], types["database"]["id"]
    product = await _product(world, a, "laptop", f"Write laptop {uuid.uuid4().hex[:6]}")
    rights = [*CI_RIGHTS, ("assets.view", "all"), ("assets.manage", "all")]
    async with _holding(world, a, a.requester, rights) as narrowed:
        for resource, criteria in (
            ("ci", {"type_ids": [server], "site_ids": [str(a.s1)]}),
            ("asset", {"site_ids": [str(a.s1)]}),
        ):
            assert (await _rule(world, a, narrowed, resource, criteria)).status_code == 201
        me = a.requester

        async def ci(type_id: str, site: uuid.UUID) -> Any:  # noqa: ANN401 - httpx response
            return await world.call(
                "POST", "/cmdb/cis", a, me, headers=_new(),
                json={"type_id": type_id, "name": f"W {uuid.uuid4().hex[:6]}",
                      "site_id": str(site)},
            )  # fmt: skip

        inside = await ci(server, a.s1)
        assert inside.status_code == 201, inside.text
        _outside(await ci(database, a.s1))  # a type the rule leaves out
        _outside(await ci(server, a.s2))  # a site the rule leaves out
        record = inside.json()
        _outside(
            await world.call(
                "PATCH", f"/cmdb/cis/{record['id']}", a, me, json={"site_id": str(a.s2)},
                headers=_match(record["version"]),
            )
        )  # fmt: skip
        _outside(
            await world.call(
                "POST", f"/cmdb/cis/{record['id']}/change-type", a, me,
                json={"type_id": database, "confirm_dropped_fields": True},
                headers=_match(record["version"]),
            )
        )  # fmt: skip
        copied = await world.call("POST", f"/cmdb/cis/{record['id']}/copy", a, me, headers=_new())
        assert copied.status_code == 201, copied.text  # the copy stays inside the set
        kept = (await world.call("GET", f"/cmdb/cis/{record['id']}", a, a.admin)).json()
        assert (kept["site_id"], kept["type_id"]) == (str(a.s1), server)  # nothing was saved

        near = await add_asset(
            world, a, {"name": "W near", "product_id": product, "site_id": str(a.s1)}, me
        )
        assert near.status_code == 201, near.text
        _outside(
            await add_asset(
                world, a, {"name": "W far", "product_id": product, "site_id": str(a.s2)}, me
            )
        )
        asset = near.json()
        _outside(
            await world.call(
                "PATCH", f"/assets/{asset['id']}", a, me, json={"site_id": str(a.s2)},
                headers=_match(asset["version"]),
            )
        )  # fmt: skip
        stayed = (await world.call("GET", f"/assets/{asset['id']}", a, a.admin)).json()
        assert stayed["site_id"] == str(a.s1)


async def test_my_own_holdings_stay_listed_but_the_record_stays_narrowed(world: World) -> None:
    """/assets/mine is the person's own holdings (EXEMPT in the route walk): it still lists an
    asset outside their set, while the record, and the picker, keep it hidden."""
    a = world.a
    await _edition(world, a, "enterprise")
    product = await _product(world, a, "laptop", f"Held laptop {uuid.uuid4().hex[:6]}")
    far = (
        await add_asset(world, a, {"name": "Held far", "product_id": product, "site_id": str(a.s2)})
    ).json()
    await _hold(world, a, far, a.requester)
    async with _holding(world, a, a.requester, [("assets.view", "all")]) as narrowed:
        assert (
            await _rule(world, a, narrowed, "asset", {"site_ids": [str(a.s1)]})
        ).status_code == 201
        assert far["id"] in json.dumps(await _mine(world, a, a.requester))
        opened = await world.call("GET", f"/assets/{far['id']}", a, a.requester)
        assert opened.status_code == 404, opened.text
        picked = await world.call("GET", "/assets/picker", a, a.requester)
        assert picked.status_code == 200, picked.text
        assert far["id"] not in picked.text


async def test_registers_name_no_unseen_asset(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    product = await _product(world, a, "laptop", f"Register laptop {uuid.uuid4().hex[:6]}")

    async def asset(name: str, site: uuid.UUID) -> dict[str, Any]:
        made = await add_asset(
            world, a, {"name": name, "product_id": product, "site_id": str(site)}
        )
        assert made.status_code == 201, made.text
        return dict(made.json())

    near, far, far_alone = (
        await asset("Reg near", a.s1),
        await asset("Reg far", a.s2),
        await asset("Reg far alone", a.s2),
    )
    near_booked, far_booked = await asset("Book near", a.s1), await asset("Book far", a.s2)
    await _loanable(world, near, far, far_alone, near_booked, far_booked)
    both = await _loan(world, [near, far], a.tech_a)
    alone = await _loan(world, [far_alone], a.tech_a)
    assert both.status_code == 201, both.text
    assert alone.status_code == 201, alone.text
    for item in (near_booked, far_booked):
        booked = await _book(world, item, _day(30), _day(31))
        assert booked.status_code == 201, booked.text
    audit = await _start(world, a, await _plan(world, a, site_ids=[str(a.s1), str(a.s2)]))
    rights = [("assets.view", "all"), ("assets.manage", "all")]
    async with _holding(world, a, a.requester, rights) as narrowed:
        assert (
            await _rule(world, a, narrowed, "asset", {"site_ids": [str(a.s1)]})
        ).status_code == 201
        me = a.requester
        register = await world.call("GET", "/assets/loans", a, me)
        assert register.status_code == 200, register.text
        loans = {row["id"]: row for row in register.json()}
        assert alone.json()["id"] not in loans  # a loan of unseen assets only: not listed
        shown = loans[both.json()["id"]]
        assert [x["id"] for x in shown["assets"]] == [near["id"]]
        assert far["id"] not in json.dumps(shown)
        assert shown["status"] == both.json()["status"]  # the status still counts every line
        back = await world.call(
            "POST", f"/assets/loans/{both.json()['id']}/returns", a, a.admin,
            json={"asset_ids": [near["id"]]},
        )  # fmt: skip
        assert back.status_code == 200, back.text
        again = await world.call("GET", "/assets/loans", a, me)
        shown = {row["id"]: row for row in again.json()}[both.json()["id"]]
        # Only an unseen line is still out: the loan stays open, never "closed" to this reader.
        assert (shown["status"], shown["outstanding"]) == ("open", []), shown
        for item, count in ((near_booked, 1), (far_booked, 0)):
            found = await world.call(
                "GET", "/assets/bookings", a, me, params={"asset_id": item["id"]}
            )
            assert found.status_code == 200, found.text
            assert len(found.json()) == count, item["name"]
        free = await world.call(
            "GET", "/assets/availability", a, me, params={"product_id": product}
        )
        assert free.status_code == 200, free.text
        # The shared pool (D-179): no asset is named, seen or not, so no rule narrows it.
        assert near_booked["id"] not in free.text
        assert far_booked["id"] not in free.text
        assert {"product_id", "product_name", "site_name", "busy"} >= set(free.json()[0])
        items = await world.call("GET", f"/assets/audits/{audit['id']}/items", a, me)
        assert items.status_code == 200, items.text
        assert near["id"] in items.text
        assert far["id"] not in items.text
