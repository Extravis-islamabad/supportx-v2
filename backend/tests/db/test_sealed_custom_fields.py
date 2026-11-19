"""Sensitive custom fields sealed at rest (WP-057 S3b-2a; SEC-040; ADR-050 addendum).

- A sensitive value is stored as `sx2:` text, never in the search text, with a blind-index row;
  readers get it back opened, the record page and the list alike.
- A list filters a sealed field by exact value only (`eq`, `in`), through the index; any other
  operator, or a sort, is refused.
- A field the reader's roles withhold is never rewritten to the index: no oracle (lane A).
- History keeps a sealed field's values sealed for their own cell: moved to another version or
  side, a value does not open (lane B). A value sent back unchanged is no change.
"""

import json
import statistics
import time
import uuid
from typing import Any

import asyncpg
import httpx
import pytest
from pydantic import SecretStr

from app.core.tenancy import TenantContext
from app.modules.work_items.service import custom_values
from app.shared.fields import Binding, field_cipher_for
from app.shared.files.keyring import KeyRing
from tests.db.test_field_access_reads import _custom_field, _rule
from tests.db.test_incidents_api import (  # noqa: F401 - fixture
    BASE,
    CONSOLE,
    SEED,
    Org,
    World,
    make_org,
    world,
)
from tests.db.test_reports_api import reports  # noqa: F401 - fixture
from tooling import timing

pytestmark = pytest.mark.db
# The test values hold a space and "!", which no base64 or hex text contains, so checking that a
# value is absent from the stored ciphertext can never fail by chance (#535's shard 8 flake).


def _with_keys(w: World) -> None:
    """The installation's key ring, for the app's and the database's settings alike."""
    settings = w.app.state.settings.model_copy(
        update={"files_keys": SecretStr(KeyRing.generate()), "valkey_url": None}
    )
    w.app.state.settings = settings
    w.app.state.db.settings = settings


async def _sensitive(w: World, org: Org, name: str) -> str:
    """A text custom field, marked sensitive and sealed (the S3b-2b switch sets this)."""
    key = await _custom_field(w, org, name)
    await w.sql(
        "UPDATE custom_fields SET sensitive = true, seal_state = 'sealed'"
        " WHERE tenant_id = $1 AND entity = 'incident' AND key = $2",
        org.tenant,
        key,
    )
    return key


async def _stored(w: World, org: Org, record_id: str, key: str) -> tuple[str, str | None]:
    (row,) = await w.sql(
        "SELECT custom->>$3 AS value, custom_text FROM work_items WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        uuid.UUID(record_id),
        key,
    )
    return row["value"], row["custom_text"]


async def test_a_sensitive_value_is_sealed_at_rest_and_reads_back_opened(world: World) -> None:  # noqa: F811
    _with_keys(world)
    a = world.a
    key = await _sensitive(world, a, "Pay band")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={key: "B7 one!"})
    value, text = await _stored(world, a, item["id"], key)
    assert value.startswith("sx2:")
    assert "B7 one!" not in value
    assert "B7 one!" not in (text or "")
    index = await world.sql(
        "SELECT digest FROM work_item_field_index WHERE tenant_id = $1 AND work_item_id = $2"
        " AND field_key = $3",
        a.tenant,
        uuid.UUID(item["id"]),
        key,
    )
    assert len(index) == 1
    assert "B7 one!" not in index[0]["digest"]
    shown = await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)
    assert shown.status_code == 200, shown.text
    assert shown.json()["custom"][key] == "B7 one!"
    assert shown.json()["unreadable_fields"] == []
    listed = await world.call("GET", BASE, a, a.admin)
    row = next(r for r in listed.json()["items"] if r["id"] == item["id"])
    assert row["custom"][key] == "B7 one!"


