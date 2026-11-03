"""Instance settings over HTTP (WP-042; REQ-ADM-049, 050, 052).

- Everyone signed in reads them; only the organisation's configure right (or settings.manage)
  changes them, with If-Match.
- Every bad value is named at its field; English is always offered.
- A base currency already set changes only with a confirmation.
- A change writes an outbox event; the table is isolated per tenant (RLS).
"""

import asyncpg

from tests.db.test_access_api import World, problem, world  # noqa: F401 - the fixture, reused

PATH = "/organization/settings"


async def _read(world: World, user: object, org: object = None) -> tuple[dict[str, object], str]:  # noqa: F811
    got = await world.call("GET", PATH, org or world.a, user)  # type: ignore[arg-type]  # Org, user ID
    assert got.status_code == 200, got.text
    return got.json(), got.headers["etag"]


async def test_everyone_reads_the_defaults_and_only_configurers_change_them(world: World) -> None:  # noqa: F811
    a = world.a
    settings, etag = await _read(world, a.tech)
    assert (settings["time_zone"], settings["base_currency"]) == ("UTC", "USD")
    assert settings["languages"] == ["en", "ar", "ur"]
    refused = await world.call(
        "PATCH", PATH, a, a.tech, json={"time_zone": "Asia/Karachi"}, headers={"If-Match": etag}
    )
    assert problem(refused)[0] == 403
    saved = await world.call(
        "PATCH",
        PATH,
        a,
        a.admin,
        json={"time_zone": "Asia/Karachi", "week_start": "sunday", "base_currency": "PKR"},
        headers={"If-Match": etag},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["time_zone"] == "Asia/Karachi"
    stale = await world.call(
        "PATCH", PATH, a, a.admin, json={"time_zone": "UTC"}, headers={"If-Match": etag}
    )
    assert problem(stale) == (409, "version_conflict")


async def test_bad_values_are_named_at_their_fields_and_english_stays(world: World) -> None:  # noqa: F811
    a = world.a
    _, etag = await _read(world, a.admin)
    bad = await world.call(
        "PATCH",
        PATH,
        a,
        a.admin,
        json={"time_zone": "Mars/Olympus", "languages": ["ar"], "base_currency": "XYZ"},
        headers={"If-Match": etag},
    )
    assert bad.status_code == 422, bad.text
    fields = {e["field"]: e["code"] for e in bad.json()["errors"]}
    assert fields == {
        "body.time_zone": "time_zone_unknown",
        "body.base_currency": "currency_unknown",
        "body.languages": "languages_invalid",
        # Offering only Arabic would also leave the default (English) unoffered.
        "body.default_language": "default_language_not_offered",
    }


async def test_a_set_currency_changes_only_when_confirmed(world: World) -> None:  # noqa: F811
    a = world.a
    _, etag = await _read(world, a.admin)
    first = await world.call(
        "PATCH", PATH, a, a.admin, json={"base_currency": "AED"}, headers={"If-Match": etag}
    )
    assert first.status_code == 200, first.text  # the first choice needs no confirmation
    etag = first.headers["etag"]
    unconfirmed = await world.call(
        "PATCH", PATH, a, a.admin, json={"base_currency": "SAR"}, headers={"If-Match": etag}
    )
    assert problem(unconfirmed) == (409, "currency_change_needs_confirmation")
    confirmed = await world.call(
        "PATCH",
        PATH,
        a,
        a.admin,
        json={"base_currency": "SAR", "confirm_currency": True},
        headers={"If-Match": etag},
    )
    assert confirmed.json()["base_currency"] == "SAR"


async def test_a_change_writes_an_event_and_the_table_is_isolated(world: World) -> None:  # noqa: F811
    a, b = world.a, world.b
    _, etag = await _read(world, a.admin)
    await world.call(
        "PATCH", PATH, a, a.admin, json={"languages": ["en", "ar"]}, headers={"If-Match": etag}
    )
    assert (await _read(world, b.admin, b))[0]["languages"] == ["en", "ar", "ur"]  # B untouched
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        fields = await conn.fetchval(
            "SELECT envelope->'payload'->>'changed_fields' FROM outbox_events"
            " WHERE tenant_id = $1 AND event_type = 'organization.tenant_settings.changed'"
            " ORDER BY id DESC LIMIT 1",
            a.tenant,
        )
    finally:
        await conn.close()
    assert fields == '["languages"]'
    conn = await asyncpg.connect(world.db.app_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(b.tenant))
            rows = await conn.fetch("SELECT languages FROM tenant_settings")
            assert [list(r["languages"]) for r in rows] == [["en", "ar", "ur"]]
    finally:
        await conn.close()
