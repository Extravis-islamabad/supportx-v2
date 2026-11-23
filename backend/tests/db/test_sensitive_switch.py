"""Turning `sensitive` on and off, and the re-seal job (WP-057 S3b-2b; lane B's conditions).

- On: the field leaves search at the switch's commit; the job seals values batch by batch,
  reads stay right while some are sealed and some are not, and the end is audited.
- Off: a recent sign-in, a reason and the field's name; values open back, index rows go.
- The job never overwrites a value changed since it read it; a key outage pauses it with the
  state unchanged and tells the admins once; a lapsed licence never stops sealing.
- Tenant A's job never touches tenant B.
"""

import json
import uuid
from typing import Any

import pytest
from fastapi import Request
from pydantic import SecretStr

from app.core.recent_auth import SignInFreshness, record_freshness
from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.modules import metadata
from app.modules.work_items.service import custom_values, sealing_job
from app.shared.fields import FieldKeysUnavailable
from app.shared.files.keyring import KeyRing
from app.shared.files.service.core import rewrap_data_keys
from tests.db.test_access_api import fake_session
from tests.db.test_field_access_reads import _custom_field
from tests.db.test_field_access_search import _found
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, world  # noqa: F401 - fixture

pytestmark = pytest.mark.db

FIELDS = "/custom-fields"


def _with_keys(w: World) -> None:
    settings = w.app.state.settings.model_copy(
        update={"files_keys": SecretStr(KeyRing.generate()), "valkey_url": None}
    )
    w.app.state.settings = settings
    w.app.state.db.settings = settings


async def _field_id(w: World, org: Org, key: str, entity: str = "incident") -> str:
    (row,) = await w.sql(
        "SELECT id FROM custom_fields WHERE tenant_id = $1 AND key = $2 AND entity = $3",
        org.tenant,
        key,
        entity,
    )
    return str(row["id"])


async def _switch(w: World, org: Org, key: str, **body: Any) -> Any:  # noqa: ANN401 - a response
    field_id = await _field_id(w, org, key)
    current = await w.call("GET", f"{FIELDS}/{field_id}/sensitivity", org, org.admin)
    assert current.status_code == 200, current.text
    return await w.call(
        "PUT",
        f"{FIELDS}/{field_id}/sensitivity",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{current.json()["version"]}"', **CONSOLE},
    )


async def _state(w: World, org: Org, key: str) -> tuple[str, bool]:
    (row,) = await w.sql(
        "SELECT seal_state, sensitive FROM custom_fields WHERE tenant_id = $1 AND key = $2"
        " AND entity = 'incident'",
        org.tenant,
        key,
    )
    return row["seal_state"], row["sensitive"]


async def _stored(w: World, org: Org, key: str) -> list[str]:
    rows = await w.sql(
        "SELECT custom->>$2 AS v FROM work_items WHERE tenant_id = $1 AND custom ? $2 ORDER BY id",
        org.tenant,
        key,
    )
    return [r["v"] for r in rows]


async def _run(w: World, org: Org) -> None:
    await sealing_job.run_tenant(w.app.state.db, org.tenant, w.app.state.settings)


async def _one_batch(w: World, org: Org) -> sealing_job.Batch:
    async with w.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        (field,) = await metadata.fields_being_sealed(session, sealing_job.ENTITIES)
        return await sealing_job.run_batch(session, field, w.app.state.settings)


