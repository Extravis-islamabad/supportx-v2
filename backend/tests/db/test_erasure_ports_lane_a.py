"""Lane A's erasure ports (ADR-052 §4; 0166): each owner proves its port (ADR-052's rules).

Erase, a second call changes nothing and counts zero, other people untouched, another tenant
untouched. The ports are run as the job runs them: cursor after cursor until None.
"""

import uuid
from collections import Counter
from datetime import UTC, datetime

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.identity_access import PersonData
from app.modules.work_items.service.person_data import OWNED, REFERENCES
from app.shared.erasure import ERASED_ON_REQUEST
from tests.db.test_incidents_api import BASE, CONSOLE, World, world  # noqa: F401 - the fixture


async def _erase(
    world: World,  # noqa: F811 - the fixture's name
    tenant: uuid.UUID,
    person: uuid.UUID,
    port: PersonData,
) -> Counter[str]:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    counts: Counter[str] = Counter()
    try:
        cursor: str | None = None
        for _ in range(100):  # a bounded loop: a port that never ends is a defect
            async with database.tenant_session(TenantContext(tenant)) as session:
                batch = await port.erase_person(
                    session,
                    person,
                    successor_id=world.a.admin,
                    keep_files={},
                    now=datetime.now(UTC),
                    cursor=cursor,
                )
            assert set(batch.counts) <= port.kinds, batch.counts  # declared kinds only
            counts.update(batch.counts)
            cursor = batch.cursor
            if cursor is None:
                return counts
        msg = "the port never finished"
        raise AssertionError(msg)
    finally:
        await database.dispose()


async def test_the_requester_s_text_goes_and_the_records_stay(world: World) -> None:  # noqa: F811
    a = world.a
    theirs = await world.create(
        a, a.admin, requester_id=str(a.requester), description="<p>My home address is 1 Elm St</p>"
    )
    other = await world.create(a, a.admin, requester_id=str(a.tech_b), description="<p>Keep</p>")
    counts = await _erase(world, a.tenant, a.requester, OWNED)
    assert counts["requests_blanked"] == 1
    (row,) = await world.sql(
        "SELECT subject, description, deleted_at FROM work_items WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(theirs["id"]),
    )
    assert (row["subject"], row["description"], row["deleted_at"]) == (
        ERASED_ON_REQUEST,
        None,
        None,
    )
    (kept,) = await world.sql(
        "SELECT description FROM work_items WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(other["id"]),
    )
    assert "Keep" in kept["description"]
    # Idempotent: a second full run changes nothing and counts zero.
    assert sum((await _erase(world, a.tenant, a.requester, OWNED)).values()) == 0


async def test_an_open_record_assigned_to_them_goes_back_to_the_group(world: World) -> None:  # noqa: F811
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    counts = await _erase(world, a.tenant, a.tech_a, OWNED)
    assert counts["records_unassigned"] == 1
    (row,) = await world.sql(
        "SELECT technician_id, group_id FROM work_items WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    assert row["technician_id"] is None
    assert row["group_id"] == a.ga


async def test_their_follows_and_address_come_off_others_records(world: World) -> None:  # noqa: F811
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    followed = await world.call(
        "PUT", f"{BASE}/{item['id']}/followers/{a.tech_a}", a, a.admin, headers=CONSOLE
    )
    assert followed.status_code in {200, 201, 204}, followed.text
    (person,) = await world.sql(
        "SELECT email FROM users WHERE tenant_id = $1 AND id = $2", a.tenant, a.tech_a
    )
    await world.sql(
        "UPDATE work_items SET notify_emails = ARRAY[$3::text, 'someone@else.test']"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
        person["email"],
    )
    counts = await _erase(world, a.tenant, a.tech_a, REFERENCES)
    assert counts["followers_removed"] == 1
    assert counts["notify_addresses_removed"] == 1
    (row,) = await world.sql(
        "SELECT notify_emails FROM work_items WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    assert row["notify_emails"] == ["someone@else.test"]
    assert (
        await world.sql(
            "SELECT 1 FROM work_item_followers WHERE tenant_id = $1 AND user_id = $2",
            a.tenant,
            a.tech_a,
        )
        == []
    )
    assert sum((await _erase(world, a.tenant, a.tech_a, REFERENCES)).values()) == 0


async def test_another_tenant_is_untouched(world: World) -> None:  # noqa: F811
    a, b = world.a, world.b
    mine = await world.create(b, b.admin, requester_id=str(b.requester), description="<p>B</p>")
    # Erasing tenant A's requester inside tenant A's session cannot reach tenant B's records.
    await _erase(world, a.tenant, b.requester, OWNED)
    (row,) = await world.sql(
        "SELECT description FROM work_items WHERE tenant_id = $1 AND id = $2",
        b.tenant,
        uuid.UUID(mine["id"]),
    )
    assert "B" in row["description"]


async def test_in_progress_tasks_are_unassigned_too(world: World) -> None:  # noqa: F811
    """Lane B's #505 review: open and in progress, never only "open"."""
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    for title in ("Open", "Started"):
        made = await world.call(
            "POST",
            f"{BASE}/{item['id']}/tasks",
            a,
            a.admin,
            json={"title": title, "owner_id": str(a.tech_a)},
            headers=CONSOLE,
        )
        assert made.status_code == 201, made.text
    await world.sql(
        "UPDATE work_item_tasks SET status = 'in_progress'"
        " WHERE tenant_id = $1 AND work_item_id = $2 AND title = 'Started'",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    counts = await _erase(world, a.tenant, a.tech_a, REFERENCES)
    assert counts["tasks_unassigned"] == 2
    assert (
        await world.sql(
            "SELECT 1 FROM work_item_tasks WHERE tenant_id = $1 AND owner_id = $2",
            a.tenant,
            a.tech_a,
        )
        == []
    )


async def test_a_personal_data_field_of_any_type_is_blanked(world: World) -> None:  # noqa: F811
    """Lane B's #505 review: a date marked personal data goes, not only free text."""
    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "date", "labels": {"en": "Date of birth"}},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    key = made.json()["key"]
    await world.sql(
        "UPDATE custom_fields SET personal_data = true WHERE tenant_id = $1 AND key = $2",
        a.tenant,
        key,
    )
    item = await world.create(a, a.admin, requester_id=str(a.requester), custom={key: "1990-04-01"})
    await _erase(world, a.tenant, a.requester, OWNED)
    (row,) = await world.sql(
        "SELECT custom FROM work_items WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    assert "1990-04-01" not in str(row["custom"])
