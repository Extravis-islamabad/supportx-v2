"""Catalog administration (WP-031 s1, plan D1..D13). Real PostgreSQL with RLS.

The category tree, the item life (draft, published, retired, planned, copy, delete), what
requesters see, the form's audiences, search in three languages with its 500 ms budget, the
tenant settings, "report a problem" entries and the starter catalog (D-138). Every new table
and column is tenant-isolated.
"""

import json
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from sqlalchemy import func, select

from app.core.tenancy import TenantContext
from app.modules.service_catalog.domain.starter import CATEGORIES, ITEMS
from app.modules.service_catalog.infra.models import CatalogItem, ServiceCategory
from app.modules.service_catalog.service.schedule import apply_due
from app.modules.service_catalog.service.search import TEXT
from app.modules.service_catalog.service.starter import (
    on_tenant_provisioned,
    seed_empty_catalog,
    seed_new_tenant,
)
from app.shared.clock import FrozenClock
from app.shared.search import ENGINE
from tests.db.test_catalog_api import CATEGORIES as CATEGORIES_PATH
from tests.db.test_catalog_api import ITEMS as ITEMS_PATH
from tests.db.test_catalog_api import add, category
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, world
from tests.db.test_service_requests_api import raise_request
from tooling import timing

__all__ = ["world"]  # the fixture, re-used


def codes(response: Any) -> dict[str, str]:  # noqa: ANN401 - an httpx response
    assert response.status_code == 422, response.text
    return {e["field"].removeprefix("body."): e["code"] for e in response.json()["errors"]}


async def patch(
    world: World,
    org: Org,
    user: uuid.UUID,
    path: str,
    version: int,
    **body: Any,  # noqa: ANN401
) -> Any:  # noqa: ANN401 - JSON
    return await world.call(
        "PATCH", path, org, user, json=body, headers={"If-Match": f'"{version}"', **CONSOLE}
    )


async def seen_by(world: World, org: Org, user: uuid.UUID, **params: Any) -> set[str]:  # noqa: ANN401
    response = await world.call("GET", ITEMS_PATH, org, user, params=params)
    assert response.status_code == 200, response.text
    return {i["id"] for i in response.json()}


# --- categories -----------------------------------------------------------------------------------


