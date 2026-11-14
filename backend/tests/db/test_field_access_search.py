"""Search never finds a value someone may not see (ADR-047 §6; slice b2).

A restricted custom field stays out of the search text; while a type's search text is rebuilt,
search ignores custom text for everyone (fails closed); the rebuild then clears the mark.
"""

import json
import uuid
from datetime import UTC, datetime

import pytest

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


async def test_live_signals_and_conflicts_name_a_restricted_field_only_as_restricted(
    world: World,  # noqa: F811
) -> None:
    """ADR-047 §7: shared channels and 409s say "restricted", never the field's name."""
    from app.modules.work_items.service import realtime  # noqa: PLC0415 - one test

    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Salary"}},
        headers=CONSOLE,
    )
    key = made.json()["key"]
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={key: "B7"})
    await _restrict(world, a, f"custom.{key}")
    changed = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        json={"custom": {key: "C9"}},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    stale = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        json={"subject": "Again"},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert stale.status_code == 409, stale.text
    named = stale.json()["params"]["changed_fields"].split(",")
    assert "restricted" in named
    assert f"custom.{key}" not in named
    (row,) = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'work_items.work_item.updated' AND aggregate_id = $2"
        " ORDER BY created_at DESC LIMIT 1",
        a.tenant,
        item["id"],
    )
    envelope = EventEnvelope.model_validate(json.loads(row["envelope"]))
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await realtime._work_item_changed(envelope, session)  # noqa: SLF001 - the route
    staff = [p for p in effects.publications if "portal" not in str(p.channel)]
    assert staff
    for publication in staff:
        assert f"custom.{key}" not in publication.fields


async def test_a_rule_cannot_name_a_field_its_author_may_not_see(world: World) -> None:  # noqa: F811
    """ADR-047 §8: checked on the server when the rule is saved (422 field_not_permitted)."""
    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Salary"}},
        headers=CONSOLE,
    )
    key = made.json()["key"]
    (role,) = await world.sql(
        "SELECT id FROM roles WHERE tenant_id = $1 AND key = 'tenant_admin'", a.tenant
    )
    await world.sql(
        "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
        " VALUES (gen_random_uuid(), $1, $2, 'incident', $3, 'masked')",
        a.tenant,
        role["id"],
        f"custom.{key}",
    )
    await world.app.state.policy.invalidate(a.tenant)
    body = {
        "record_type": "incident",
        "name": "Copies the salary",
        "events": ["create"],
        "conditions": {"field": f"custom.{key}", "op": "eq", "value": "B7"},
        "actions": [{"kind": "set", "field": "urgency", "value": "high", "mode": "fill_empty"}],
    }
    refused = await world.call("POST", "/automation/rules", a, a.admin, json=body)
    assert refused.status_code == 422, refused.text
    assert [e["code"] for e in refused.json()["errors"]] == ["field_not_permitted"]
    # The same rule on a field the author sees in clear is fine.
    body["conditions"] = {"field": "urgency", "op": "eq", "value": "high"}
    body["name"] = "Fine"
    assert (await world.call("POST", "/automation/rules", a, a.admin, json=body)).status_code == 201


async def test_a_restricted_value_never_reaches_the_ai_gateway(world: World) -> None:  # noqa: F811
    """ADR-047 §10: what AI reads of a record (its conversation and its embedding texts)
    carries no restricted field's value."""
    from app.modules.work_items.service import ai_sources  # noqa: PLC0415 - one test

    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Codename"}},
        headers=CONSOLE,
    )
    key = made.json()["key"]
    item = await world.create(
        a, a.admin, group_id=str(a.ga), subject="Printer jam", custom={key: "Zebra42"}
    )
    await _restrict(world, a, f"custom.{key}")
    subject = await world.app.state.policy.subject(a.tenant, a.admin)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        talk = await ai_sources.conversation_for(
            session, subject, uuid.UUID(item["id"]), {"replies", "public_notes", "private_notes"}
        )
        texts = await ai_sources.incident_texts(session, [uuid.UUID(item["id"])])
    assert "Zebra42" not in repr(talk)
    assert "Zebra42" not in repr(texts)
    assert "Printer" in repr(texts)  # the record's own text is there


async def test_search_finds_nothing_the_moment_the_rule_commits(world: World) -> None:  # noqa: F811
    """Lane B's #509 review: the mark commits with the rule (an in-transaction listener), so no
    consumer has to run first for search to fail closed."""
    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Codename"}},
        headers=CONSOLE,
    )
    key = made.json()["key"]
    item = await world.create(
        a, a.admin, group_id=str(a.ga), subject="Scanner offline", custom={key: "Quokka55"}
    )
    assert item["id"] in await _found(world, a, a.admin, "Quokka55")
    (role,) = await world.sql(
        "SELECT id FROM roles WHERE tenant_id = $1 AND key = 'technician'", a.tenant
    )
    added = await world.call(
        "POST",
        "/field-access/rules",
        a,
        a.admin,
        json={
            "role_id": str(role["id"]),
            "record_type": "incident",
            "field": f"custom.{key}",
            "mode": "hidden",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert added.status_code == 201, added.text
    # No consumer and no rebuild have run: the rule's own transaction set the mark.
    assert await _found(world, a, a.admin, "Quokka55") == []
    assert item["id"] in await _found(world, a, a.admin, "Scanner")


async def test_a_rebuild_with_a_time_budget_goes_on_where_it_stopped(
    world: World,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lane B's #509 note: a big type is rebuilt over several ticks, search closed throughout."""
    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Codename"}},
        headers=CONSOLE,
    )
    key = made.json()["key"]
    for word in ("Ibis1", "Ibis2", "Ibis3"):
        await world.create(a, a.admin, group_id=str(a.ga), custom={key: word})
    await _restrict(world, a, f"custom.{key}")
    monkeypatch.setattr(search_rebuild, "PAGE", 1)
    database = world.app.state.db
    calls = 0
    while not await search_rebuild.rebuild(database, a.tenant, INCIDENT, budget_seconds=0):
        calls += 1
        assert calls < 50, "the pass never finished"
        assert await _found(world, a, a.admin, "Ibis1") == []  # closed between ticks too
    assert calls >= 2
    rows = await world.sql(
        "SELECT custom_text FROM work_items WHERE tenant_id = $1 AND type = 'incident'", a.tenant
    )
    assert not any("Ibis" in json.dumps(r["custom_text"]) for r in rows)


async def test_a_failing_listener_fails_the_rule_change(
    world: World,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lane B's #509 review: the mark and the rule commit together or not at all."""
    from app.modules.identity_access.domain.field_access import FieldMode  # noqa: PLC0415
    from app.modules.identity_access.service import field_access  # noqa: PLC0415 - one test

    async def boom(*_: object) -> None:
        msg = "listener failed"
        raise RuntimeError(msg)

    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Codename"}},
        headers=CONSOLE,
    )
    key = made.json()["key"]
    (role,) = await world.sql(
        "SELECT id FROM roles WHERE tenant_id = $1 AND key = 'technician'", a.tenant
    )
    monkeypatch.setattr(field_access, "_LISTENERS", [boom])
    subject = await world.app.state.policy.subject(a.tenant, a.admin)
    with pytest.raises(RuntimeError, match="listener failed"):
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            await field_access.set_rule(
                session,
                subject,
                role_id=role["id"],
                record_type="incident",
                field_key=f"custom.{key}",
                mode=FieldMode.HIDDEN,
            )
    assert (
        await world.sql(
            "SELECT 1 FROM role_field_access WHERE tenant_id = $1 AND field = $2",
            a.tenant,
            f"custom.{key}",
        )
        == []
    )