async def test_a_sealed_field_filters_by_exact_value_only_and_never_sorts(world: World) -> None:  # noqa: F811
    _with_keys(world)
    a = world.a
    key = await _sensitive(world, a, "Grade band")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={key: "Senior"})

    async def filtered(node: dict[str, object]) -> httpx.Response:
        return await world.call("GET", BASE, a, a.admin, params={"filter": json.dumps(node)})

    hit = await filtered({"field": f"custom.{key}", "op": "eq", "value": "senior "})  # normalised
    assert hit.status_code == 200, hit.text
    assert [r["id"] for r in hit.json()["items"]] == [item["id"]]
    listed = await filtered({"field": f"custom.{key}", "op": "in", "value": ["Junior", "Senior"]})
    assert [r["id"] for r in listed.json()["items"]] == [item["id"]]
    miss = await filtered({"field": f"custom.{key}", "op": "eq", "value": "Junior"})
    assert miss.json()["items"] == []
    contains = await filtered({"field": f"custom.{key}", "op": "contains", "value": "Sen"})
    assert contains.status_code == 422, contains.text
    assert "field_not_filterable_sealed" in contains.text
    sorted_ = await world.call("GET", BASE, a, a.admin, params={"sort": f"custom.{key}"})
    assert sorted_.status_code == 422, sorted_.text


async def test_a_withheld_sealed_field_is_never_an_oracle(world: World) -> None:  # noqa: F811
    """Lane A: a technician whose role hides the field gets the usual refusal, no narrowed list."""
    _with_keys(world)
    a = world.a
    key = await _sensitive(world, a, "Bonus band")
    await world.create(a, a.admin, group_id=str(a.ga), custom={key: "B7 one!"})
    await _rule(world, a, "technician", f"custom.{key}", "hidden")
    probe = json.dumps({"field": f"custom.{key}", "op": "eq", "value": "B7 one!"})
    refused = await world.call("GET", BASE, a, a.tech_a, params={"filter": probe})
    assert refused.status_code == 422, refused.text
    assert "field_not_filterable_sealed" not in refused.text  # the withheld refusal, unchanged


async def test_history_keeps_sealed_values_per_cell_and_unchanged_is_no_change(
    world: World,  # noqa: F811
) -> None:
    _with_keys(world)
    a = world.a
    key = await _sensitive(world, a, "Cost band")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={key: "B7 one!"})
    current = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    changed = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        json={"custom": {key: "C9 two!"}},
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    (row,) = await world.sql(
        "SELECT old_value #>> '{}' AS old, new_value #>> '{}' AS new, record_version"
        " FROM field_changes WHERE tenant_id = $1 AND record_id = $2 AND field = $3"
        " AND kind = 'updated'",
        a.tenant,
        uuid.UUID(item["id"]),
        f"custom.{key}",
    )
    assert row["old"].startswith("sx2:")
    assert row["new"].startswith("sx2:")
    assert "C9 two!" not in row["new"]
    version = row["record_version"]
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        cipher = field_cipher_for(session, world.app.state.settings)
        record = uuid.UUID(item["id"])

        def cell(v: int, side: str) -> Binding:
            return custom_values.history_binding("work_item", record, f"custom.{key}", v, side)

        assert (
            await cipher.open(custom_values.CUSTOM, cell(version, "new"), row["new"]) == '"C9 two!"'
        )
        # Moved to another version or side, it does not open (lane B).
        assert await cipher.open(custom_values.CUSTOM, cell(version + 1, "new"), row["new"]) is None
        assert await cipher.open(custom_values.CUSTOM, cell(version, "old"), row["new"]) is None
    # The created row too: sealed for its own cell, not the record's ciphertext copied.
    (made,) = await world.sql(
        "SELECT new_value #>> '{}' AS new, record_version FROM field_changes WHERE tenant_id = $1"
        " AND record_id = $2 AND field = $3 AND kind = 'created'",
        a.tenant,
        uuid.UUID(item["id"]),
        f"custom.{key}",
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        cipher = field_cipher_for(session, world.app.state.settings)
        binding = custom_values.history_binding(
            "work_item", uuid.UUID(item["id"]), f"custom.{key}", made["record_version"], "new"
        )
        assert await cipher.open(custom_values.CUSTOM, binding, made["new"]) == '"B7 one!"'
    # The opened value sent back unchanged is no change: no new history row.
    again = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    same = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        json={"custom": {key: "C9 two!"}, "subject": "Renamed"},
        headers={"If-Match": f'"{again["version"]}"'},
    )
    assert same.status_code == 200, same.text
    rows = await world.sql(
        "SELECT count(*) AS n FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = $3 AND kind = 'updated'",
        a.tenant,
        uuid.UUID(item["id"]),
        f"custom.{key}",
    )
    assert rows[0]["n"] == 1


