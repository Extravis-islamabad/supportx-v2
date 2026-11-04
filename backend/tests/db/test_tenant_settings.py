"""Instance settings over HTTP (WP-042; REQ-ADM-049, 050, 052).

- Everyone signed in reads them; only the organisation's configure right (or settings.manage)
  changes them, with If-Match.
- Every bad value is named at its field; English is always offered.
- A base currency already set changes only with a confirmation.
- A change writes an outbox event; the table is isolated per tenant (RLS).
"""

import asyncpg
import httpx

from tests.db.test_access_api import World, problem, world  # noqa: F401 - the fixture, reused
from tests.db.test_auth_bff import Bff, bff  # noqa: F401 - the fixture, reused

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


async def test_a_language_switched_off_falls_back_to_the_tenant_default(bff: Bff) -> None:  # noqa: F811
    """REQ-ADM-052: someone who chose Urdu sees the default once Urdu is no longer offered."""
    admin = bff.user("a", email="langadmin@demo.test", locale="en", roles=("tenant_admin",))
    await bff.login(admin)
    me = (await bff.me()).json()
    path = f"/api/v1/users/{me['user']['id']}"
    read = await bff.client.get(path)
    chosen = await bff.client.patch(
        path,
        json={"ui_locale": "ur"},
        headers={"X-CSRF-Token": me["csrf_token"], "If-Match": read.headers["ETag"]},
    )
    assert chosen.status_code == 200, chosen.text
    assert (await bff.me()).json()["user"]["locale"] == "ur"
    settings = await bff.client.get(f"/api/v1{PATH}")
    saved = await bff.client.patch(
        f"/api/v1{PATH}",
        json={"languages": ["en", "ar"], "default_language": "ar"},
        headers={"X-CSRF-Token": me["csrf_token"], "If-Match": settings.headers["ETag"]},
    )
    assert saved.status_code == 200, saved.text
    assert (await bff.me()).json()["user"]["locale"] == "ar"


async def test_personal_preferences_win_and_defaults_are_read_not_copied(bff: Bff) -> None:  # noqa: F811
    """REQ-ADM-059, 062 and Haider's rule: a changed tenant default reaches everyone who has not
    chosen, never anyone who has; clearing a choice goes back to the default."""
    admin = bff.user("a", email="prefadmin@demo.test", locale="en", roles=("tenant_admin",))
    await bff.login(admin)
    me = (await bff.me()).json()
    user = me["user"]
    assert (user["theme_mode"], user["text_scale"], user["date_format"]) == (
        None,
        100,
        "dd/mm/yyyy",
    )
    assert (user["time_zone"], user["chosen"]) == ("UTC", [])
    csrf = {"X-CSRF-Token": me["csrf_token"]}
    path = f"/api/v1/users/{user['id']}"

    async def patch(url: str, body: dict[str, object]) -> httpx.Response:
        read = await bff.client.get(url)
        return await bff.client.patch(
            url, json=body, headers={**csrf, "If-Match": read.headers["ETag"]}
        )

    bad = await patch(path, {"theme_mode": "neon", "text_scale": 95, "date_format": "yy"})
    assert bad.status_code == 422, bad.text
    assert {e["field"] for e in bad.json()["errors"]} == {
        "body.theme_mode",
        "body.text_scale",
        "body.date_format",
    }
    chosen = await patch(path, {"theme_mode": "dark", "text_scale": 130, "time_format": "12h"})
    assert chosen.status_code == 200, chosen.text
    # The tenant changes its defaults: only what the person left alone follows.
    saved = await patch(
        f"/api/v1{PATH}",
        {"time_format": "24h", "date_format": "yyyy-mm-dd", "time_zone": "Asia/Dubai"},
    )
    assert saved.status_code == 200, saved.text
    user = (await bff.me()).json()["user"]
    assert (user["theme_mode"], user["text_scale"], user["time_format"]) == ("dark", 130, "12h")
    assert (user["date_format"], user["time_zone"]) == ("yyyy-mm-dd", "Asia/Dubai")
    assert user["chosen"] == ["text_scale", "theme_mode", "time_format"]
    cleared = await patch(path, {"time_format": None})
    assert cleared.status_code == 200, cleared.text
    assert (await bff.me()).json()["user"]["time_format"] == "24h"