async def test_turning_on_seals_existing_values_batch_by_batch(
    world: World,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_keys(world)
    monkeypatch.setattr(sealing_job, "BATCH", 2)
    a = world.a
    key = await _custom_field(world, a, "Badge")
    items = [
        await world.create(a, a.admin, group_id=str(a.ga), custom={key: f"Zebra{n}"})
        for n in range(5)
    ]
    assert items[0]["id"] in await _found(world, a, a.admin, "Zebra0")
    switched = await _switch(world, a, key, sensitive=True)
    assert switched.status_code == 200, switched.text
    assert switched.json()["seal_state"] == "sealing"
    assert switched.json()["records"] == 5
    # Search stops finding its words at the switch's commit (lane B).
    assert await _found(world, a, a.admin, "Zebra0") == []
    # One batch: some sealed, some not; every reader still sees the values (the coordinator).
    first = await _one_batch(world, a)
    assert (first.moved, first.finished) == (2, False)
    stored = await _stored(world, a, key)
    assert sum(v.startswith("sx2:") for v in stored) == 2
    listed = await world.call("GET", BASE, a, a.admin)
    shown = {r["id"]: r["custom"].get(key) for r in listed.json()["items"]}
    assert {shown[i["id"]] for i in items} == {f"Zebra{n}" for n in range(5)}
    assert "sx2:" not in listed.text
    # Filters stay refused in between (lane B).
    # By the POST form, so it reaches the in-between refusal itself: the GET would stop earlier
    # at `sealed_filter_needs_post` (#555; lane C).
    probe = {"field": f"custom.{key}", "op": "eq", "value": "Zebra1"}
    between = await world.call("POST", f"{BASE}/list", a, a.admin, json={"filter": probe})
    assert between.status_code == 422, between.text
    assert "field_not_filterable_sealed" in between.text
    await _run(world, a)
    assert await _state(world, a, key) == ("sealed", True)
    assert all(v.startswith("sx2:") for v in await _stored(world, a, key))
    index = await world.sql(
        "SELECT count(*) AS n FROM work_item_field_index WHERE tenant_id = $1 AND field_key = $2",
        a.tenant,
        key,
    )
    assert index[0]["n"] == 5
    # A sealed filter goes by the POST form, never in a URL (#555).
    hit = {"field": f"custom.{key}", "op": "eq", "value": "zebra3"}
    found = await world.call("POST", f"{BASE}/list", a, a.admin, json={"filter": hit})
    assert [r["id"] for r in found.json()["items"]] == [items[3]["id"]]
    audited = await world.sql(
        "SELECT action AS action_code, details FROM audit_entries WHERE tenant_id = $1"
        " AND action LIKE 'metadata.custom_field_s%' ORDER BY occurred_at",
        a.tenant,
    )
    codes = [r["action_code"] for r in audited]
    assert codes == ["metadata.custom_field_sensitivity_changed", "metadata.custom_field_sealed"]
    assert json.loads(audited[1]["details"])["records"] == 5
    assert "Zebra" not in json.dumps([dict(r) for r in audited], default=str)
    # Its values are in no event, only the state and counts (the coordinator).
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'metadata.custom_field.seal_changed'",
        a.tenant,
    )
    assert len(events) == 2
    assert "Zebra" not in json.dumps([dict(r) for r in events], default=str)


async def test_turning_off_needs_a_reason_and_the_name_then_opens(world: World) -> None:  # noqa: F811
    _with_keys(world)
    a = world.a
    key = await _custom_field(world, a, "Locker")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={key: "L-17"})
    assert (await _switch(world, a, key, sensitive=True)).status_code == 200
    await _run(world, a)
    assert await _state(world, a, key) == ("sealed", True)
    no_reason = await _switch(world, a, key, sensitive=False, confirm_name="Locker")
    assert no_reason.status_code == 422, no_reason.text
    wrong_name = await _switch(
        world, a, key, sensitive=False, reason="Audit done", confirm_name="X"
    )
    assert wrong_name.status_code == 422, wrong_name.text
    assert "confirm_name_mismatch" in wrong_name.text
    off = await _switch(
        world, a, key, sensitive=False, reason="No longer personal", confirm_name="locker "
    )
    assert off.status_code == 200, off.text
    assert off.json()["seal_state"] == "opening"
    # Still out of search while opening: only once plain may it come back (lane B).
    assert await _found(world, a, a.admin, "L-17") == []
    await _run(world, a)
    assert await _state(world, a, key) == ("plain", False)
    assert await _stored(world, a, key) == ["L-17"]
    rows = await world.sql(
        "SELECT count(*) AS n FROM work_item_field_index WHERE tenant_id = $1 AND field_key = $2",
        a.tenant,
        key,
    )
    assert rows[0]["n"] == 0
    shown = await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)
    assert shown.json()["custom"][key] == "L-17"
    # The reason is the audit entry's personal part, never its details (lane B).
    (entry,) = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'metadata.custom_field_sensitivity_changed'"
        " AND details->>'direction' = 'off'",
        a.tenant,
    )
    assert "No longer personal" not in json.dumps(entry["details"])


