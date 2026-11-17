"""The audit names the real actor (WP-057 S4b, REQ-AUD-014).

A person's API key writes the key as the actor and the person as `on_behalf`; the person, never
the key, is whose personal data (the IP, the device) the entry holds, so erasing them still finds
it. The audit API names both.
"""

import uuid

import asyncpg
import pytest

from tests.db.test_api_keys import _as_key, _make, _signed_in
from tests.db.test_auth_bff import Bff, bff  # noqa: F401 - the fixture, reused

pytestmark = pytest.mark.db


async def test_a_persons_key_is_the_actor_on_their_behalf(bff: Bff) -> None:  # noqa: F811
    csrf = await _signed_in(bff)
    me = (await bff.me()).json()["user"]["id"]
    made = (await _make(bff, csrf, scopes=["incidents:read", "incidents:write"])).json()
    async with _as_key(bff, made["key"]) as api:
        created = await api.post(
            "/api/v1/incidents",
            json={"subject": "Made with a key", "requester_id": me},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
    assert created.status_code == 201, created.text
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        entries = await conn.fetch(
            "SELECT id, actor_type, actor_id, on_behalf_id FROM audit_entries WHERE object_id = $1",
            created.json()["id"],
        )
        assert entries, "the save wrote no entry"
        assert {(e["actor_type"], str(e["actor_id"]), str(e["on_behalf_id"])) for e in entries} == {
            ("api_key", made["id"], me)
        }
        subjects = await conn.fetch(
            "SELECT DISTINCT subject_id FROM audit_personal WHERE entry_id = ANY($1::uuid[])",
            [e["id"] for e in entries],
        )
        assert {str(s["subject_id"]) for s in subjects} <= {me}
    finally:
        await conn.close()
    shown = await bff.client.get(f"/api/v1/audit/entries/{entries[0]['id']}")
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert (body["actor_type"], body["actor_name"], body["on_behalf_id"]) == (
        "api_key",
        "Nightly export",
        me,
    )
