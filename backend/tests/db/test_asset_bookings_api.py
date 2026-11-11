"""Bookings ahead and the loan register's leftovers (WP-049b s1; REQ-AST-030, 032; 0130).

The incident world: org A's admin holds everything; technicians only view assets; requesters
have no asset permission. Org A has sites s1 and s2.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.assets.service.realtime import (
    ASSET_CHANGED,
    BOOKINGS_CHANGED,
    MINE_CHANGED,
    ROUTES,
)
from app.shared.events import EventEnvelope
from app.shared.realtime import broadcast, personal, record
from tests.db import test_incidents_api
from tests.db.test_asset_holders_api import _asset
from tests.db.test_asset_loans_api import _loan, _loanable
from tests.db.test_incidents_api import Org, World, field_codes, problem
from tests.db.test_knowledge_api import _match

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def _day(days: int, hour: int = 9) -> datetime:
    """A whole day ahead, at `hour` UTC."""
    base = datetime.now(UTC).replace(hour=hour, minute=0, second=0, microsecond=0)
    return base + timedelta(days=days)


async def _projector(world: World, name: str) -> dict[str, Any]:
    asset = await _asset(world, name)
    await _loanable(world, asset)
    return asset


async def _book(
    world: World,
    asset: dict[str, Any],
    starts: datetime,
    ends: datetime,
    *,
    borrower: uuid.UUID | None = None,
    user: uuid.UUID | None = None,
    **extra: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - httpx response
    a = world.a
    return await world.call(
        "POST", f"{BASE}/bookings", a, user or a.admin,
        json={
            "asset_id": asset["id"],
            "borrower_id": str(borrower or a.requester),
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            **extra,
        },
        headers=_key(),
    )  # fmt: skip


async def test_032_ac1_a_taken_day_is_refused_and_the_next_free_day_suggested(
    world: World,
) -> None:
    a = world.a
    projector = await _projector(world, "Projector P1")
    first = await _book(world, projector, _day(3), _day(3, 17), comment="Training day")
    assert first.status_code == 201, first.text
    assert (first.json()["status"], first.json()["channel"]) == ("booked", "console")
    # The day after is booked too: the suggestion skips it.
    assert (await _book(world, projector, _day(4), _day(4, 17))).status_code == 201
    taken = await _book(world, projector, _day(3, 13), _day(3, 15), borrower=a.requester2)
    assert problem(taken) == (409, "asset_booking_taken")
    suggested = datetime.fromisoformat(taken.json()["params"]["next_free"])
    assert suggested == _day(5, 13)
    # Touching ends do not overlap; the suggested day is free.
    assert (await _book(world, projector, _day(3, 17), _day(3, 19))).status_code == 201
    assert (
        await _book(world, projector, suggested, suggested + timedelta(hours=2))
    ).status_code == 201
    # Checked: the end after the start, not in the past, not too long; staff only.
    backwards = await _book(world, projector, _day(6, 17), _day(6, 9))
    assert field_codes(backwards) == {"ends_at": "asset_booking_ends_before_start"}
    too_long = await _book(world, projector, _day(6), _day(120))
    assert field_codes(too_long) == {"ends_at": "asset_booking_too_long"}
    assert (await _book(world, projector, _day(7), _day(8), user=a.tech_a)).status_code == 403
    plain = await _asset(world, "Not loanable P")
    assert problem(await _book(world, plain, _day(7), _day(8))) == (409, "asset_not_bookable")
    # The calendar: by asset, and by product and site (availability).
    listed = (
        await world.call("GET", f"{BASE}/bookings?asset_id={projector['id']}", a, a.tech_a)
    ).json()
    assert len(listed) == 4
    held = (await world.call("GET", f"{BASE}/availability?q=Projector%20P1", a, a.tech_a)).json()
    assert [x["id"] for x in held] == [projector["id"]]
    assert len(held[0]["held"]) == 4
    assert "borrower_id" not in held[0]["held"][0]


async def test_032_two_bookings_racing_for_the_same_time_never_both_win(world: World) -> None:
    a = world.a
    projector = await _projector(world, "Raced projector")
    one, two = await asyncio.gather(
        _book(world, projector, _day(2), _day(2, 17)),
        _book(world, projector, _day(2, 10), _day(2, 12), borrower=a.requester2),
    )
    assert sorted([one.status_code, two.status_code]) == [201, 409], (one.text, two.text)
    rows = await world.sql(
        "SELECT count(*) AS n FROM asset_bookings WHERE tenant_id = $1 AND asset_id = $2"
        " AND status = 'booked'",
        a.tenant,
        uuid.UUID(projector["id"]),
    )
    assert rows[0]["n"] == 1


async def test_032_ac2_handing_over_turns_the_booking_into_a_loan_with_its_dates(
    world: World,
) -> None:
    a = world.a
    projector = await _projector(world, "Handover projector")
    starts, ends = datetime.now(UTC) - timedelta(minutes=5), _day(2, 17)
    booking = (await _book(world, projector, starts, ends, borrower=a.requester)).json()
    # Another loan over the booked time is refused while the booking holds it.
    over = await _loan(world, [projector], a.requester2)
    assert problem(over) == (409, "asset_booked")
    handed = await world.call(
        "POST", f"{BASE}/bookings/{booking['id']}/handover", a, a.admin,
        headers=_match(booking["version"]),
    )  # fmt: skip
    assert handed.status_code == 200, handed.text
    loan, after = handed.json()["loan"], handed.json()["booking"]
    assert datetime.fromisoformat(loan["starts_at"]) == starts
    assert datetime.fromisoformat(loan["due_at"]) == ends
    assert (loan["borrower_id"], loan["booking_id"]) == (str(a.requester), booking["id"])
    assert (after["status"], after["loan_id"]) == ("handed_over", loan["id"])
    assert loan["display_id"].startswith("LN-")
    asset = (await world.call("GET", f"{BASE}/{projector['id']}", a, a.admin)).json()
    assert asset["owner_user_id"] == str(a.requester)
    again = await world.call(
        "POST", f"{BASE}/bookings/{booking['id']}/handover", a, a.admin,
        headers=_match(after["version"]),
    )  # fmt: skip
    assert problem(again) == (409, "asset_booking_not_open")
    # While it is out, its loan holds it: a booking over that time is refused.
    clash = await _book(world, projector, _day(1), _day(1, 17), borrower=a.requester2)
    assert problem(clash) == (409, "asset_booking_taken")


async def test_032_ac3_a_requester_books_from_the_portal_only_when_allowed(world: World) -> None:
    a = world.a
    projector = await _projector(world, "Portal projector")
    mine = (await world.call("GET", f"{BASE}/my-bookings", a, a.requester)).json()
    assert (mine["enabled"], mine["bookings"]) == (False, [])
    body = {"asset_id": projector["id"], "starts_at": _day(5).isoformat(),
            "ends_at": _day(5, 17).isoformat()}  # fmt: skip
    off = await world.call("POST", f"{BASE}/my-bookings", a, a.requester, json=body, headers=_key())
    assert problem(off) == (403, "asset_portal_booking_off")
    assert (await world.call("GET", f"{BASE}/bookable", a, a.requester)).status_code == 403
    settings = await world.call("GET", f"{BASE}/settings", a, a.admin)
    turned = await world.call(
        "PATCH", f"{BASE}/settings", a, a.admin, json={"portal_booking": True},
        headers=_match(settings.json()["version"]),
    )  # fmt: skip
    assert turned.json()["portal_booking"] is True
    offered = (await world.call("GET", f"{BASE}/bookable?q=Portal", a, a.requester)).json()
    assert projector["id"] in {x["id"] for x in offered}
    made = await world.call(
        "POST", f"{BASE}/my-bookings", a, a.requester, json=body, headers=_key()
    )
    assert made.status_code == 201, made.text
    assert (made.json()["borrower_id"], made.json()["channel"]) == (str(a.requester), "portal")
    taken = await world.call(
        "POST", f"{BASE}/my-bookings", a, a.requester2, json=body, headers=_key()
    )
    assert problem(taken) == (409, "asset_booking_taken")
    listed = (await world.call("GET", f"{BASE}/my-bookings", a, a.requester)).json()
    assert [b["id"] for b in listed["bookings"]] == [made.json()["id"]]
    assert listed["assets"][projector["id"]] == projector["tag"]
    # Someone else's booking is not mine to cancel; mine is.
    foreign = await world.call(
        "POST", f"{BASE}/my-bookings/{made.json()['id']}/cancel", a, a.requester2,
        headers=_match(made.json()["version"]),
    )  # fmt: skip
    assert problem(foreign) == (404, "asset_booking_not_found")
    cancelled = await world.call(
        "POST", f"{BASE}/my-bookings/{made.json()['id']}/cancel", a, a.requester,
        headers=_match(made.json()["version"]),
    )  # fmt: skip
    assert cancelled.json()["status"] == "cancelled"
    # Staff cancel any booking, with If-Match.
    staff = (await _book(world, projector, _day(5), _day(5, 17))).json()
    stale = await world.call(
        "POST", f"{BASE}/bookings/{staff['id']}/cancel", a, a.admin, headers=_match(0)
    )
    assert problem(stale) == (409, "version_conflict")


async def test_a_booking_refreshes_the_calendar_the_asset_and_the_booker_live(
    world: World,
) -> None:
    a = world.a
    projector = await _projector(world, "Live projector")
    booking = (await _book(world, projector, _day(2), _day(2, 17))).json()
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'assets.booking.changed' ORDER BY created_at DESC LIMIT 1",
        a.tenant,
    )
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    route = next(r for r in ROUTES if envelope.event_type in r.event_types)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(envelope, session)
    asset_id = uuid.UUID(projector["id"])
    assert {(p.channel, p.type, p.ids) for p in effects.publications} == {
        (broadcast(a.tenant), BOOKINGS_CHANGED, (booking["id"], projector["id"])),
        (record(a.tenant, "asset", asset_id), ASSET_CHANGED, (projector["id"],)),
        (personal(a.tenant, a.requester), MINE_CHANGED, (booking["id"],)),
    }


async def test_bookings_are_isolated_by_rls(world: World) -> None:
    b = world.b
    projector = await _projector(world, "RLS projector")
    assert (await _book(world, projector, _day(2), _day(2, 17))).status_code == 201
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await session.scalar(text("SELECT count(*) FROM asset_bookings")) == 0
        changed = await session.execute(text("UPDATE asset_bookings SET comment = 'x'"))
        assert changed.rowcount == 0
    assert (await world.call("GET", f"{BASE}/bookings", b, b.admin)).json() == []
    other = await world.call(
        "POST", f"{BASE}/bookings", b, b.admin,
        json={"asset_id": projector["id"], "borrower_id": str(b.requester),
              "starts_at": _day(3).isoformat(), "ends_at": _day(3, 17).isoformat()},
        headers=_key(),
    )  # fmt: skip
    assert problem(other) == (404, "asset_not_found")


# --- REQ-AST-030's leftovers: display ID, department, site, the register's filters ---------


async def _loan_at(
    world: World,
    org: Org,
    name: str,
    *,
    site: uuid.UUID | None,
    **extra: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    asset = await _projector(world, name)
    made = await world.call(
        "POST", f"{BASE}/loans", org, org.admin,
        json={
            "borrower_id": str(org.requester),
            "asset_ids": [asset["id"]],
            "due_at": _day(7).isoformat(),
            "site_id": None if site is None else str(site),
            **extra,
        },
        headers=_key(),
    )  # fmt: skip
    assert made.status_code == 201, made.text
    return dict(made.json())


async def test_030_loans_have_display_ids_a_site_and_may_go_to_a_department(world: World) -> None:
    a = world.a
    first = await _loan_at(world, a, "Loan ID one", site=a.s1)
    second = await _loan_at(world, a, "Loan ID two", site=a.s2)
    assert first["display_id"].startswith("LN-")
    assert int(second["display_id"][3:]) == int(first["display_id"][3:]) + 1
    assert (first["site_id"], second["site_id"]) == (str(a.s1), str(a.s2))
    department = await world.call(
        "POST", "/organization/departments", a, a.admin, json={"name": "Loans training"}
    )
    lent = await _loan_at(
        world, a, "Department loan", site=None, department_id=department.json()["id"]
    )
    assert (lent["department_id"], lent["borrower_id"]) == (
        department.json()["id"],
        str(a.requester),
    )
    held = (await world.call("GET", f"{BASE}/{lent['assets'][0]['id']}", a, a.admin)).json()
    assert (held["department_id"], held["owner_user_id"]) == (department.json()["id"], None)
    unknown = await world.call(
        "POST", f"{BASE}/loans", a, a.admin,
        json={"borrower_id": str(a.requester), "asset_ids": [lent["assets"][0]["id"]],
              "due_at": _day(7).isoformat(), "department_id": str(uuid.uuid4()),
              "site_id": str(uuid.uuid4())},
        headers=_key(),
    )  # fmt: skip
    assert field_codes(unknown) == {
        "department_id": "asset_holder_not_found",
        "site_id": "site_not_found",
    }


async def test_030_the_register_filters_by_status_and_site(world: World) -> None:
    a = world.a
    at_one = await _loan_at(world, a, "Filter one", site=a.s1)
    at_two = await _loan_at(world, a, "Filter two", site=a.s2)
    late = await _loan_at(world, a, "Filter late", site=a.s1)
    await world.sql(
        "UPDATE asset_loans SET due_at = now() - interval '1 hour', starts_at = now() - interval"
        " '2 days' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(late["id"]),
    )
    back = await world.call(
        "POST", f"{BASE}/loans/{at_two['id']}/returns", a, a.admin,
        json={"asset_ids": [at_two["assets"][0]["id"]]},
    )  # fmt: skip
    assert back.json()["status"] == "closed"

    async def ids(query: str) -> set[str]:
        found = await world.call("GET", f"{BASE}/loans{query}", a, a.tech_a)
        assert found.status_code == 200, found.text
        return {x["id"] for x in found.json()}

    assert {at_one["id"], late["id"]} <= await ids("")
    assert at_two["id"] not in await ids("")
    assert at_one["id"] in await ids("?status=open")
    assert late["id"] not in await ids("?status=open")
    assert late["id"] in await ids("?status=overdue")
    assert at_one["id"] not in await ids("?status=overdue")
    assert at_two["id"] in await ids("?status=closed")
    assert await ids(f"?site_id={a.s1}") >= {at_one["id"], late["id"]}
    assert at_two["id"] not in await ids(f"?status=closed&site_id={a.s1}")
    assert (await world.call("GET", f"{BASE}/loans?status=lost", a, a.tech_a)).status_code == 422
