"""Worklog costs, billable time and the closed-record rule over HTTP (WP-046a S3; REQ-INC-068, 070).

Real PostgreSQL, the incidents test world. People's rates are identity_access's (lane B); here a
fake behind the work_items port gives them, so these tests only see what work_items does with a
rate. Each test names the requirement and criterion.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantContext
from app.modules.work_items.service import cost_rates
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, Org, World, field_codes, problem

pytestmark = [pytest.mark.db, pytest.mark.valkey, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, used by name

START = "2026-11-12T09:00:00Z"


class FakeRates:
    """A rate per person from a given time; nothing before it."""

    def __init__(self) -> None:
        self.rates: dict[uuid.UUID, list[tuple[datetime, Decimal]]] = {}
        self.asked: list[tuple[uuid.UUID, datetime]] = []

    def set(self, user_id: uuid.UUID, start: str, rate: str) -> None:
        self.rates.setdefault(user_id, []).append((datetime.fromisoformat(start), Decimal(rate)))

    async def cost_rate(
        self, session: AsyncSession, user_id: uuid.UUID, at: datetime
    ) -> Decimal | None:
        del session
        self.asked.append((user_id, at))
        found = [r for start, r in sorted(self.rates.get(user_id, [])) if start <= at]
        return found[-1] if found else None


@pytest.fixture
def rates() -> Iterator[FakeRates]:
    fake = FakeRates()
    cost_rates.register_cost_rates(fake)
    try:
        yield fake
    finally:
        cost_rates.reset_cost_rates()


async def log(
    world: World, org: Org, user: uuid.UUID, item: dict[str, Any], **body: object
) -> httpx.Response:
    return await world.call("POST", f"{BASE}/{item['id']}/worklogs", org, user, json=body)


async def worklogs(world: World, org: Org, user: uuid.UUID, item: dict[str, Any]) -> dict[str, Any]:
    found = await world.call("GET", f"{BASE}/{item['id']}/worklogs", org, user)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def test_req_inc_068_ac1_cost_is_the_rate_when_the_time_started(
    world: World, rates: FakeRates
) -> None:
    a = world.a
    rates.set(a.tech_a, "2026-01-01T00:00:00+00:00", "40.00")
    rates.set(a.tech_a, "2026-12-01T00:00:00+00:00", "55.00")  # later: never used for November
    item = await world.create(a, a.admin, group_id=str(a.ga))
    logged = await log(
        world, a, a.admin, item, owner_id=str(a.tech_a), worklog_type="fix",
        started_at=START, minutes=90,
    )  # fmt: skip
    assert logged.status_code == 201, logged.text
    body = logged.json()
    assert (Decimal(body["cost_rate"]), Decimal(body["technician_cost"])) == (
        Decimal("40.00"),
        Decimal("60.00"),
    )
    assert rates.asked[-1] == (a.tech_a, datetime.fromisoformat("2026-11-12T09:00:00+00:00"))
    # A new duration takes the cost again; a description alone does not ask for a rate.
    path = f"{BASE}/{item['id']}/worklogs/{body['id']}"
    asked = len(rates.asked)
    noted = await world.call(
        "PATCH", path, a, a.admin, json={"description": "Swapped the fuser"},
        headers={"If-Match": '"1"'},
    )  # fmt: skip
    assert noted.status_code == 200, noted.text
    assert len(rates.asked) == asked
    longer = await world.call(
        "PATCH", path, a, a.admin, json={"minutes": 120}, headers={"If-Match": '"2"'}
    )
    assert Decimal(longer.json()["technician_cost"]) == Decimal("80.00")
    # Nobody set a rate: no cost, never a zero passed off as one.
    unrated = await log(
        world, a, a.admin, item, owner_id=str(a.tech_c), worklog_type="fix",
        started_at=START, minutes=30,
    )  # fmt: skip
    assert (unrated.json()["cost_rate"], unrated.json()["technician_cost"]) == (None, None)


async def test_req_inc_068_ac2_costs_are_hidden_without_the_cost_right(
    world: World, rates: FakeRates
) -> None:
    a = world.a
    rates.set(a.tech_a, "2026-01-01T00:00:00+00:00", "40.00")
    item = await world.create(a, a.admin, group_id=str(a.ga))
    mine = await log(
        world, a, a.tech_a, item, worklog_type="fix", started_at=START, minutes=60,
        costs=[{"amount": "12.50", "note": "Cable"}],
    )  # fmt: skip
    assert mine.status_code == 201, mine.text
    # A technician works the record but holds no cost right: time yes, money nowhere.
    assert mine.json()["money_hidden"] is True
    assert (mine.json()["cost_rate"], mine.json()["costs"]) == (None, [])
    seen = await worklogs(world, a, a.tech_a, item)
    assert seen["minutes"] == 60
    assert seen["money_hidden"] is True
    for name in ("technician_cost", "other_cost", "total_cost", "currency"):
        assert seen[name] is None, name
    assert all(i["technician_cost"] is None and i["costs"] == [] for i in seen["items"])
    # The admin holds every right and sees it all, in the base currency.
    full = await worklogs(world, a, a.admin, item)
    assert full["money_hidden"] is False
    assert full["currency"] == "USD"
    assert (
        Decimal(full["technician_cost"]),
        Decimal(full["other_cost"]),
        Decimal(full["total_cost"]),
    ) == (Decimal("40.00"), Decimal("12.50"), Decimal("52.50"))
    # A task's extra cost follows the same right (S1 had "may edit").
    task = await world.call(
        "POST",
        f"{BASE}/{item['id']}/tasks",
        a,
        a.admin,
        json={"title": "Order", "extra_cost": "9.99"},
    )
    assert task.status_code == 201, task.text
    listed = (await world.call("GET", f"{BASE}/{item['id']}/tasks", a, a.tech_a)).json()
    assert [t["extra_cost"] for t in listed["items"]] == [None]
    listed = (await world.call("GET", f"{BASE}/{item['id']}/tasks", a, a.admin)).json()
    assert [Decimal(t["extra_cost"]) for t in listed["items"]] == [Decimal("9.99")]


async def test_req_inc_068_billable_totals_and_other_costs_in_another_currency(
    world: World, rates: FakeRates
) -> None:
    a = world.a
    del rates  # no rates: only time and other costs
    item = await world.create(a, a.admin, group_id=str(a.ga))
    billed = await log(
        world, a, a.admin, item, worklog_type="fix", started_at=START, minutes=45, billable=True,
        costs=[{"original_amount": "100.00", "original_currency": "EUR", "exchange_rate": "1.085"}],
    )  # fmt: skip
    assert billed.status_code == 201, billed.text
    [line] = billed.json()["costs"]
    assert (Decimal(line["amount"]), line["original_currency"]) == (Decimal("108.50"), "EUR")
    await log(world, a, a.admin, item, worklog_type="travel", started_at=START, minutes=15)
    found = await worklogs(world, a, a.admin, item)
    assert (found["minutes"], found["billable_minutes"], found["non_billable_minutes"]) == (
        60,
        45,
        15,
    )
    assert Decimal(found["other_cost"]) == Decimal("108.50")
    # Another currency without the rate the person paid at is refused, naming the line.
    no_rate = await log(
        world, a, a.admin, item, worklog_type="fix", started_at=START, minutes=5,
        costs=[{"amount": "1.00"}, {"original_amount": "5.00", "original_currency": "EUR"}],
    )  # fmt: skip
    assert field_codes(no_rate) == {"costs.1.exchange_rate": "required"}
    # The lines change together: a PATCH replaces them all.
    path = f"{BASE}/{item['id']}/worklogs/{billed.json()['id']}"
    replaced = await world.call(
        "PATCH", path, a, a.admin, json={"costs": [{"amount": "3.00"}]}, headers={"If-Match": '"1"'}
    )  # fmt: skip
    assert [Decimal(c["amount"]) for c in replaced.json()["costs"]] == [Decimal("3.00")]
    assert Decimal((await worklogs(world, a, a.admin, item))["other_cost"]) == Decimal("3.00")


async def _block_closed(world: World, org: Org, *, on: bool) -> None:
    current = (await world.call("GET", f"{BASE}/settings", org, org.admin)).json()
    changed = await world.call(
        "PATCH",
        f"{BASE}/settings/closure",
        org,
        org.admin,
        json={"worklog_block_closed": on},
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["closure"]["worklog_block_closed"] is on


async def test_req_inc_070_a_closed_record_refuses_time_when_the_rule_is_on(world: World) -> None:
    a = world.a
    await _block_closed(world, a, on=True)
    try:
        await _closed_record_refuses(world, a)
    finally:
        await _block_closed(world, a, on=False)  # the shared world: back to the default


async def _closed_record_refuses(world: World, a: Org) -> None:
    item = await world.create(a, a.admin, group_id=str(a.ga))
    before = await log(world, a, a.admin, item, worklog_type="fix", started_at=START, minutes=10)
    assert before.status_code == 201, before.text
    resolved = (await world.act(a, a.admin, item, "resolve")).json()
    # Resolved is not closed: time can still be logged.
    late = await log(world, a, a.admin, item, worklog_type="fix", started_at=START, minutes=5)
    assert late.status_code == 201, late.text
    closed = await world.act(a, a.admin, resolved, "close")
    assert closed.status_code == 200, closed.text
    refused = await log(world, a, a.admin, item, worklog_type="fix", started_at=START, minutes=5)
    assert problem(refused) == (409, "worklog_record_closed")
    path = f"{BASE}/{item['id']}/worklogs/{before.json()['id']}"
    changed = await world.call(
        "PATCH", path, a, a.admin, json={"minutes": 20}, headers={"If-Match": '"1"'}
    )
    assert problem(changed) == (409, "worklog_record_closed")
    removed = await world.call("DELETE", path, a, a.admin, headers={"If-Match": '"1"'})
    assert problem(removed) == (409, "worklog_record_closed")
    # Off (the default) a closed record still takes time, as before S3.
    await _block_closed(world, a, on=False)
    allowed = await log(world, a, a.admin, item, worklog_type="fix", started_at=START, minutes=5)
    assert allowed.status_code == 201, allowed.text


async def test_worklog_settings_default_and_refuse_non_booleans(world: World) -> None:
    a = world.a
    closure = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()["closure"]
    assert (
        closure["worklog_block_closed"],
        closure["worklog_count_nonworking"],
        closure["timer_auto_start"],
    ) == (False, True, False)
    current = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
    refused = await world.call(
        "PATCH", f"{BASE}/settings/closure", a, a.admin, json={"timer_auto_start": "yes"},
        headers={"If-Match": f'"{current["version"]}"'},
    )  # fmt: skip
    assert refused.status_code == 422, refused.text


async def test_cost_lines_are_isolated_by_rls(world: World, rates: FakeRates) -> None:
    a, b = world.a, world.b
    del rates
    item = await world.create(a, a.admin, group_id=str(a.ga))
    await log(
        world, a, a.admin, item, worklog_type="fix", started_at=START, minutes=5,
        costs=[{"amount": "1.00"}],
    )  # fmt: skip
    table = "work_item_worklog_costs"
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert (await session.execute(text(f"SELECT id FROM {table}"))).all() == []  # noqa: S608 - fixed name
        changed = await session.execute(text(f"UPDATE {table} SET amount = 0"))  # noqa: S608 - fixed name
        assert changed.rowcount == 0
    rows = await world.sql(
        f"SELECT count(*) AS n FROM {table} WHERE tenant_id = $1 AND work_item_id = $2",  # noqa: S608 - fixed name
        a.tenant,
        uuid.UUID(item["id"]),
    )
    assert rows[0]["n"] == 1
