"""Assets' erasure ports (ADR-052 §4; the coordinator, 2026-11-16) against a real database.

Tech A is the person: they hold an asset, have one on loan, two bookings (one future, one
past), an auditor seat on an open audit and on a closed one. Tech B books too (untouched).
Open holdings stay; future bookings and open-audit seats go; the asset team is told once.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.assets.service.person_data import OWNED, REFERENCES
from app.modules.identity_access import ErasureBatch, PersonData
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_asset_audits_api import _plan
from tests.db.test_asset_bookings_api import _book, _day, _projector
from tests.db.test_asset_holders_api import _asset, _hold
from tests.db.test_asset_loans_api import _loan, _loanable
from tests.db.test_incidents_api import Org, World
from tests.db.test_person_erasure_api import _request

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

NOW = datetime.now(UTC)


async def _run(world: World, org: Org, port: PersonData, person: uuid.UUID) -> dict[str, int]:
    """Every batch of one port for the person, as the job calls it; the counts summed."""
    counts: dict[str, int] = {}
    cursor: str | None = None
    for _ in range(50):
        async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
            batch: ErasureBatch = await port.erase_person(
                session,
                person,
                successor_id=org.tech_c,
                keep_files={},
                now=datetime.now(UTC),
                cursor=cursor,
            )
        for kind, count in batch.counts.items():
            counts[kind] = counts.get(kind, 0) + count
        if batch.cursor is None:
            return counts
        cursor = batch.cursor
    msg = "the port never finished"
    raise AssertionError(msg)


async def _status(world: World, table: str, row_id: str) -> Any:  # noqa: ANN401 - a column value
    rows = await world.sql(f"SELECT status FROM {table} WHERE id = $1", uuid.UUID(row_id))  # noqa: S608 - fixed names
    return rows[0]["status"]


async def test_assets_erasure_keeps_what_they_hold_and_clears_what_points_ahead(  # noqa: PLR0915 - one run, every promise checked
    world: World,
) -> None:
    a, b = world.a, world.b
    person = a.tech_a
    held = await _asset(world, f"Erased holder laptop {uuid.uuid4().hex[:6]}")
    given = await _hold(world, held, "user", person)
    assert given.status_code == 200, given.text
    lent = await _asset(world, f"Erased loan projector {uuid.uuid4().hex[:6]}")
    await _loanable(world, lent)
    loan = await _loan(world, [lent], person)
    assert loan.status_code == 201, loan.text
    booked = await _projector(world, f"Erased booking screen {uuid.uuid4().hex[:6]}")
    future = await _book(world, booked, _day(5), _day(6), borrower=person)
    assert future.status_code == 201, future.text
    past = await _book(world, booked, _day(8), _day(9), borrower=person)
    assert past.status_code == 201, past.text
    await world.sql(  # moved into the past (superuser, test only): a booking that already ran
        "UPDATE asset_bookings SET starts_at = $2, ends_at = $3 WHERE id = $1",
        uuid.UUID(past.json()["id"]),
        NOW - timedelta(days=3),
        NOW - timedelta(days=2),
    )
    others = await _book(world, booked, _day(11), _day(12), borrower=a.tech_b)
    assert others.status_code == 201, others.text
    open_audit = await _plan(world, a, name="Open count", auditor_ids=[str(person)])
    closed_audit = await _plan(world, a, name="Closed count", auditor_ids=[str(person)])
    await world.sql(
        "UPDATE asset_audits SET state = 'closed', started_at = now(), closed_at = now()"
        " WHERE id = $1",
        uuid.UUID(closed_audit["id"]),
    )

    # Before approval: the approver sees what stays with the person (counts only).
    asked = await _request(world, a, a.admin, person)
    assert asked.status_code == 201, asked.text
    shown = await world.call("GET", f"/erasures/{asked.json()['id']}", a, a.admin)
    assert shown.status_code == 200, shown.text
    # A loan hands the asset over too (loans.set_holder): two held, one of them on loan.
    assert shown.json()["holdings"] == {"asset_assignments_open": 2, "asset_loans_open": 1}
    assert held["name"] not in shown.text  # never which assets

    references = await _run(world, a, REFERENCES, person)
    assert references == {"audit_seats_removed": 1, "bookings_cancelled": 1}
    owned = await _run(world, a, OWNED, person)
    assert owned == {"holder_notices_sent": 1}

    # Held and lent stay as they are: nothing invented.
    holder = await world.sql(
        "SELECT owner_user_id FROM assets WHERE id = $1", uuid.UUID(held["id"])
    )
    assert holder[0]["owner_user_id"] == person
    still_open = await world.sql(
        "SELECT count(*) AS n FROM asset_assignments WHERE asset_id = $1 AND ended_at IS NULL",
        uuid.UUID(held["id"]),
    )
    assert still_open[0]["n"] == 1
    loan_open = await world.sql(
        "SELECT closed_at FROM asset_loans WHERE id = $1", uuid.UUID(loan.json()["id"])
    )
    assert loan_open[0]["closed_at"] is None
    # Bookings: theirs ahead cancelled; theirs past and someone else's untouched.
    assert await _status(world, "asset_bookings", future.json()["id"]) == "cancelled"
    assert await _status(world, "asset_bookings", past.json()["id"]) == "booked"
    assert await _status(world, "asset_bookings", others.json()["id"]) == "booked"
    # Audit seats: the open audit's gone, the closed one's kept.
    seats = {
        row["audit_id"]
        for row in await world.sql(
            "SELECT audit_id FROM asset_audit_auditors WHERE user_id = $1", person
        )
    }
    assert uuid.UUID(open_audit["id"]) not in seats
    assert uuid.UUID(closed_audit["id"]) in seats
    # The asset team's notice: once, with the assets' IDs (never a name).
    notices = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'assets.erased_holder.items' AND aggregate_id = $2",
        a.tenant,
        str(person),
    )
    assert len(notices) == 1
    payload = json.loads(notices[0]["envelope"])["payload"]
    assert set(payload["asset_ids"]) == {held["id"], lent["id"]}
    assert (payload["assignments_open"], payload["loans_open"]) == (2, 1)

    # Again: nothing to do, nothing counted, no second notice.
    assert await _run(world, a, REFERENCES, person) == {}
    assert await _run(world, a, OWNED, person) == {}
    again = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'assets.erased_holder.items' AND aggregate_id = $2",
        a.tenant,
        str(person),
    )
    assert again[0]["n"] == 1
    # Another tenant's session reaches none of tenant A's rows.
    assert await _run(world, b, REFERENCES, person) == {}
    assert await _run(world, b, OWNED, person) == {}
