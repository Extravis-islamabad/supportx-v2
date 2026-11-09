"""Loanable assets, loans, returns and their notices (WP-049a s5; REQ-AST-029..031, 059; 0114)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.assets.service.loans import notify_due
from tests.db import test_incidents_api
from tests.db.test_asset_holders_api import _asset
from tests.db.test_asset_moves_api import _states
from tests.db.test_incidents_api import World, field_codes, problem
from tests.db.test_knowledge_api import _match

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"


def _soon(days: int = 7) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


async def _loanable(world: World, *assets: dict[str, Any]) -> None:
    a = world.a
    done = await world.call(
        "POST", f"{BASE}/loanable", a, a.admin,
        json={"asset_ids": [x["id"] for x in assets], "loanable": True},
    )  # fmt: skip
    assert done.status_code == 200, done.text


async def _loan(world: World, assets: list[dict[str, Any]], borrower: uuid.UUID) -> Any:  # noqa: ANN401 - httpx response
    a = world.a
    return await world.call(
        "POST", f"{BASE}/loans", a, a.admin,
        json={
            "borrower_id": str(borrower),
            "asset_ids": [x["id"] for x in assets],
            "due_at": _soon(),
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )  # fmt: skip


async def _outbox(world: World, kind: str, change: str | None = None) -> int:
    rows = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1"
        " AND envelope->>'event_type' = $2"
        " AND ($3::text IS NULL OR envelope->'payload'->>'change' = $3)",
        world.a.tenant,
        kind,
        change,
    )
    return int(rows[0]["n"])


async def test_a_loan_moves_assets_in_use_and_returns_bring_them_back(world: World) -> None:
    """030 AC1, 031 AC1-AC3: in use and held while out; one back leaves it open; last closes."""
    a = world.a
    states = await _states(world, a)
    one, two = await _asset(world, "Loan one"), await _asset(world, "Loan two")
    await _loanable(world, one, two)
    made = await _loan(world, [one, two], a.requester)
    assert made.status_code == 201, made.text
    loan = made.json()
    assert (loan["status"], len(loan["outstanding"])) == ("open", 2)
    assert sorted(a["name"] for a in loan["assets"]) == ["Loan one", "Loan two"]  # the register
    mine = (await world.call("GET", f"{BASE}/mine", a, a.requester)).json()
    due = {m["id"]: m["loan_due_at"] for m in mine}
    assert due[one["id"]] == loan["due_at"]  # the borrower sees when it is due back
    for asset in (one, two):
        now = (await world.call("GET", f"{BASE}/{asset['id']}", a, a.admin)).json()
        assert (now["state_id"], now["owner_user_id"]) == (states["in_use"], str(a.requester))
        held = (await world.call("GET", f"{BASE}/{asset['id']}/holdings", a, a.admin)).json()
        assert held[0]["holder_id"] == str(a.requester)
    back = await world.call(
        "POST", f"{BASE}/loans/{loan['id']}/returns", a, a.admin, json={"asset_ids": [one["id"]]}
    )
    assert back.status_code == 200, back.text
    assert (back.json()["status"], back.json()["outstanding"]) == ("open", [two["id"]])
    no_reason = await world.call(
        "POST", f"{BASE}/loans/{loan['id']}/returns", a, a.admin,
        json={"asset_ids": [two["id"]], "outcome": "in_repair"},
    )  # fmt: skip
    assert field_codes(no_reason) == {"comment": "required"}
    last = await world.call(
        "POST", f"{BASE}/loans/{loan['id']}/returns", a, a.admin,
        json={"asset_ids": [two["id"]], "outcome": "in_repair", "comment": "Hinge broken"},
    )  # fmt: skip
    assert last.json()["status"] == "closed"
    came_back = {x["id"]: x["outcome"] for x in last.json()["assets"]}
    assert came_back == {one["id"]: "in_stock", two["id"]: "in_repair"}
    mine = (await world.call("GET", f"{BASE}/mine", a, a.requester)).json()
    assert all(m["loan_due_at"] is None for m in mine)
    assert (await world.call("GET", f"{BASE}/{one['id']}", a, a.admin)).json()["state_id"] == (
        states["in_stock"]
    )
    repaired = (await world.call("GET", f"{BASE}/{two['id']}", a, a.admin)).json()
    assert (repaired["state_id"], repaired["owner_user_id"]) == (states["in_repair"], None)
    assert await _outbox(world, "assets.loan.changed", "closed") >= 1


async def test_only_loanable_in_stock_assets_go_on_one_loan_at_a_time(world: World) -> None:
    """029 AC2, 030 AC3, 017 AC1."""
    a = world.a
    plain = await _asset(world, "Not loanable")
    assert problem(await _loan(world, [plain], a.requester))[1] == "asset_not_loanable"
    out = await _asset(world, "Out once")
    await _loanable(world, out)
    assert (await _loan(world, [out], a.requester)).status_code == 201
    # Already in use and on a loan: refused, whoever asks.
    assert problem(await _loan(world, [out], a.tech_a))[0] == 409
    fresh = (await world.call("GET", f"{BASE}/{out['id']}", a, a.admin)).json()
    disposed = await world.call(
        "POST", f"{BASE}/{out['id']}/dispose", a, a.admin,
        json={"disposed_on": "2026-11-01", "method": "recycling", "reason": "x"},
        headers=_match(fresh["version"]),
    )  # fmt: skip
    assert problem(disposed) == (409, "asset_on_loan")
    past = await world.call(
        "POST", f"{BASE}/loans", a, a.admin,
        json={
            "borrower_id": str(a.requester),
            "asset_ids": [plain["id"]],
            "due_at": "2020-01-01T00:00:00Z",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )  # fmt: skip
    assert "due_at" in field_codes(past)


async def test_two_loans_racing_for_one_asset_never_both_win(world: World) -> None:
    """030 AC3, condition 1: the database's unique open item decides, not only the check."""
    a = world.a
    asset = await _asset(world, "Raced")
    await _loanable(world, asset)
    first, second = await asyncio.gather(
        _loan(world, [asset], a.requester), _loan(world, [asset], a.requester2)
    )
    codes = sorted([first.status_code, second.status_code])
    assert codes == [201, 409], (first.text, second.text)
    rows = await world.sql(
        "SELECT count(*) AS n FROM asset_loan_items WHERE tenant_id = $1 AND asset_id = $2"
        " AND returned_at IS NULL",
        a.tenant,
        uuid.UUID(asset["id"]),
    )
    assert rows[0]["n"] == 1


