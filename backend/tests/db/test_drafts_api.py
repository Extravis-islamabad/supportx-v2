"""Kept drafts of unsent create forms (WP-046a S5c; REQ-INC-019) and lane B's conditions.

AC1: what was typed comes back after a reload, with a way to discard it.
AC2: a draft is its author's alone, and goes when the record is saved or the draft discarded.
Sealed (no plain text stored), bound to its row, owner-only (admins too), deleted on
deactivation or erasure and after 30 days; any form key but the known ones refused.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.work_items.service import drafts
from app.shared.events import EventEnvelope
from app.shared.files.keyring import KeyRing
from tests.db.per_test_world import MODULE_LOOP, module_world, shared_world  # has sync tests
from tests.db.test_incidents_api import BASE, CONSOLE, World, problem

__all__ = ["module_world", "shared_world"]  # fixture, re-used

pytestmark = [pytest.mark.db, MODULE_LOOP]

DRAFTS = "/drafts/incident-new"
VALUES = {"subject": "Printer jams on floor 2", "description": "<p>Every page.</p>"}


def with_key_ring(world: World) -> None:
    settings = world.app.state.settings
    # No Valkey: the cipher's data-key cache is one per process and would keep a client bound to
    # an earlier test's event loop; every open then reads the key from the database.
    world.app.state.settings = settings.model_copy(
        update={"files_keys": SecretStr(KeyRing.generate()), "valkey_url": None}
    )


async def keep(world: World, user: uuid.UUID, version: int = 0, **values: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "PUT",
        DRAFTS,
        world.a,
        user,
        json={"values": values or VALUES},
        headers={"If-Match": f'"{version}"'},
    )


async def test_a_draft_comes_back_to_its_author_only_and_is_never_stored_plain(
    world: World,
) -> None:
    with_key_ring(world)
    a, b = world.a, world.b
    kept = await keep(world, a.tech_a)
    assert kept.status_code == 200, kept.text
    assert kept.json()["values"] is None  # a save never sends the values back
    back = await world.call("GET", DRAFTS, a, a.tech_a)
    assert back.status_code == 200, back.text
    assert (back.json()["values"], back.json()["unreadable"]) == (VALUES, False)
    # Nobody else, admins included, in this tenant or another.
    assert problem(await world.call("GET", DRAFTS, a, a.admin)) == (404, "draft_not_found")
    assert problem(await world.call("GET", DRAFTS, a, a.lead)) == (404, "draft_not_found")
    assert (await world.call("GET", DRAFTS, b, b.admin)).status_code == 404
    (row,) = await world.sql(
        "SELECT body FROM work_item_drafts WHERE tenant_id = $1 AND owner_id = $2",
        a.tenant,
        a.tech_a,
    )
    assert "Printer" not in row["body"]
    assert "floor" not in row["body"]
    # Saved again: If-Match on the version, the newer values kept.
    assert problem(await keep(world, a.tech_a, 0)) == (409, "version_conflict")
    again = await keep(world, a.tech_a, 1, subject="Printer jams everywhere")
    assert again.json()["version"] == 2
    assert (await world.call("GET", DRAFTS, a, a.tech_a)).json()["values"] == {
        "subject": "Printer jams everywhere"
    }


async def test_only_known_forms_and_plain_values_are_kept(world: World) -> None:
    with_key_ring(world)
    a = world.a
    other = await world.call(
        "PUT", "/drafts/made-up", a, a.tech_a, json={"values": VALUES}, headers={"If-Match": '"0"'}
    )
    assert other.status_code == 422
    files = await keep(world, a.tech_a, attachment_ids=["x"])
    assert files.status_code == 422
    big = await keep(world, a.tech_a, description="x" * (70 * 1024))
    assert big.status_code == 422
    assert await world.sql("SELECT 1 FROM work_item_drafts WHERE tenant_id = $1", a.tenant) == []


async def test_without_the_installation_key_nothing_is_kept(world: World) -> None:
    refused = await keep(world, world.a.tech_a)
    assert problem(refused) == (503, "field_keys_unavailable")


async def test_saving_the_incident_takes_away_the_senders_own_draft_only(world: World) -> None:
    with_key_ring(world)
    a = world.a
    assert (await keep(world, a.tech_a)).status_code == 200
    assert (await keep(world, a.tech_b)).status_code == 200
    made = await world.call(
        "POST",
        BASE,
        a,
        a.tech_a,
        json={
            "subject": "Printer jams on floor 2",
            "requester_id": str(a.requester),
            "draft_form_key": "incident-new",
        },
        headers={**CONSOLE, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert made.status_code == 201, made.text
    assert (await world.call("GET", DRAFTS, a, a.tech_a)).status_code == 404
    assert (await world.call("GET", DRAFTS, a, a.tech_b)).status_code == 200  # theirs stays


async def test_a_draft_that_does_not_open_comes_back_unreadable(world: World) -> None:
    with_key_ring(world)
    a = world.a
    assert (await keep(world, a.tech_a)).status_code == 200
    assert (await keep(world, a.tech_b)).status_code == 200
    # One draft's sealed body under the other's row: bound to its own row, it does not open.
    await world.sql(
        "UPDATE work_item_drafts SET body = (SELECT body FROM work_item_drafts"
        " WHERE tenant_id = $1 AND owner_id = $2) WHERE tenant_id = $1 AND owner_id = $3",
        a.tenant,
        a.tech_b,
        a.tech_a,
    )
    back = await world.call("GET", DRAFTS, a, a.tech_a)
    assert (back.status_code, back.json()["unreadable"], back.json()["values"]) == (
        200,
        True,
        None,
    )
    gone = await world.call("DELETE", DRAFTS, a, a.tech_a)
    assert gone.status_code == 204
    assert (await world.call("GET", DRAFTS, a, a.tech_a)).status_code == 404


async def test_a_deactivated_person_and_an_old_draft_are_forgotten(world: World) -> None:
    with_key_ring(world)
    a = world.a
    assert (await keep(world, a.tech_a)).status_code == 200
    assert (await keep(world, a.tech_b)).status_code == 200
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        envelope = EventEnvelope.model_validate(
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "identity_access.user.status_changed",
                "schema_version": 1,
                "tenant_id": str(a.tenant),
                "aggregate_type": "user",
                "aggregate_id": str(a.tech_a),
                "aggregate_version": 1,
                "occurred_at": datetime.now(UTC).isoformat(),
                "actor": {"type": "system", "id": "test"},
                "payload": {"user_id": str(a.tech_a), "status": "disabled", "reason": "erasure"},
            }
        )
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            await drafts.on_user_status_changed(envelope, session)
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            assert await drafts.purge_old(session, datetime.now(UTC)) == 0
            later = datetime.now(UTC) + timedelta(days=31)
            assert await drafts.purge_old(session, later) == 1
    finally:
        await database.dispose()
    assert await world.sql("SELECT 1 FROM work_item_drafts WHERE tenant_id = $1", a.tenant) == []


async def test_the_signal_names_the_form_and_version_only(world: World) -> None:
    with_key_ring(world)
    a = world.a
    assert (await keep(world, a.tech_a)).status_code == 200
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'work_items.draft.changed'",
        a.tenant,
    )
    payload = json.loads(rows[-1]["envelope"])["payload"]
    assert payload == {"owner_id": str(a.tech_a), "form_key": "incident-new", "version": 1}
