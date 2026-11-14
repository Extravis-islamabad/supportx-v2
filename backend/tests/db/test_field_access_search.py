"""Search never finds a value someone may not see (ADR-047 §6; slice b2).

A restricted custom field stays out of the search text; while a type's search text is rebuilt,
search ignores custom text for everyone (fails closed); the rebuild then clears the mark.
"""

import json
import uuid
from datetime import UTC, datetime

from app.core.tenancy import TenantContext
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.service import search_rebuild
from app.shared.events import EventEnvelope
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, world  # noqa: F401 - fixture


async def _found(world: World, org: Org, user: uuid.UUID, words: str) -> list[str]:  # noqa: F811
    hits = await world.call("GET", f"{BASE}/search", org, user, params={"q": words})
    assert hits.status_code == 200, hits.text
    return [r["id"] for r in hits.json()["items"]]


async def _restrict(world: World, org: Org, field: str) -> None:  # noqa: F811
    """A rule on a custom field, then the event's consumer as the worker would run it."""
    (role,) = await world.sql(
        "SELECT id FROM roles WHERE tenant_id = $1 AND key = 'technician'", org.tenant
    )
    await world.sql(
        "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
        " VALUES (gen_random_uuid(), $1, $2, 'incident', $3, 'hidden')",
        org.tenant,
        role["id"],
        field,
    )
    envelope = EventEnvelope.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "identity_access.field_access.changed",
            "schema_version": 1,
            "tenant_id": str(org.tenant),
            "aggregate_type": "role",
            "aggregate_id": str(role["id"]),
            "aggregate_version": 1,
            "occurred_at": datetime.now(UTC).isoformat(),
            "actor": {"type": "system", "id": "test"},
            "payload": {
                "role_id": str(role["id"]),
                "record_type": "incident",
                "field": field,
                "mode": "hidden",
            },
        }
    )
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await search_rebuild.on_field_access_changed(envelope, session)


async def test_a_restricted_value_is_never_found_during_or_after_the_rebuild(
    world: World,  # noqa: F811
) -> None:
    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Codename"}},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    key = made.json()["key"]
    item = await world.create(
        a, a.admin, group_id=str(a.ga), subject="Printer on floor two", custom={key: "Zebra42"}
    )
    assert item["id"] in await _found(world, a, a.admin, "Zebra42")  # no rule yet: findable

    await _restrict(world, a, f"custom.{key}")
    # Marked: the stored search text still holds the word, but search ignores custom text now.
    assert await _found(world, a, a.admin, "Zebra42") == []
    assert item["id"] in await _found(world, a, a.admin, "Printer")  # subject still works

    assert await search_rebuild.rebuild(world.app.state.db, a.tenant, INCIDENT) is True
    (row,) = await world.sql(
        "SELECT custom_text FROM work_items WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    assert "Zebra42" not in json.dumps(row["custom_text"])
    (mark,) = await world.sql(
        "SELECT custom_text_rebuilding_since FROM work_item_type_settings"
        " WHERE tenant_id = $1 AND type = 'incident'",
        a.tenant,
    )
    assert mark["custom_text_rebuilding_since"] is None
    assert await _found(world, a, a.admin, "Zebra42") == []  # rebuilt: still never found
    # A record saved after the rule keeps the value out of its search text from the start.
    later = await world.create(a, a.admin, group_id=str(a.ga), custom={key: "Okapi7"})
    assert later["id"] not in await _found(world, a, a.admin, "Okapi7")
