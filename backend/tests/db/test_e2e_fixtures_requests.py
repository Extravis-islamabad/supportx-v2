"""The e2e teardown on a tenant with service requests (WP-030; stack smoke 41826831299).

The suite's "E2E …" requests have approvals (which reference the record) and e-mailed approval
links (which name the approval). The teardown removes them before the record, then the suite's
catalog items and their emptied categories. Nothing else is touched: another request, its
approval and link, and an "E2E" item a remaining request still names all stay.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core.tenancy import TenantContext
from app.modules.work_items.infra.models import WorkItemApproval
from app.modules.work_items.service.approvals import issue_links
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import MANAGER, manager_of
from tests.db.test_incidents_api import CONSOLE, Org, World
from tests.db.test_service_requests_api import an_item, raise_request
from tooling import e2e_fixtures

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def _category(world: World, org: Org, name: str) -> str:
    made = await world.call(
        "POST",
        "/catalog/categories",
        org,
        org.admin,
        json={"names": {"en": name}},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


async def _request(world: World, org: Org, item: dict[str, Any], subject: str) -> uuid.UUID:
    made = await raise_request(
        world,
        org,
        org.requester,
        catalog_item_id=item["id"],
        answers={"model": "air"},
        subject=subject,
    )
    assert made.status_code == 201, made.text
    record = uuid.UUID(made.json()["id"])
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        rows = list(
            await session.scalars(
                select(WorkItemApproval).where(WorkItemApproval.work_item_id == record)
            )
        )
        assert rows, "the request waits for an approval"
        await issue_links(session, rows)  # as the e-mail would
    return record


async def test_the_teardown_removes_the_suites_requests_with_their_approvals(
    world: World,
) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    suite_category = await _category(world, a, "E2E chairs")
    suite_item = await an_item(
        world, a, names={"en": "E2E chair"}, category_id=suite_category, **MANAGER
    )
    shared_item = await an_item(world, a, names={"en": "E2E desk"}, **MANAGER)
    keep_item = await an_item(world, a, names={"en": "Keep laptop"}, **MANAGER)
    suite = await _request(world, a, suite_item, "E2E chair for Adel")
    await _request(world, a, shared_item, "E2E desk for Adel")
    kept = await _request(world, a, keep_item, "Laptop for Sara")
    still_named = await _request(world, a, shared_item, "Desk for Omar")  # not the suite's

    removed = await e2e_fixtures.delete_suite_records(
        world.db.migrator_url, (a.tenant,), test_tenants=True
    )

    assert removed["work_items"] == 2
    assert removed["work_item_approvals"] == 2
    assert removed["action_links"] == 2
    assert removed["catalog_items"] == 1  # "E2E desk" stays: "Desk for Omar" names it
    assert removed["service_categories"] == 1
    left = await world.sql(
        "SELECT w.id, count(a.id) AS approvals, count(l.id) AS links FROM work_items w"
        " LEFT JOIN work_item_approvals a ON a.work_item_id = w.id"
        " LEFT JOIN action_links l ON l.object_id = a.id"
        " WHERE w.tenant_id = $1 AND w.catalog_item_id IS NOT NULL GROUP BY w.id",
        a.tenant,
    )
    assert {r["id"]: (r["approvals"], r["links"]) for r in left} == {
        kept: (1, 1),
        still_named: (1, 1),
    }
    assert suite not in {r["id"] for r in left}
    items = await world.sql(
        "SELECT names->>'en' AS name FROM catalog_items WHERE tenant_id = $1 ORDER BY 1", a.tenant
    )
    assert [r["name"] for r in items] == ["E2E desk", "Keep laptop"]


async def test_the_teardown_removes_every_row_that_references_a_suite_record(world: World) -> None:
    """Children found in the catalogue, not a hand-kept list (the nightly k3d run's FK failure).

    An unread marker (work_item_reads, WP-046b S3) was not on the old list, so the teardown failed
    on its foreign key. Every table with a blocking foreign key onto work_items is now covered
    whatever adds it later: the suite's request goes with its marker, another record keeps its own.
    """
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await an_item(world, a, names={"en": "Keep monitor"}, **MANAGER)
    suite = await _request(world, a, item, "E2E monitor for Adel")
    kept = await _request(world, a, item, "Monitor for Sara")
    for record in (suite, kept):
        await world.sql(
            "INSERT INTO work_item_reads (tenant_id, user_id, work_item_id, seen_version)"
            " VALUES ($1, $2, $3, 1)",
            a.tenant,
            a.tech_a,
            record,
        )

    removed = await e2e_fixtures.delete_suite_records(
        world.db.migrator_url, (a.tenant,), test_tenants=True
    )

    assert removed["work_items"] == 1
    assert removed[e2e_fixtures.WORK_ITEM_DEPENDENTS] >= 1  # the marker, and whatever else
    reads = await world.sql(
        "SELECT work_item_id FROM work_item_reads WHERE tenant_id = $1", a.tenant
    )
    assert {r["work_item_id"] for r in reads} == {kept}
    # Coverage (lane A): no blocking foreign key onto work_items, read from the same catalogue
    # query the teardown uses, still holds the removed suite record's ID.
    fks = await world.sql(e2e_fixtures._BLOCKING_FKS, "work_items")  # noqa: SLF001 - the tool's own query
    assert any(r["child"] == "work_item_reads" for r in fks), [r["child"] for r in fks]
    for fk in fks:
        held = await world.sql(
            f'SELECT count(*) AS n FROM {fk["child"]} WHERE "{fk["col"]}" = $1',  # noqa: S608 - catalogue names
            suite,
        )
        assert held[0]["n"] == 0, f"{fk['child']}.{fk['col']} still names the removed record"


async def test_the_teardown_refuses_a_tenant_other_than_the_dev_ones(world: World) -> None:
    """Rule 5h: pointed at another tenant without a test's say-so, it refuses before any delete."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await an_item(world, a, names={"en": "Keep dock"}, **MANAGER)
    record = await _request(world, a, item, "E2E dock for Adel")
    with pytest.raises(ValueError, match="dev tenants"):
        await e2e_fixtures.delete_suite_records(world.db.migrator_url, (a.tenant,))
    left = await world.sql("SELECT id FROM work_items WHERE id = $1", record)
    assert [r["id"] for r in left] == [record]  # nothing was removed
