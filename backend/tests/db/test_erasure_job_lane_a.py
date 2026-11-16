"""The whole erasure, as the job runs it, on a record the person requested (lane B's #505
review): no history row of it keeps the requester's original subject or description.

Step 4 (work_items.owned) blanks the current values; step 6 (audit.erase_subject, ADR-046)
blanks the history of the requester's personal fields. Together nothing of their words is left.
"""

import uuid

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, CONSOLE, World
from tests.db.test_person_erasure_job import Effects, _approved, _run

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the incidents fixture, re-used

SUBJECT = "My landlord at 12 Elm Street"
DESCRIPTION = "<p>Call me on 0300 1234567</p>"


async def test_no_history_row_keeps_the_requester_s_words(world: World) -> None:
    a = world.a
    item = await world.create(
        a, a.admin, requester_id=str(a.requester), subject=SUBJECT, description=DESCRIPTION
    )
    edited = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        json={"subject": SUBJECT + " (urgent)"},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert edited.status_code == 200, edited.text
    erasure = await _approved(world, a, a.requester)
    outcome = await _run(world, a, erasure, Effects())
    assert outcome.state == "done", outcome
    rows = await world.sql(
        "SELECT field, old_value::text AS old, new_value::text AS new FROM field_changes"
        " WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    assert any(r["field"] == "subject" for r in rows)  # the edit's history line is there
    kept = [
        r["field"]
        for r in rows
        if any(w in f"{r['old']} {r['new']}" for w in ("Elm Street", "0300 1234567"))
    ]
    assert kept == [], f"history still holds the requester's words in {kept}"