async def _stale_session(request: Request) -> TenantContext | None:
    tenant, user = request.headers.get("x-test-tenant"), request.headers.get("x-test-user")
    if tenant is None:
        return None
    record_freshness(request, SignInFreshness(interactive=True, recent=False))
    return TenantContext(uuid.UUID(tenant), uuid.UUID(user) if user else None)


async def test_the_switch_needs_a_recent_sign_in(world: World) -> None:  # noqa: F811
    a = world.a
    key = await _custom_field(world, a, "Pin")
    setattr(world.app.state, SESSION_RESOLVER_STATE, _stale_session)
    try:
        refused = await _switch(world, a, key, sensitive=True)
    finally:
        setattr(world.app.state, SESSION_RESOLVER_STATE, fake_session)
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "reauth_required"
    assert await _state(world, a, key) == ("plain", False)


@pytest.mark.parametrize("entity", ["asset", "ci"])
async def test_an_asset_or_ci_field_cannot_be_sensitive(world: World, entity: str) -> None:  # noqa: F811
    """No sealed form exists for asset or CI fields: CI versions rely on it (lane C, #550). A future
    seal port for either must change this test on purpose."""
    a = world.a
    made = await world.call(
        "POST",
        FIELDS,
        a,
        a.admin,
        json={"entity": entity, "field_type": "text", "labels": {"en": "Code"}},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    field_id = await _field_id(world, a, made.json()["key"], entity)
    refused = await world.call("GET", f"{FIELDS}/{field_id}/sensitivity", a, a.admin)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "custom_field_sensitive_unsupported"


async def test_the_job_never_overwrites_a_value_changed_since_it_read_it(
    world: World,  # noqa: F811
) -> None:
    """Lane B (1): compare-and-set on the value the job read."""
    _with_keys(world)
    a = world.a
    key = await _custom_field(world, a, "Desk")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={key: "D1"})
    record = uuid.UUID(item["id"])
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        # Someone changed it to D2 after the job read D1: the stale write is refused.
        assert not await sealing_job._swap(session, record, key, "D0", "sx2:stale")  # noqa: SLF001
        assert await sealing_job._swap(session, record, key, "D1", "D1-moved")  # noqa: SLF001
    assert await _stored(world, a, key) == ["D1-moved"]


async def test_a_key_outage_pauses_with_the_state_unchanged_and_tells_once(
    world: World,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_keys(world)
    a = world.a
    key = await _custom_field(world, a, "Seat")
    await world.create(a, a.admin, group_id=str(a.ga), custom={key: "S9"})
    assert (await _switch(world, a, key, sensitive=True)).status_code == 200
    real = custom_values.seal_custom

    async def no_keys(*_args: object, **_kwargs: object) -> object:  # stands in for seal_custom
        raise FieldKeysUnavailable

    monkeypatch.setattr(custom_values, "seal_custom", no_keys)
    for _ in range(2):
        await sealing_job.seal_schedule(world.app.state.db, world.app.state.settings)
    assert await _state(world, a, key) == ("sealing", True)
    assert await _stored(world, a, key) == ["S9"]
    paused = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'metadata.custom_field.seal_paused'",
        a.tenant,
    )
    assert paused[0]["n"] == 1  # told once, however many ticks fail
    monkeypatch.setattr(custom_values, "seal_custom", real)
    await _run(world, a)
    assert await _state(world, a, key) == ("sealed", True)


