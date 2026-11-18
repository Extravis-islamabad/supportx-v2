"""The CMDB's mentions port on real Postgres (ADR-052 S1b, D-171 a; 0176; lane C's conditions).

Tech A is being erased. Other people wrote their name into CIs: a CI's description now, and an
old name a CI no longer has (only its snapshot keeps it). The report lists each place (never the
text); a redaction turns the matched words into the marker:
- the CI through an ordinary save (version, history naming the field only, a new snapshot, the
  `cmdb.ci.updated` event with IDs, fields and version only);
- an old snapshot through 0176's `cmdb_redact_version`, the matched stretch only; an unrelated
  older name stays as it was;
- a CI in the bin is redacted too, but shows no passage.
The definer is bound to an open, redacted `ci_version` mention of the caller's tenant and accepts
only a pure redaction; the app role may never change a snapshot itself.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_api import _ci
from tests.db.test_incidents_api import Org, World
from tests.db.test_person_erasure_api import _name, _request
from tests.db.test_person_erasure_mentions import _build, _get, _mentions

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the incidents fixture, re-used

MARKER = "erased_on_request"


async def _patch(world: World, org: Org, ci: dict[str, Any], **changes: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    done = await world.call(
        "PATCH",
        f"/cmdb/cis/{ci['id']}",
        org,
        org.admin,
        json=changes,
        headers={"If-Match": f'"{ci["version"]}"'},
    )
    assert done.status_code == 200, done.text
    return dict(done.json())


async def _redact(world: World, org: Org, erasure: dict[str, Any], ids: list[str]) -> Any:  # noqa: ANN401 - httpx response
    current = await _get(world, org, erasure)
    return await world.call(
        "POST",
        f"/erasures/{erasure['id']}/mentions/redact",
        org,
        org.admin,
        json={"mention_ids": ids},
        headers={"If-Match": f'"{current["version"]}"'},
    )


def _on(page: dict[str, Any], record_type: str, field: str) -> list[dict[str, Any]]:
    return [
        m
        for m in page["items"]
        if m["module_key"] == "cmdb"
        and m["record_type"] == record_type
        and m["field"] == field
        and m["match_kind"] == "name"
    ]


async def _snapshots(world: World, org: Org, ci_id: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT id, version, snapshot FROM cmdb_ci_versions WHERE tenant_id = $1 AND ci_id = $2"
        " ORDER BY version",
        org.tenant,
        uuid.UUID(ci_id),
    )
    return [{**dict(r), "snapshot": json.loads(r["snapshot"])} for r in rows]


async def test_cis_and_old_snapshots_are_found_and_redacted_in_place(world: World) -> None:  # noqa: PLR0915 - one journey, end to end
    a = world.a
    name = await _name(world, a, a.tech_a)
    # Renamed twice: once for an unrelated reason, then away from the person's name.
    made = await _ci(world, a, "Core switch SW-01", description=f"Racked by {name} in May")
    assert made.status_code == 201, made.text
    ci = dict(made.json())
    ci = await _patch(world, a, ci, name=f"Switch kept by {name}")
    ci = await _patch(world, a, ci, name="Core switch SW-02")
    binned = dict((await _ci(world, a, f"Spare for {name}")).json())
    gone = await world.call(
        "DELETE",
        f"/cmdb/cis/{binned['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{binned["version"]}"'},
    )
    assert gone.status_code in (200, 204), gone.text

    asked = await _request(world, a, a.admin, a.tech_a, successor_id=str(a.lead))
    assert asked.status_code == 201, asked.text
    erasure = dict(asked.json())
    await _build(world, a)
    page = await _mentions(world, a, erasure)
    assert name not in json.dumps(page)  # places, never text

    now_desc = [m for m in _on(page, "ci", "description") if m["record_id"] == ci["id"]]
    assert len(now_desc) == 1
    assert not [m for m in _on(page, "ci", "name") if m["record_id"] == ci["id"]]
    versions = {s["id"]: s for s in await _snapshots(world, a, ci["id"])}
    old_names = [
        m for m in _on(page, "ci_version", "name") if uuid.UUID(m["record_id"]) in versions
    ]
    assert len(old_names) == 1  # only the snapshot that named them
    binned_name = [m for m in _on(page, "ci", "name") if m["record_id"] == binned["id"]]
    assert len(binned_name) == 1

    # The bin keeps its text: shown only to someone who may erase people (0170's rule), never to
    # a technician who merely sees CIs.
    base = f"/erasures/{erasure['id']}/mentions"
    by_eraser = await world.call("GET", f"{base}/{binned_name[0]['id']}/passage", a, a.admin)
    assert by_eraser.status_code == 200, by_eraser.text
    by_tech = await world.call("GET", f"{base}/{binned_name[0]['id']}/passage", a, a.tech_c)
    assert by_tech.status_code in (403, 404), by_tech.text
    assert name not in by_tech.text
    shown = await world.call("GET", f"{base}/{old_names[0]['id']}/passage", a, a.admin)
    assert shown.status_code == 200, shown.text
    assert name in shown.text

    events_before = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'cmdb.ci.updated'",
        a.tenant,
    )
    chosen = [now_desc[0]["id"], old_names[0]["id"], binned_name[0]["id"]]
    done = await _redact(world, a, erasure, chosen)
    assert done.status_code == 200, done.text

    (row,) = await world.sql(
        "SELECT name, description, version FROM cmdb_cis WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(ci["id"]),
    )
    assert row["description"] == f"Racked by {MARKER} in May"
    assert row["name"] == "Core switch SW-02"  # the current name never named them
    after = await _snapshots(world, a, ci["id"])
    by_id = {s["id"]: s for s in after}
    old = by_id[uuid.UUID(old_names[0]["record_id"])]
    assert old["snapshot"]["name"] == f"Switch kept by {MARKER}"  # the stretch only
    first = after[0]
    assert first["snapshot"]["name"] == "Core switch SW-01"  # an unrelated old name stays
    assert after[-1]["snapshot"]["description"] == f"Racked by {MARKER} in May"
    (bin_row,) = await world.sql(
        "SELECT name, deleted_at FROM cmdb_cis WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(binned["id"]),
    )
    assert bin_row["name"] == f"Spare for {MARKER}"
    assert bin_row["deleted_at"] is not None  # still in the bin
    # As any save (lane C): its newest snapshot is the redacted one.
    assert (await _snapshots(world, a, binned["id"]))[-1]["snapshot"][
        "name"
    ] == f"Spare for {MARKER}"

    history = await world.sql(
        "SELECT field, old_value, new_value, reason FROM field_changes WHERE tenant_id = $1"
        " AND record_type = 'ci' AND record_id = $2 AND reason = 'erasure_redaction'",
        a.tenant,
        uuid.UUID(ci["id"]),
    )
    assert [(h["field"], h["old_value"], h["new_value"]) for h in history] == [
        ("description", None, None)
    ]
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'cmdb.ci.updated' ORDER BY id",
        a.tenant,
    )
    assert len(events) >= events_before[0]["n"] + 2  # the CI and the binned CI
    payload = json.loads(events[-1]["envelope"])["payload"]
    assert set(payload) <= {"ci_id", "type_id", "changed_fields", "event_id", "version"}
    assert name not in json.dumps([json.loads(e["envelope"])["payload"] for e in events])

    again = await _redact(world, a, erasure, chosen)  # a second time changes nothing
    assert again.status_code == 200, again.text
    assert await _snapshots(world, a, ci["id"]) == after


async def test_the_snapshot_definer_is_bound_and_takes_only_a_pure_redaction(
    world: World,
) -> None:
    a, b = world.a, world.b
    name = await _name(world, a, a.tech_a)
    ci = dict((await _ci(world, a, f"Printer of {name}")).json())
    ci = await _patch(world, a, ci, name="Printer P-7")
    asked = await _request(world, a, a.admin, a.tech_a, successor_id=str(a.lead))
    erasure = dict(asked.json())
    await _build(world, a)
    (old,) = _on(await _mentions(world, a, erasure), "ci_version", "name")
    call = text("SELECT cmdb_redact_version(:m, :v)")

    # Not redacted yet: nothing is written.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (
            await session.scalar(call, {"m": uuid.UUID(old["id"]), "v": f"Printer of {MARKER}"})
            is False
        )
    # Another tenant's session cannot reach the mention.
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert (
            await session.scalar(call, {"m": uuid.UUID(old["id"]), "v": f"Printer of {MARKER}"})
            is False
        )
    await world.sql(
        "UPDATE person_erasure_mentions SET state = 'redacted', redacted_at = now(),"
        " redacted_by = $3 WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(old["id"]),
        a.admin,
    )
    # Not a pure redaction: refused, nothing written.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        with pytest.raises(DBAPIError, match="marker in place"):
            await session.scalar(call, {"m": uuid.UUID(old["id"]), "v": "Something else"})
    # A snapshot whose field is missing (old text NULL) is never written either (lane C, #533).
    await world.sql(
        "UPDATE cmdb_ci_versions SET snapshot = snapshot - 'name' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(old["record_id"]),
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        with pytest.raises(DBAPIError, match="marker in place"):
            await session.scalar(call, {"m": uuid.UUID(old["id"]), "v": MARKER})
    await world.sql(
        "UPDATE cmdb_ci_versions SET snapshot = jsonb_set(snapshot, '{name}', to_jsonb($3::text))"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(old["record_id"]),
        f"Printer of {name}",
    )
    snap = {s["id"]: s for s in await _snapshots(world, a, ci["id"])}[uuid.UUID(old["record_id"])]
    assert snap["snapshot"]["name"] == f"Printer of {name}"
    # The app role may never change a snapshot directly.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(
                text("UPDATE cmdb_ci_versions SET snapshot = '{}'::jsonb WHERE id = :id"),
                {"id": uuid.UUID(old["record_id"])},
            )
    # A closed erasure: nothing written.
    await world.sql(
        "UPDATE person_erasures SET state = 'rejected' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(erasure["id"]),
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (
            await session.scalar(call, {"m": uuid.UUID(old["id"]), "v": f"Printer of {MARKER}"})
            is False
        )


async def test_a_business_views_text_is_found_and_redacted(world: World) -> None:
    """S2 (0180): a view's name and description are record type `ci_business_view`."""
    a = world.a
    name = await _name(world, a, a.tech_a)
    base = dict((await _ci(world, a, "Payments service", "business_service")).json())
    made = await world.call(
        "POST",
        "/cmdb/business-views",
        a,
        a.admin,
        json={"base_ci_id": base["id"], "name": f"Map kept by {name}", "description": "Payments"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert made.status_code == 201, made.text
    view = dict(made.json())
    asked = await _request(world, a, a.admin, a.tech_a, successor_id=str(a.lead))
    assert asked.status_code == 201, asked.text
    erasure = dict(asked.json())
    await _build(world, a)
    page = await _mentions(world, a, erasure)
    assert name not in json.dumps(page)
    found = [m for m in _on(page, "ci_business_view", "name") if m["record_id"] == view["id"]]
    assert len(found) == 1
    assert not _on(page, "ci_business_view", "description")
    base_path = f"/erasures/{erasure['id']}/mentions"
    shown = await world.call("GET", f"{base_path}/{found[0]['id']}/passage", a, a.admin)
    assert shown.status_code == 200, shown.text
    assert name in shown.text
    done = await _redact(world, a, erasure, [found[0]["id"]])
    assert done.status_code == 200, done.text
    (row,) = await world.sql(
        "SELECT name, description, version FROM cmdb_business_views WHERE tenant_id = $1"
        " AND id = $2",
        a.tenant,
        uuid.UUID(view["id"]),
    )
    assert row["name"] == f"Map kept by {MARKER}"
    assert row["description"] == "Payments"
    assert row["version"] == view["version"] + 1
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND aggregate_id = $2"
        " AND event_type = 'cmdb.business_view.changed' ORDER BY id",
        a.tenant,
        view["id"],
    )
    assert json.loads(events[-1]["envelope"])["payload"]["changed_fields"] == ["name"]
    assert name not in json.dumps([e["envelope"] for e in events])