async def _changed(w: World, org: Org, key: str, first: str, second: str) -> dict[str, Any]:
    item = await w.create(org, org.admin, group_id=str(org.ga), custom={key: first})
    current = (await w.call("GET", f"{BASE}/{item['id']}", org, org.admin)).json()
    changed = await w.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        org,
        org.admin,
        json={"custom": {key: second}},
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    return item


async def test_history_opens_sealed_values_and_never_shows_sealed_text(world: World) -> None:  # noqa: F811
    """Lane B's #520 review: no `sx2:` reaches a reader; masked stays masked; tampered hides."""
    _with_keys(world)
    a = world.a
    key = await _sensitive(world, a, "Shift band")
    item = await _changed(world, a, key, "B7 one!", "C9 two!")
    page = f"{BASE}/{item['id']}/history"
    shown = await world.call("GET", page, a, a.admin)
    assert shown.status_code == 200, shown.text
    assert "sx2:" not in shown.text
    lines = [
        c for e in shown.json()["items"] for c in e["changes"] if c["field"] == f"custom.{key}"
    ]
    assert {"old": "B7 one!", "new": "C9 two!"} in [
        {"old": c.get("old"), "new": c.get("new")} for c in lines
    ]
    # Masked for the technician: the hidden line, never opened.
    await _rule(world, a, "technician", f"custom.{key}", "masked")
    masked = await world.call("GET", page, a, a.tech_a)
    assert masked.status_code == 200, masked.text
    assert "sx2:" not in masked.text
    assert "C9 two!" not in masked.text
    # A value moved into another row (tampering) does not open: the hidden line, no ciphertext.
    record = uuid.UUID(item["id"])
    await world.sql(
        "UPDATE field_changes SET new_value = (SELECT new_value FROM field_changes"
        " WHERE tenant_id = $1 AND record_id = $2 AND field = $3 AND kind = 'created')"
        " WHERE tenant_id = $1 AND record_id = $2 AND field = $3 AND kind = 'updated'",
        a.tenant,
        record,
        f"custom.{key}",
    )
    moved = await world.call("GET", page, a, a.admin)
    assert moved.status_code == 200, moved.text
    assert "sx2:" not in moved.text
    updated = [
        c
        for e in moved.json()["items"]
        if e["kind"] == "updated"
        for c in e["changes"]
        if c["field"] == f"custom.{key}"
    ]
    assert [(c["hidden"], c.get("old"), c.get("new")) for c in updated] == [(True, None, None)]


