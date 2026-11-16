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
import uuid

import httpx
import pytest
from pydantic import SecretStr

from app.core.tenancy import TenantContext
from app.modules.work_items.service import custom_values
from app.shared.fields import Binding, field_cipher_for
from app.shared.files.keyring import KeyRing
from tests.db.test_field_access_reads import _custom_field, _rule
from tests.db.test_incidents_api import BASE, Org, World, world  # noqa: F401 - fixture

pytestmark = pytest.mark.db


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
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={key: "B7"})
    value, text = await _stored(world, a, item["id"], key)
    assert value.startswith("sx2:")
    assert "B7" not in value
    assert "B7" not in (text or "")
    index = await world.sql(
        "SELECT digest FROM work_item_field_index WHERE tenant_id = $1 AND work_item_id = $2"
        " AND field_key = $3",
        a.tenant,
        uuid.UUID(item["id"]),
        key,
    )
    assert len(index) == 1
    assert "B7" not in index[0]["digest"]
    shown = await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)
    assert shown.status_code == 200, shown.text
    assert shown.json()["custom"][key] == "B7"
    assert shown.json()["unreadable_fields"] == []
    listed = await world.call("GET", BASE, a, a.admin)
    row = next(r for r in listed.json()["items"] if r["id"] == item["id"])
    assert row["custom"][key] == "B7"


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
    await world.create(a, a.admin, group_id=str(a.ga), custom={key: "B7"})
    await _rule(world, a, "technician", f"custom.{key}", "hidden")
    probe = json.dumps({"field": f"custom.{key}", "op": "eq", "value": "B7"})
    refused = await world.call("GET", BASE, a, a.tech_a, params={"filter": probe})
    assert refused.status_code == 422, refused.text
    assert "field_not_filterable_sealed" not in refused.text  # the withheld refusal, unchanged


async def test_history_keeps_sealed_values_per_cell_and_unchanged_is_no_change(
    world: World,  # noqa: F811
) -> None:
    _with_keys(world)
    a = world.a
    key = await _sensitive(world, a, "Cost band")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={key: "B7"})
    current = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    changed = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        json={"custom": {key: "C9"}},
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    (row,) = await world.sql(
        "SELECT old_value #>> '{}' AS old, new_value #>> '{}' AS new, record_version"
        " FROM field_changes WHERE tenant_id = $1 AND record_id = $2 AND field = $3",
        a.tenant,
        uuid.UUID(item["id"]),
        f"custom.{key}",
    )
    assert row["old"].startswith("sx2:")
    assert row["new"].startswith("sx2:")
    assert "C9" not in row["new"]
    version = row["record_version"]
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        cipher = field_cipher_for(session, world.app.state.settings)
        record = uuid.UUID(item["id"])

        def cell(v: int, side: str) -> Binding:
            return custom_values.history_binding("work_item", record, f"custom.{key}", v, side)

        assert await cipher.open(custom_values.CUSTOM, cell(version, "new"), row["new"]) == '"C9"'
        # Moved to another version or side, it does not open (lane B).
        assert await cipher.open(custom_values.CUSTOM, cell(version + 1, "new"), row["new"]) is None
        assert await cipher.open(custom_values.CUSTOM, cell(version, "old"), row["new"]) is None
    # The opened value sent back unchanged is no change: no new history row.
    again = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    same = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        json={"custom": {key: "C9"}, "subject": "Renamed"},
        headers={"If-Match": f'"{again["version"]}"'},
    )
    assert same.status_code == 200, same.text
    rows = await world.sql(
        "SELECT count(*) AS n FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = $3",
        a.tenant,
        uuid.UUID(item["id"]),
        f"custom.{key}",
    )
    assert rows[0]["n"] == 1
