"""The two reads the erasure screens need (D-171, ADR-052; the coordinator, 2026-11-17).

- `GET /people/{id}/legal-hold`: for those who place holds or ask for erasure; others 403.
- `GET /people/{id}/uploads`: `people.erase` only; the person's live uploads as metadata (never
  content), cursor-paged, each page audited; another tenant's person is not found.
"""

import json
import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import Org, World

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the incidents fixture, re-used


async def _upload(world: World, org: Org, owner: uuid.UUID, name: str) -> uuid.UUID:
    file_id = uuid.uuid4()
    await world.sql(
        "INSERT INTO files (id, tenant_id, name, size, sha256, content_type, kind, state,"
        " data_key_id, object_key, stored_size, source, created_by)"
        " VALUES ($1, $2, $3, 12, $4, 'text/plain', 'other', 'clean', $5, $6, 12, 'ui', $7)",
        file_id,
        org.tenant,
        name,
        bytes(32),
        uuid.uuid4(),
        f"{org.tenant}/{file_id}",
        owner,
    )
    return file_id


async def _audit(world: World, org: Org, action: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT object_id, details FROM audit_entries"
        " WHERE tenant_id = $1 AND action = $2 ORDER BY occurred_at",
        org.tenant,
        action,
    )
    return [{**dict(row), "details": json.loads(row["details"])} for row in rows]


async def test_a_hold_is_read_by_the_rights_that_need_it(world: World) -> None:
    a = world.a
    shown = await world.call("GET", f"/people/{a.requester2}/legal-hold", a, a.admin)
    assert shown.status_code == 200, shown.text
    assert (shown.json()["held"], shown.json()["held_by"]) == (False, None)
    assert shown.headers["ETag"] == f'"{shown.json()["version"]}"'
    held = await world.call(
        "PUT",
        f"/people/{a.requester2}/legal-hold",
        a,
        a.admin,
        json={"reason": "Litigation hold, case 2026-31"},
        headers={"If-Match": shown.headers["ETag"]},
    )
    assert held.status_code == 200, held.text
    again = await world.call("GET", f"/people/{a.requester2}/legal-hold", a, a.admin)
    assert again.json()["held"] is True
    assert again.json()["held_by"] == str(a.admin)
    assert again.json()["reason"] == "Litigation hold, case 2026-31"
    # A technician holds neither right.
    refused = await world.call("GET", f"/people/{a.requester2}/legal-hold", a, a.tech_a)
    assert refused.status_code == 403
    # Lifted again so other tests see the person free.
    await world.call(
        "POST",
        f"/people/{a.requester2}/legal-hold/lift",
        a,
        a.admin,
        json={"reason": "Test over"},
        headers={"If-Match": f'"{again.json()["version"]}"'},
    )


async def test_uploads_are_metadata_paged_and_audited(world: World) -> None:
    a = world.a
    person = a.tech_b
    made = [await _upload(world, a, person, f"scan-{n}.txt") for n in range(3)]
    await _upload(world, a, a.tech_a, "someone-else.txt")
    first = await world.call("GET", f"/people/{person}/uploads?limit=2", a, a.admin)
    assert first.status_code == 200, first.text
    assert first.headers["Cache-Control"] == "no-store"
    body = first.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None
    assert set(body["items"][0]) == {
        "id",
        "name",
        "size",
        "content_type",
        "created_at",
        "attached_to",
    }  # metadata only: no content, no link
    rest = await world.call(
        "GET", f"/people/{person}/uploads?limit=2&cursor={body['next_cursor']}", a, a.admin
    )
    seen = [i["id"] for i in body["items"]] + [i["id"] for i in rest.json()["items"]]
    assert {str(f) for f in made} <= set(seen)
    assert "someone-else.txt" not in {i["name"] for i in body["items"] + rest.json()["items"]}
    logged = await _audit(world, a, "person.uploads_listed")
    assert [e["object_id"] for e in logged[-2:]] == [str(person), str(person)]
    assert logged[-2]["details"] == {"files": 2, "more": True}


async def test_uploads_need_the_erasure_right_and_stay_in_the_tenant(
    world: World,
) -> None:
    a, b = world.a, world.b
    refused = await world.call("GET", f"/people/{a.tech_b}/uploads", a, a.tech_a)
    assert refused.status_code == 403
    elsewhere = await world.call("GET", f"/people/{a.tech_b}/uploads", b, b.admin)
    assert elsewhere.status_code == 404
