"""People change their own contact details only when the tenant allows it (WP-028; REQ-PRT-013).

Lane B's conditions (#178): off by default and refused by the API when off; a directory's fields
stay read-only (the directory_source lock of #168), saying which directory; every change audited
with field names only, never the numbers.
"""

import json
import uuid

import asyncpg

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
    status, body = await _patch(directory, directory.requester, phone="+971 4 555 0101")
    assert (status, body["code"]) == (403, "contact_editing_off")
    # Preferences still save as before.
    status, _ = await _patch(directory, directory.requester, time_zone="Asia/Dubai")
    assert status == 200


async def test_when_allowed_people_change_their_own_numbers_audited(directory: Directory) -> None:
    await _allow(directory)
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