async def test_due_and_overdue_notices_go_out_exactly_once_with_two_workers(world: World) -> None:
    """059 AC1, condition 2: claimed by one UPDATE ... RETURNING per loan."""
    a = world.a
    asset = await _asset(world, "Overdue laptop")
    await _loanable(world, asset)
    loan = (await _loan(world, [asset], a.requester)).json()
    await world.sql(
        "UPDATE asset_loans SET due_at = now() - interval '1 hour', starts_at = now() - interval"
        " '2 days' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(loan["id"]),
    )

    async def worker() -> int:
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            return await notify_due(session)

    await asyncio.gather(worker(), worker())
    assert await _outbox(world, "assets.loan.changed", "overdue") == 1
    await worker()
    assert await _outbox(world, "assets.loan.changed", "overdue") == 1
    listed = (await world.call("GET", f"{BASE}/loans", a, a.tech_a)).json()
    assert next(x for x in listed if x["id"] == loan["id"])["status"] == "overdue"


async def test_a_warranty_ending_is_noticed_once_per_date(world: World) -> None:
    """059 AC2: within the notice days (Appendix A: 30), to the managers, once per date."""
    a = world.a
    asset = await _asset(world, "Warranty soon")
    soon = (datetime.now(UTC) + timedelta(days=10)).date()
    changed = await world.call(
        "PATCH", f"{BASE}/{asset['id']}", a, a.admin,
        json={"warranty_expires_on": soon.isoformat()}, headers=_match(asset["version"]),
    )  # fmt: skip
    assert changed.status_code == 200
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await notify_due(session)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await notify_due(session)
    assert await _outbox(world, "assets.warranty.ending") == 1


async def test_loans_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    asset = await _asset(world, "RLS loan")
    await _loanable(world, asset)
    assert (await _loan(world, [asset], a.requester)).status_code == 201
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in ("asset_loans", "asset_loan_items"):
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608 - fixed names
        assert (await session.execute(text("UPDATE asset_loans SET comment = 'x'"))).rowcount == 0
    assert (await world.call("GET", f"{BASE}/loans", b, b.admin)).json() == []