async def test_categories_form_a_tree_and_a_disabled_one_hides_its_items(world: World) -> None:
    a = world.a
    root = await category(world, a)
    child = await category(world, a, parent_id=root, names={"en": "Laptops"})
    deeper = await category(world, a, parent_id=child, names={"en": "Gaming"})
    deepest = await category(world, a, parent_id=deeper, names={"en": "Big"})
    too_deep = await world.call(
        "POST",
        CATEGORIES_PATH,
        a,
        a.admin,
        json={"names": {"en": "Fifth"}, "parent_id": deepest},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert codes(too_deep) == {"parent_id": "catalog_too_deep"}
    listed = {c["id"]: c for c in (await world.call("GET", CATEGORIES_PATH, a, a.admin)).json()}
    loop = await patch(
        world, a, a.admin, f"{CATEGORIES_PATH}/{root}", listed[root]["version"], parent_id=deeper
    )
    assert codes(loop) == {"parent_id": "category_loop"}
    item = (await add(world, a, a.admin, category_id=deeper)).json()
    assert item["id"] in await seen_by(world, a, a.requester)
    off = await patch(
        world, a, a.admin, f"{CATEGORIES_PATH}/{child}", listed[child]["version"], enabled=False
    )
    assert off.status_code == 200, off.text
    assert item["id"] not in await seen_by(world, a, a.requester)  # below a disabled category
    assert item["id"] in await seen_by(world, a, a.tech_a)  # staff still see it
    browsable = {c["id"] for c in (await world.call("GET", CATEGORIES_PATH, a, a.requester)).json()}
    assert root in browsable
    assert {child, deeper, deepest}.isdisjoint(browsable)


async def test_a_category_in_use_is_not_deleted(world: World) -> None:
    a, b = world.a, world.b
    holder = await category(world, a)
    await category(world, a, parent_id=holder, names={"en": "Child"})
    await add(world, a, a.admin, category_id=holder)
    refused = await world.call(
        "DELETE", f"{CATEGORIES_PATH}/{holder}", a, a.admin, headers={"If-Match": '"1"', **CONSOLE}
    )
    assert problem(refused) == (409, "service_category_in_use")
    assert refused.json()["params"] == {"items": 1, "categories": 1}
    empty = await category(world, a, names={"en": "Empty"})
    foreign = await world.call(
        "DELETE", f"{CATEGORIES_PATH}/{empty}", b, b.admin, headers={"If-Match": '"1"', **CONSOLE}
    )
    assert problem(foreign) == (404, "service_category_not_found")  # RLS
    gone = await world.call(
        "DELETE", f"{CATEGORIES_PATH}/{empty}", a, a.admin, headers={"If-Match": '"1"', **CONSOLE}
    )
    assert gone.status_code == 204, gone.text
    names = {c["id"] for c in (await world.call("GET", CATEGORIES_PATH, a, a.admin)).json()}
    assert empty not in names


# --- the item's life ------------------------------------------------------------------------------


async def test_an_item_is_drafted_published_retired_and_published_again(world: World) -> None:
    a = world.a
    draft = await world.call(
        "POST",
        ITEMS_PATH,
        a,
        a.admin,
        json={"names": {"en": "Monitor"}},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert draft.status_code == 201, draft.text
    item = draft.json()
    assert (item["status"], item["enabled"]) == ("draft", False)
    assert {"field": "names", "language": "ar"} in item["missing_translations"]
    path = f"{ITEMS_PATH}/{item['id']}"
    assert item["id"] not in await seen_by(world, a, a.requester)
    incomplete = await patch(world, a, a.admin, path, item["version"], status="published")
    assert codes(incomplete) == {"category_id": "required", "group_id": "required"}
    filled = await patch(
        world,
        a,
        a.admin,
        path,
        item["version"],
        status="published",
        category_id=await category(world, a),
        group_id=str(a.ga),
    )
    assert filled.status_code == 200, filled.text
    published = filled.json()
    assert published["status"] == "published"
    assert published["published_at"] is not None
    assert item["id"] in await seen_by(world, a, a.requester)
    back = await patch(world, a, a.admin, path, published["version"], status="draft")
    assert codes(back) == {"status": "not_allowed"}
    retired = await patch(world, a, a.admin, path, published["version"], status="retired")
    assert retired.json()["status"] == "retired"
    assert item["id"] not in await seen_by(world, a, a.requester)
    again = await patch(world, a, a.admin, path, retired.json()["version"], status="published")
    assert again.json()["status"] == "published"
    history = await world.sql(
        "SELECT kind FROM field_changes WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    assert "status" in {r["kind"] for r in history}


async def test_a_copy_is_an_independent_draft_and_delete_needs_no_requests(world: World) -> None:
    a = world.a
    original = (await add(world, a, a.admin, featured=True)).json()
    copied = await world.call(
        "POST",
        f"{ITEMS_PATH}/{original['id']}/copy",
        a,
        a.admin,
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert copied.status_code == 201, copied.text
    copy = copied.json()
    assert copy["id"] != original["id"]
    assert (copy["status"], copy["featured"]) == ("draft", False)
    assert copy["names"] == {"en": "Copy of New laptop", "ar": "نسخة من حاسوب جديد"}
    assert copy["group_id"] == original["group_id"]
    raised = await raise_request(world, a, a.requester, catalog_item_id=original["id"])
    assert raised.status_code == 201, raised.text
    used = await world.call(
        "DELETE",
        f"{ITEMS_PATH}/{original['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{original["version"]}"', **CONSOLE},
    )
    assert problem(used) == (409, "catalog_item_in_use")
    deleted = await world.call(
        "DELETE",
        f"{ITEMS_PATH}/{copy['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{copy["version"]}"', **CONSOLE},
    )
    assert deleted.status_code == 204, deleted.text
    assert copy["id"] not in await seen_by(world, a, a.admin)


async def test_the_schedule_publishes_and_retires_on_time(world: World) -> None:
    a = world.a
    now = datetime.now(UTC)
    soon, later = now + timedelta(hours=1), now + timedelta(hours=3)
    planned = (
        await add(
            world,
            a,
            a.admin,
            status="draft",
            publish_at=soon.isoformat(),
            retire_at=later.isoformat(),
        )
    ).json()
    assert planned["status"] == "draft"
    hollow = (await add(world, a, a.admin, status="draft")).json()
    await world.sql(  # an item that became incomplete after it was planned
        "UPDATE catalog_items SET publish_at = $2, group_id = NULL WHERE id = $1",
        uuid.UUID(hollow["id"]),
        soon,
    )
    db = world.app.state.db
    async with db.tenant_session(TenantContext(a.tenant)) as session:
        assert await apply_due(session, FrozenClock(now)) == 0
    async with db.tenant_session(TenantContext(a.tenant)) as session:
        assert await apply_due(session, FrozenClock(soon + timedelta(minutes=1))) == 2
    fresh = (await world.call("GET", f"{ITEMS_PATH}/{planned['id']}", a, a.admin)).json()
    assert (fresh["status"], fresh["publish_at"]) == ("published", None)
    stays = (await world.call("GET", f"{ITEMS_PATH}/{hollow['id']}", a, a.admin)).json()
    assert (stays["status"], stays["publish_at"]) == ("draft", None)
    async with db.tenant_session(TenantContext(a.tenant)) as session:
        assert await apply_due(session, FrozenClock(later + timedelta(minutes=1))) == 1
    fresh = (await world.call("GET", f"{ITEMS_PATH}/{planned['id']}", a, a.admin)).json()
    assert fresh["status"] == "retired"
    audit = await world.sql(
        "SELECT outcome FROM audit_entries"
        " WHERE tenant_id = $1 AND action = 'catalog.item_scheduled'",
        a.tenant,
    )
    assert sorted(r["outcome"] for r in audit) == ["done", "done", "refused"]
    past = await add(
        world, a, a.admin, status="draft", publish_at=(now - timedelta(hours=1)).isoformat()
    )
    assert codes(past) == {"publish_at": "must_be_future"}


# --- the form and what requesters see -------------------------------------------------------------


async def test_questions_meant_for_others_never_reach_the_requester(world: World) -> None:
    a = world.a
    item = (
        await add(
            world,
            a,
            a.admin,
            questions=[
                {"key": "why", "label": {"en": "Why"}, "kind": "long_text", "required": True},
                {
                    "key": "asset_tag",
                    "label": {"en": "Asset tag"},
                    "kind": "text",
                    "shown_to": ["technician"],
                },
                {"key": "mail", "label": {"en": "Mail"}, "kind": "email"},
            ],
            descriptions={"en": '<p>Hi<script>alert(1)</script><a href="javascript:x">y</a></p>'},
            subject_template="Laptop for {person}: {why}",
        )
    ).json()
    assert "<script" not in item["descriptions"]["en"]
    assert "javascript:" not in item["descriptions"]["en"]
    as_requester = (await world.call("GET", f"{ITEMS_PATH}/{item['id']}", a, a.requester)).json()
    assert [q["key"] for q in as_requester["questions"]] == ["why", "mail"]
    assert as_requester["missing_translations"] == []  # for managers only

    async def raise_with(answers: dict[str, Any]) -> Any:  # noqa: ANN401 - httpx response
        return await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers=answers
        )

    sneaky = await raise_with({"why": "Broken", "asset_tag": "A-1"})
    assert sneaky.status_code == 422, sneaky.text
    assert {e["code"] for e in sneaky.json()["errors"]} == {"unknown_question"}
    badmail = await raise_with({"why": "Broken", "mail": "not-an-address"})
    assert {e["code"] for e in badmail.json()["errors"]} == {"email_not_valid"}
    wrong = await add(world, a, a.admin, subject_template="For {nobody}")
    assert codes(wrong) == {"subject_template": "unknown_placeholder"}


async def test_a_report_a_problem_entry_points_at_a_requester_incident_template(
    world: World,
) -> None:
    a = world.a
    listed = await world.call("GET", "/incidents/templates", a, a.admin)  # makes the defaults
    assert listed.status_code == 200, listed.text
    [template] = await world.sql(
        "SELECT id FROM work_item_templates WHERE tenant_id = $1 AND type = 'incident'"
        " AND is_default",
        a.tenant,
    )
    entry = {"kind": "incident_template", "template_id": str(template["id"])}
    hidden = await add(world, a, a.admin, **entry)
    assert codes(hidden) == {"template_id": "not_found"}  # not marked for requesters yet
    await world.sql(
        "UPDATE work_item_templates SET for_requesters = true WHERE id = $1", template["id"]
    )
    made = await add(world, a, a.admin, **entry)
    assert made.status_code == 201, made.text
    assert made.json()["id"] in await seen_by(world, a, a.requester)
    as_request = await raise_request(world, a, a.requester, catalog_item_id=made.json()["id"])
    assert problem(as_request)[0] in {404, 422}  # never a service request
    with_form = await add(
        world,
        a,
        a.admin,
        **entry,
        questions=[{"key": "x", "label": {"en": "X"}, "kind": "text"}],
    )
    assert codes(with_form) == {"kind": "not_allowed"}


# --- search ---------------------------------------------------------------------------------------


async def test_search_finds_words_keywords_typos_and_arabic_and_urdu_spellings(
    world: World,
) -> None:
    a, b = world.a, world.b
    printer = (
        await add(
            world,
            a,
            a.admin,
            names={"en": "Printer toner", "ar": "حبر الطابعة", "ur": "پرنٹر کی سیاہی"},
            keywords={"en": ["cartridge"], "ar": ["خرطوشة"]},
            summaries={"en": "Order toner for a floor printer"},
        )
    ).json()
    access = (
        await add(
            world,
            a,
            a.admin,
            names={"en": "Building access", "ar": "إذن دخول المبنى"},
            descriptions={"en": "<p>A <strong>badge</strong> for the main entrance</p>"},
        )
    ).json()
    draft = (await add(world, a, a.admin, names={"en": "Printer paper"}, status="draft")).json()
    staff_only = (
        await add(world, a, a.admin, names={"en": "Printer driver"}, audience="technicians")
    ).json()
    foreign = (await add(world, b, b.admin, names={"en": "Printer ink"})).json()

    async def found(q: str, user: uuid.UUID | None = None, org: Org = a) -> list[str]:
        response = await world.call(
            "GET", f"{ITEMS_PATH}/search", org, user or org.requester, params={"q": q}
        )
        assert response.status_code == 200, response.text
        return [i["id"] for i in response.json()]

    assert (await found("print"))[0] == printer["id"]  # prefix
    assert printer["id"] in await found("cartridge")  # keyword
    assert printer["id"] in await found("printr")  # typo
    assert access["id"] in await found("badge")  # description, HTML stripped
    # Arabic: hamza forms, ta marbuta written as heh, diacritics typed or left out.
    assert access["id"] in await found("اذن")
    assert access["id"] in await found("إِذْن")
    assert printer["id"] in await found("الطابعه")
    assert printer["id"] in await found("خرطوشه")
    assert printer["id"] in await found("پرنٹر")  # Urdu
    everything = await found("printer")
    assert {draft["id"], staff_only["id"], foreign["id"]}.isdisjoint(everything)
    assert staff_only["id"] in await found("printer", a.tech_a)
    assert draft["id"] in await found("printer", a.admin)
    assert foreign["id"] not in await found("printer", a.admin)  # RLS
    assert printer["id"] not in await found("printer", org=b)


async def _thousand_items(world: World) -> None:
    a = world.a
    holder = uuid.UUID(await category(world, a))
    await world.sql(
        "INSERT INTO catalog_items (id, tenant_id, names, keywords, summaries, status, category_id,"
        " group_id, audience)"
        " SELECT gen_random_uuid(), $1,"
        " jsonb_build_object('en', 'Item ' || n || ' laptop dock', 'ar', 'عنصر ' || n),"
        " jsonb_build_object('en', jsonb_build_array('kw' || n)),"
        " jsonb_build_object('en', 'Summary of service number ' || n),"
        " 'published', $2, $3, 'everyone'"
        " FROM generate_series(1, 1000) AS n",
        a.tenant,
        holder,
        a.ga,
    )
    await world.sql("ANALYZE catalog_items")


async def test_req_cat_028_search_uses_its_indexes_for_1000_items(world: World) -> None:
    """REQ-CAT-028, the timing-free half: at 1,000 items the search predicate is answered from
    the search indexes (GIN on the vector, trigram on the name), never by reading every row.

    Sequential scans are switched off in this transaction only: on a table this small the planner
    may still prefer one, so this asks whether the indexes *can* answer the search. A predicate
    no index can serve would still show a sequential scan. The speed itself is the nightly
    timing test below (perf.yml).
    """
    await _thousand_items(world)
    statements: list[str] = []
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        for q in ["laptop", "lapotp", "kw77", "عنصر"]:  # words, a typo, a keyword, Arabic
            words = await ENGINE.match(session, TEXT, q)
            assert words is not None
            compiled = (
                select(CatalogItem.id)
                .where(words.predicate)
                .compile(dialect=session.get_bind().dialect, compile_kwargs={"literal_binds": True})
            )
            # Literal compilation doubles "%" (the trigram operator <%): undo it for EXPLAIN.
            statements.append(str(compiled).replace("%%", "%"))
    # The bare predicate, as the database admin (no row-level filter, whose tenant index would
    # otherwise answer first): with sequential scans off, only the search indexes can serve it.
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        async with conn.transaction():
            await conn.execute("SET LOCAL enable_seqscan = off")
            for sql in statements:
                plan = "\n".join(r[0] for r in await conn.fetch(f"EXPLAIN {sql}"))
                assert "Seq Scan" not in plan, plan
                assert "ix_catalog_items_search" in plan, plan
    finally:
        await conn.close()


@pytest.mark.timing
async def test_search_answers_within_500_ms_for_1000_items(world: World) -> None:
    """REQ-CAT-028 AC: p95 ≤ 500 ms over 1,000 published items (through the API).

    A wall-clock budget: the real 500 ms in the nightly performance run on a quiet runner
    (perf.yml), ten times it in pull requests (tooling/timing.py), so shared-runner load never
    fails a PR. The PR guarantee is the index test above.
    """
    a = world.a
    await _thousand_items(world)
    timings: list[float] = []
    for q in ["laptop", "dock 42", "kw77", "summary", "lapotp", "عنصر", "item 9"] * 3:
        started = time.perf_counter()
        response = await world.call("GET", f"{ITEMS_PATH}/search", a, a.requester, params={"q": q})
        timings.append(time.perf_counter() - started)
        assert response.status_code == 200, response.text
    p95 = statistics.quantiles(timings, n=20)[18]
    timing.record("catalog_search_1000_items", {"p95_ms": round(p95 * 1000, 1)})
    assert p95 <= timing.limit(0.5), f"p95 {p95:.3f}s"


# --- settings -------------------------------------------------------------------------------------


async def test_settings_read_without_writing_and_change_with_if_match(world: World) -> None:
    a, b = world.a, world.b
    read = await world.call("GET", "/catalog/settings", a, a.requester)
    assert read.json() == {"hide_default_incident_template": False, "version": 1}
    rows = await world.sql(
        "SELECT count(*) AS n FROM catalog_settings WHERE tenant_id = $1", a.tenant
    )
    assert rows[0]["n"] == 0  # GET never writes
    refused = await patch(
        world, a, a.requester, "/catalog/settings", 1, hide_default_incident_template=True
    )
    assert refused.status_code == 403, refused.text
    changed = await patch(
        world, a, a.admin, "/catalog/settings", 1, hide_default_incident_template=True
    )
    assert changed.json() == {"hide_default_incident_template": True, "version": 2}
    stale = await patch(
        world, a, a.admin, "/catalog/settings", 1, hide_default_incident_template=False
    )
    assert problem(stale)[0] == 409
    other = (await world.call("GET", "/catalog/settings", b, b.admin)).json()
    assert other["hide_default_incident_template"] is False  # RLS: a's row is a's


# --- the starter catalog (D-138) ------------------------------------------------------------------


async def _counts(world: World, org: Org) -> tuple[int, int]:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        items = await session.scalar(select(func.count()).select_from(CatalogItem))
        categories = await session.scalar(select(func.count()).select_from(ServiceCategory))
    return int(categories or 0), int(items or 0)


async def test_the_starter_catalog_is_seeded_once_per_tenant(world: World) -> None:
    a, b = world.a, world.b
    db = world.app.state.db

    class Envelope:
        tenant_id = a.tenant

    for _ in range(2):  # the event delivered twice
        async with db.tenant_session(TenantContext(a.tenant)) as session:
            await on_tenant_provisioned(Envelope(), session)  # type: ignore[arg-type]  # only tenant_id is read
    assert await _counts(world, a) == (len(CATEGORIES), len(ITEMS)) == (6, 14)
    assert await _counts(world, b) == (0, 0)  # RLS: nothing leaked into b
    statuses = await world.sql(
        "SELECT DISTINCT status, starter FROM catalog_items WHERE tenant_id = $1", a.tenant
    )
    assert [(r["status"], r["starter"]) for r in statuses] == [("draft", True)]
    # Every text in three languages (the product owner's review: Arabic and Urdu included).
    rows = await world.sql(
        "SELECT names, summaries FROM catalog_items WHERE tenant_id = $1", a.tenant
    )
    texts = [(json.loads(r["names"]), json.loads(r["summaries"])) for r in rows]
    assert all(set(names) == set(summaries) == {"en", "ar", "ur"} for names, summaries in texts)
    # Deleting everything never brings it back: the marker stays.
    await world.sql("UPDATE catalog_items SET deleted_at = now() WHERE tenant_id = $1", a.tenant)
    async with db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await seed_new_tenant(session)).items == 0
        assert (await seed_empty_catalog(session)).items == 0  # deleted rows still count


async def test_the_explicit_run_seeds_only_an_empty_catalog(world: World) -> None:
    a, b = world.a, world.b
    db = world.app.state.db
    await add(world, b, b.admin)  # b already has a catalog
    async with db.tenant_session(TenantContext(b.tenant)) as session:
        assert (await seed_empty_catalog(session)).items == 0
    await world.sql(  # a existed before WP-031: 0074 marked it as seeded
        "INSERT INTO catalog_settings (tenant_id, starter_seeded_at) VALUES ($1, now())", a.tenant
    )
    async with db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await seed_new_tenant(session)).items == 0  # the consumer respects the marker
        assert (await seed_empty_catalog(session)).items == 14  # the deliberate run does not


async def test_choosing_a_group_publishes_the_starter_items(world: World) -> None:
    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await seed_new_tenant(session)
    banner = (await world.call("GET", "/catalog/starter", a, a.admin)).json()
    assert banner == {"drafts": 14}
    assert (await world.call("GET", "/catalog/starter", a, a.requester)).json() == {"drafts": 0}
    assert not await seen_by(world, a, a.requester)
    refused = await world.call(
        "POST",
        "/catalog/starter/publish",
        a,
        a.requester,
        json={"group_id": str(a.ga)},
        headers=CONSOLE,
    )
    assert refused.status_code == 403, refused.text
    foreign = await world.call(
        "POST",
        "/catalog/starter/publish",
        a,
        a.admin,
        json={"group_id": str(world.b.ga)},
        headers=CONSOLE,
    )
    assert codes(foreign) == {"group_id": "not_found"}
    done = await world.call(
        "POST",
        "/catalog/starter/publish",
        a,
        a.admin,
        json={"group_id": str(a.ga)},
        headers=CONSOLE,
    )
    assert done.json() == {"published": 14, "skipped": []}
    assert len(await seen_by(world, a, a.requester)) == 14
    assert (await world.call("GET", "/catalog/starter", a, a.admin)).json() == {"drafts": 0}
    audit = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'catalog.starter_published' AND outcome = 'done'",
        a.tenant,
    )
    assert len(audit) == 1
    # The password item shows self-service first, in every language.
    rows = await world.sql(
        "SELECT descriptions FROM catalog_items WHERE tenant_id = $1 AND names->>'en' = $2",
        a.tenant,
        "Password or MFA reset help",
    )
    assert set(json.loads(rows[0]["descriptions"])) == {"en", "ar", "ur"}