async def test_equal_values_in_two_sealed_fields_never_link(world: World) -> None:  # noqa: F811
    """Lane B's #520 review: the field is in the digest's input."""
    _with_keys(world)
    a = world.a
    one = await _sensitive(world, a, "Badge code")
    two = await _sensitive(world, a, "Locker code")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={one: "K1", two: "K1"})
    rows = await world.sql(
        "SELECT field_key, digest FROM work_item_field_index WHERE tenant_id = $1"
        " AND work_item_id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    digests = {r["field_key"]: r["digest"] for r in rows}
    assert set(digests) == {one, two}
    assert digests[one] != digests[two]


async def test_reports_refuse_a_sealed_field(reports: World) -> None:  # noqa: F811
    """Its stored values are ciphertext: a report naming it is refused, never run blank."""
    w, a = reports, reports.a
    _with_keys(w)
    key = await _sensitive(w, a, "Grade code")
    await w.create(a, a.admin, group_id=str(a.ga), custom={key: "G4"})
    name = f"custom.{key}"
    for use in (
        {"filter": {"field": name, "op": "eq", "value": "G4"}, "measures": ["count"]},
        {"columns": ["display_id", name], "measures": ["count"]},
    ):
        refused = await w.call(
            "POST",
            "/reports/run",
            a,
            a.admin,
            json={"definition": {"entity": "incident", **use}, "language": "en"},
            headers=CONSOLE,
        )
        assert refused.status_code == 403, (use, refused.text)
        assert refused.json()["code"] == "field_not_permitted", use
        assert "sx2:" not in refused.text


# --- performance (lane B's #520 note: a sealed filter on a large list) ---------------------------

SEALED_ROWS = timing.volume(10_000, 1_000)  # all nightly, a smoke run in PRs
SEALED_RUNS = 20
INDEX_SEED = """
INSERT INTO work_item_field_index (tenant_id, id, work_item_id, field_key, key_id, digest)
SELECT $1, gen_random_uuid(), w.id, $2, $3,
       CASE WHEN w.display_number % 10 = 0 THEN $4
            ELSE encode(sha256(w.id::text::bytea), 'hex') END
FROM work_items w
WHERE w.tenant_id = $1 AND w.type = 'incident' AND w.display_number > 1000
"""


@pytest.mark.timing
async def test_a_sealed_filter_p95_on_a_large_list(world: World) -> None:  # noqa: F811
    """A sealed `eq` filter stays an index lookup: p95 < 300 ms on 10,000 incidents nightly."""
    _with_keys(world)
    org = await make_org(world, "SealedPerf")
    key = await _sensitive(world, org, "Perf band")
    real = await world.create(org, org.admin, custom={key: "B7 one!"})  # the real key and digest
    (made,) = await world.sql(
        "SELECT key_id, digest FROM work_item_field_index WHERE tenant_id = $1"
        " AND work_item_id = $2",
        org.tenant,
        uuid.UUID(real["id"]),
    )
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        await conn.execute(
            SEED, org.tenant, org.requester, org.s1, org.ga, org.gb, org.tech_a, SEALED_ROWS
        )
        await conn.execute(INDEX_SEED, org.tenant, key, made["key_id"], made["digest"])
        await conn.execute("ANALYZE work_items")
        await conn.execute("ANALYZE work_item_field_index")
    finally:
        await conn.close()
    sealed = json.dumps({"field": f"custom.{key}", "op": "eq", "value": "b7 one!"})
    queries = {
        "plain_list": "?limit=50",
        "sealed_eq": "?" + str(httpx.QueryParams({"filter": sealed, "limit": "50"})),
    }
    report: dict[str, dict[str, float]] = {}
    for name, suffix in queries.items():
        timings = []
        response = None
        for _ in range(SEALED_RUNS):
            started = time.perf_counter()
            response = await world.call("GET", f"{BASE}{suffix}", org, org.admin)
            timings.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200, response.text
        assert response is not None
        timings.sort()
        report[name] = {
            "p50_ms": round(statistics.median(timings), 1),
            "p95_ms": round(timings[int(len(timings) * 0.95) - 1], 1),
            "items": len(response.json()["items"]),
        }
        print(f"\n[perf] sealed_filter {name}: rows={SEALED_ROWS}, {report[name]}")  # noqa: T201
    assert report["sealed_eq"]["items"] == 50  # one in ten of the rows matches
    timing.record("sealed_filter_10k", report)
    assert all(r["p95_ms"] < timing.limit(300) for r in report.values()), report


async def test_a_closed_incident_still_refuses_a_sealed_field_edit(world: World) -> None:  # noqa: F811
    """The coordinator, after the 0169 merge: lane A's closed check runs before the opening.

    A technician without `incidents.edit_closed` is refused (`record_closed`) and the sealed
    value is untouched; the admin, with a reason, may edit it, and it is sealed again.
    """
    _with_keys(world)
    a = world.a
    key = await _sensitive(world, a, "Closed band")
    item = await world.create(
        a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a), custom={key: "B7 one!"}
    )
    resolved = await world.act(a, a.admin, item, "resolve")
    closed = (await world.act(a, a.admin, resolved.json(), "close")).json()
    assert closed["status_category"] == "closed"
    before, _ = await _stored(world, a, item["id"], key)
    refused = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.tech_a,
        json={"custom": {key: "C9 two!"}},
        headers={"If-Match": f'"{closed["version"]}"', **CONSOLE},
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "record_closed"), refused.text
    assert (await _stored(world, a, item["id"], key))[0] == before
    edited = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        json={"custom": {key: "C9 two!"}, "edit_reason": "Corrected after closing."},
        headers={"If-Match": f'"{closed["version"]}"', **CONSOLE},
    )
    assert edited.status_code == 200, edited.text
    after, _ = await _stored(world, a, item["id"], key)
    assert after.startswith("sx2:")
    assert after != before
    assert edited.json()["custom"][key] == "C9 two!"
