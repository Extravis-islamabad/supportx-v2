"""People change their own contact details only when the tenant allows it (WP-028; REQ-PRT-013).

Lane B's conditions (#178): off by default and refused by the API when off; a directory's fields
stay read-only (the directory_source lock of #168), saying which directory; every change audited
with field names only, never the numbers.
"""

import json
import uuid

import asyncpg

from app.modules.identity_access.service.realtime import ROUTES
from app.shared.events import EventEnvelope
from tests.db.test_users_api import Directory, directory

__all__ = ["directory"]  # the fixture, re-used


async def _sql(d: Directory, statement: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(d.db.admin_url)  # FORCED RLS: the superuser sees every tenant
    try:
        return list(await conn.fetch(statement, *args))
    finally:
        await conn.close()


async def _allow(d: Directory) -> None:
    await _sql(
        d,
        "INSERT INTO identity_settings (tenant_id, people_edit_contact) VALUES ($1, true)"
        " ON CONFLICT (tenant_id) DO UPDATE SET people_edit_contact = true",
        d.tenant,
    )


async def _patch(d: Directory, user: uuid.UUID, **body: object) -> tuple[int, dict[str, object]]:
    current = await d.get(f"/api/v1/users/{user}", user)
    response = await d.client.patch(
        f"/api/v1/users/{user}",
        json=body,
        headers={**d.as_(user), "If-Match": current.headers["etag"]},
    )
    return response.status_code, response.json()


async def _audited(d: Directory, user: uuid.UUID) -> list[dict[str, object]]:
    rows = await _sql(
        d,
        "SELECT details FROM audit_entries WHERE action = 'user.contact_changed'"
        " AND object_id = $1",
        str(user),
    )
    return [
        json.loads(r["details"]) if isinstance(r["details"], str) else r["details"] for r in rows
    ]


async def test_contact_details_are_read_only_by_default(directory: Directory) -> None:
    mine = await directory.get(f"/api/v1/users/{directory.requester}", directory.requester)
    assert mine.json()["contact_editable"] is False
    status, body = await _patch(directory, directory.requester, phone="+971 4 555 0101")
    assert (status, body["code"]) == (403, "contact_editing_off")
    # Preferences still save as before.
    status, _ = await _patch(directory, directory.requester, time_zone="Asia/Dubai")
    assert status == 200


async def test_when_allowed_people_change_their_own_numbers_audited(directory: Directory) -> None:
    await _allow(directory)
    mine = await directory.get(f"/api/v1/users/{directory.requester}", directory.requester)
    assert mine.json()["contact_editable"] is True
    # Only on your own record: another person's detail never says it.
    theirs = await directory.get(f"/api/v1/users/{directory.requester}", directory.tech)
    assert theirs.json()["contact_editable"] is False
    status, body = await _patch(
        directory, directory.requester, phone=" +971 4 555 0101 ", mobile="+971 50 555 0102"
    )
    assert status == 200, body
    assert (body["phone"], body["mobile"]) == ("+971 4 555 0101", "+971 50 555 0102")
    entries = await _audited(directory, directory.requester)
    assert entries == [{"changed_fields": ["mobile", "phone"]}]
    assert "555" not in json.dumps(entries)  # names only, never the numbers
    # A preference-only save writes no contact entry.
    await _patch(directory, directory.requester, time_zone="Asia/Karachi")
    assert len(await _audited(directory, directory.requester)) == 1
    # Someone else's record is still refused.
    other = await directory.client.patch(
        f"/api/v1/users/{directory.tech}",
        json={"phone": "+1 555 0100"},
        headers={**directory.as_(directory.requester), "If-Match": '"1"'},
    )
    assert (other.status_code, other.json()["code"]) == (403, "own_profile_only")


async def test_a_number_must_look_like_one(directory: Directory) -> None:
    await _allow(directory)
    status, body = await _patch(directory, directory.requester, phone="call me maybe")
    assert status == 422
    errors = body["errors"]
    assert isinstance(errors, list)
    assert errors[0]["code"] == "phone_not_valid"


async def test_numbers_a_directory_keeps_stay_read_only(directory: Directory) -> None:
    await _allow(directory)
    await _sql(
        directory,
        "UPDATE users SET directory_source = 'entra' WHERE id = $1",
        directory.requester,
    )
    mine = await directory.get(f"/api/v1/users/{directory.requester}", directory.requester)
    assert mine.json()["contact_editable"] is False
    status, body = await _patch(directory, directory.requester, mobile="+971 50 555 0199")
    assert status == 422
    errors = body["errors"]
    assert isinstance(errors, list)
    assert errors[0] == {
        "field": "body.mobile",
        "code": "managed_by_directory",
        "message_key": "errors.field.managed_by_directory",
        "params": {"source": "entra"},
    }


async def test_resending_the_same_number_writes_no_audit_entry(directory: Directory) -> None:
    await _allow(directory)
    status, _ = await _patch(directory, directory.requester, phone="+971 4 555 0101")
    assert status == 200
    status, _ = await _patch(directory, directory.requester, phone="+971 4 555 0101")
    assert status == 200
    assert await _audited(directory, directory.requester) == [{"changed_fields": ["phone"]}]


async def test_nobody_sets_someone_elses_numbers_here(directory: Directory) -> None:
    await _allow(directory)
    before = (await directory.get(f"/api/v1/users/{directory.tech}", directory.tech)).json()
    for field in ("phone", "mobile"):
        refused = await directory.client.patch(
            f"/api/v1/users/{directory.tech}",
            json={field: "+1 555 0100"},
            headers={**directory.as_(directory.requester), "If-Match": f'"{before["version"]}"'},
        )
        assert (refused.status_code, refused.json()["code"]) == (403, "own_profile_only")
    after = (await directory.get(f"/api/v1/users/{directory.tech}", directory.tech)).json()
    assert (after["phone"], after["mobile"], after["version"]) == (
        before["phone"],
        before["mobile"],
        before["version"],
    )
    # The refused attempts are on the record as refusals; none of them is a change.
    attempts = await _audited(directory, directory.tech)
    assert len(attempts) == 2
    assert all("changed_fields" not in a for a in attempts)


async def test_turning_the_setting_on_tells_every_my_account(directory: Directory) -> None:
    """Rule 5c: a content-free signal on the tenant channel; each screen refetches its own."""
    tenant = directory.tenant
    changed = EventEnvelope.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "identity_access.identity_settings.changed",
            "schema_version": 1,
            "occurred_at": "2026-11-04T00:00:00Z",
            "tenant_id": str(tenant),
            "aggregate_type": "tenant",
            "aggregate_id": str(tenant),
            "aggregate_version": 2,
            "actor": {"type": "user", "id": str(directory.tech)},
            "payload": {"changed_fields": ["people_edit_contact"]},
        }
    )
    other = changed.model_copy(update={"payload": {"changed_fields": ["invitation_valid_days"]}})

    async def published(envelope: EventEnvelope) -> dict[str, str]:
        route = next(r for r in ROUTES if envelope.event_type in r.event_types)
        effects = await route.route(envelope, None)  # type: ignore[arg-type]  # unused by it
        return {p.channel.name: p.type for p in effects.publications}

    channel = f"t:{tenant}:broadcast"
    assert (await published(changed))[channel] == "identity_access.contact_editing_changed"
    assert channel not in await published(other)