async def test_the_tooling_command_finds_the_tenant_by_slug(world: World) -> None:
    from tooling.catalog_starter import seed  # noqa: PLC0415 - tooling, imported where used

    a = world.a
    assert await seed(world.db.migrator_url, "no-such-tenant") is None
    [row] = await world.sql("SELECT slug FROM tenants WHERE id = $1", a.tenant)
    first = await seed(world.db.migrator_url, row["slug"])
    assert first is not None
    assert (first.categories, first.items) == (6, 14)
    again = await seed(world.db.migrator_url, row["slug"])
    assert again is not None
    assert again.items == 0  # never into a catalog that has content


async def test_provisioning_writes_the_event_in_the_tenants_transaction(world: World) -> None:
    from app.modules.organization import record_tenant_provisioned  # noqa: PLC0415 - one test

    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await record_tenant_provisioned(session)
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = 'organization.tenant.provisioned'"
        " AND aggregate_id = $1",
        str(a.tenant),
    )
    [envelope] = [json.loads(r["envelope"]) for r in rows]
    assert envelope["payload"] == {"tenant_id": str(a.tenant)}
    assert envelope["tenant_id"] == str(a.tenant)


async def test_hiding_the_general_form_keeps_a_way_to_report(world: World) -> None:
    """Plan D7: with the setting on, the portal offers the catalog's entries' forms, not the
    general one; with nothing else marked for requesters it keeps the general form."""
    a = world.a
    listed = await world.call("GET", "/incidents/templates", a, a.admin)  # makes the defaults
    assert listed.status_code == 200, listed.text
    on = await patch(world, a, a.admin, "/catalog/settings", 1, hide_default_incident_template=True)
    assert on.status_code == 200, on.text

    async def offered() -> list[bool]:
        got = await world.call("GET", "/portal/incidents/templates", a, a.requester)
        assert got.status_code == 200, got.text
        rows = await world.sql(
            "SELECT id, is_default FROM work_item_templates WHERE tenant_id = $1", a.tenant
        )
        defaults = {str(r["id"]): r["is_default"] for r in rows}
        return [defaults[t["id"]] for t in got.json()]

    assert await offered() == [True]  # the only form: kept
    [other] = await world.sql(
        "INSERT INTO work_item_templates (id, tenant_id, type, labels, for_requesters, desk_id)"
        " VALUES (gen_random_uuid(), $1, 'incident', '{\"en\": \"Printer broken\"}', true,"
        " (SELECT id FROM desks WHERE tenant_id = $1 AND is_default)) RETURNING id",
        a.tenant,
    )
    await world.sql(
        "UPDATE work_item_templates SET for_requesters = true WHERE tenant_id = $1 AND is_default",
        a.tenant,
    )
    assert await offered() == [False]  # the general form hidden, the entry's form offered
    assert other["id"] is not None