async def test_a_lapsed_licence_refuses_on_allows_off_and_never_stops_sealing(
    world: World,  # noqa: F811
) -> None:
    _with_keys(world)
    a = world.a
    key = await _custom_field(world, a, "Grade")
    other = await _custom_field(world, a, "Level")
    await world.create(a, a.admin, group_id=str(a.ga), custom={key: "G1", other: "L1"})
    assert (await _switch(world, a, key, sensitive=True)).status_code == 200
    await world.sql(
        "UPDATE tenant_subscriptions SET edition = 'essentials' WHERE tenant_id = $1", a.tenant
    )
    client = world.app.state.policy.cache.client
    keys = [
        k async for k in client.scan_iter(match=f"{world.app.state.settings.valkey_key_prefix}*")
    ]
    if keys:
        await client.delete(*keys)
    refused = await _switch(world, a, other, sensitive=True)
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "entitlement_required"
    await _run(world, a)  # a field half-sealed is finished all the same (lane B)
    assert await _state(world, a, key) == ("sealed", True)
    off = await _switch(world, a, key, sensitive=False, reason="Lapsed", confirm_name="Grade")
    assert off.status_code == 200, off.text


async def test_one_tenants_job_never_touches_another(world: World) -> None:  # noqa: F811
    _with_keys(world)
    a, b = world.a, world.b
    key_a = await _custom_field(world, a, "Token")
    key_b = await _custom_field(world, b, "Token")
    await world.create(a, a.admin, group_id=str(a.ga), custom={key_a: "A1"})
    await world.create(b, b.admin, group_id=str(b.ga), custom={key_b: "B1"})
    assert (await _switch(world, a, key_a, sensitive=True)).status_code == 200
    assert (await _switch(world, b, key_b, sensitive=True)).status_code == 200
    await _run(world, a)
    assert await _state(world, a, key_a) == ("sealed", True)
    assert await _state(world, b, key_b) == ("sealing", True)
    assert await _stored(world, b, key_b) == ["B1"]


async def test_sealed_values_survive_a_kek_rotation_and_history_stays_verifiable(
    world: World,  # noqa: F811
) -> None:
    """Lane B (7): re-seal, then a new installation key; values and history still open.

    The re-seal job never writes history, so every `field_changes` row is byte-for-byte what it
    was: the change-set fingerprints (ADR-046) still match. The KEK only rewraps data keys.
    """
    _with_keys(world)
    a = world.a
    key = await _custom_field(world, a, "Vault")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={key: "V1"})
    current = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        json={"custom": {key: "V2"}},
        headers={"If-Match": f'"{current["version"]}"'},
    )
    history_query = (
        "SELECT id, old_value, new_value FROM field_changes WHERE tenant_id = $1"
        " AND record_id = $2 ORDER BY id"
    )
    record = uuid.UUID(item["id"])
    before = [dict(r) for r in await world.sql(history_query, a.tenant, record)]
    assert (await _switch(world, a, key, sensitive=True)).status_code == 200
    await _run(world, a)
    assert await _state(world, a, key) == ("sealed", True)
    assert [dict(r) for r in await world.sql(history_query, a.tenant, record)] == before
    # A new installation key: data keys rewrapped, then the old key removed from the ring.
    old = world.app.state.settings.files_keys.get_secret_value()
    both = f"{KeyRing.generate('k2')}, {old}"
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await rewrap_data_keys(session, KeyRing.parse(both)) >= 1
    only_new = both.split(",", maxsplit=1)[0].strip()
    settings = world.app.state.settings.model_copy(update={"files_keys": SecretStr(only_new)})
    world.app.state.settings = settings
    world.app.state.db.settings = settings
    shown = await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)
    assert shown.json()["custom"][key] == "V2"
    assert shown.json()["unreadable_fields"] == []
    found = await world.call(  # by the POST form: a sealed filter never in a URL (#555)
        "POST",
        f"{BASE}/list",
        a,
        a.admin,
        json={"filter": {"field": f"custom.{key}", "op": "eq", "value": "v2"}},
    )
    assert [r["id"] for r in found.json()["items"]] == [item["id"]]
    page = await world.call("GET", f"{BASE}/{item['id']}/history", a, a.admin)
    assert "V1" in page.text
    assert "sx2:" not in page.text
    # Tenants outlive this test: their data keys go back under the test's original ring.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await rewrap_data_keys(session, KeyRing.parse(f"{old}, {only_new}"))


async def test_a_batch_begun_before_a_reversal_writes_nothing(
    world: World,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lane B (#526): the job holds the field row and re-checks its state and cursor."""
    _with_keys(world)
    monkeypatch.setattr(sealing_job, "BATCH", 2)
    a = world.a
    key = await _custom_field(world, a, "Pager")
    for n in range(3):
        await world.create(a, a.admin, group_id=str(a.ga), custom={key: f"P{n}"})
    assert (await _switch(world, a, key, sensitive=True)).status_code == 200
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        (stale,) = await metadata.fields_being_sealed(session, sealing_job.ENTITIES)
    off = await _switch(world, a, key, sensitive=False, reason="Not needed", confirm_name="Pager")
    assert off.status_code == 200, off.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        batch = await sealing_job.run_batch(session, stale, world.app.state.settings)
    assert (batch.moved, batch.finished) == (0, False)
    assert not any(v.startswith("sx2:") for v in await _stored(world, a, key))


async def test_opening_one_types_field_leaves_another_types_index(world: World) -> None:  # noqa: F811
    """Lane B (#526): keys are unique per type, so the last delete is filtered by type.

    An incident field and a problem field share a key. The problem field finishing its
    opening must leave the incident field's blind index alone.
    """
    _with_keys(world)
    a = world.a
    key = await _custom_field(world, a, "Badge")
    made = await world.call(
        "POST",
        FIELDS,
        a,
        a.admin,
        json={"entity": "problem", "field_type": "text", "labels": {"en": "Badge"}},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    assert made.json()["key"] == key
    await world.create(a, a.admin, group_id=str(a.ga), custom={key: "K1"})
    assert (await _switch(world, a, key, sensitive=True)).status_code == 200
    await _run(world, a)
    before = await world.sql(
        "SELECT count(*) AS n FROM work_item_field_index WHERE tenant_id = $1 AND field_key = $2",
        a.tenant,
        key,
    )
    assert before[0]["n"] == 1
    await world.sql(
        "UPDATE custom_fields SET sensitive = false, seal_state = 'opening'"
        " WHERE tenant_id = $1 AND entity = 'problem' AND key = $2",
        a.tenant,
        key,
    )
    await _run(world, a)
    after = await world.sql(
        "SELECT count(*) AS n FROM work_item_field_index WHERE tenant_id = $1 AND field_key = $2",
        a.tenant,
        key,
    )
    assert after[0]["n"] == 1  # the incident field's row is still there


async def test_the_off_reason_stays_out_of_history(world: World) -> None:  # noqa: F811
    """Lane B (#526): personal data, kept only where erasure reaches it."""
    _with_keys(world)
    a = world.a
    key = await _custom_field(world, a, "Shift")
    assert (await _switch(world, a, key, sensitive=True)).status_code == 200
    await _run(world, a)
    reason = "Agreed with HR on the 12th"
    off = await _switch(world, a, key, sensitive=False, reason=reason, confirm_name="Shift")
    assert off.status_code == 200, off.text
    rows = await world.sql(
        "SELECT reason, old_value, new_value FROM field_changes WHERE tenant_id = $1"
        " AND record_type = 'custom_field'",
        a.tenant,
    )
    assert reason not in json.dumps([dict(r) for r in rows], default=str)
