"""Tenant branding over HTTP (WP-017; REQ-ADM-055, REQ-PRT-016 AC1-AC2, REQ-SEC-003, REQ-SEC-004).

Same world as test_files_api.py: brand uploads are files (owner `branding`) on real S3-compatible
storage, scanned by the fake scanner; the variants are generated with Pillow on save.
"""

import io
import uuid
from typing import Any

import httpx
import pytest
from PIL import Image

from app.shared.files.service.core import FileServices
from tests.db.test_files_api import audit_actions, files, scan_waiting, storage, upload
from tests.db.test_incidents_api import World, problem, world

__all__ = ["files", "storage", "world"]  # fixtures, re-used

pytestmark = [pytest.mark.db]

SETTINGS = "/organization/branding/settings"


def logo_png(width: int = 600, height: int = 150) -> bytes:
    """A cut-out logo: a coloured mark and dark "text" on transparency."""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for x in range(10, 140):
        for y in range(10, 140):
            image.putpixel((x, y), (11, 83, 148, 255))
    for x in range(160, width - 10):
        for y in range(50, 100):
            image.putpixel((x, y), (30, 30, 30, 255))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


async def settings(world: World, org: Any, user: uuid.UUID) -> httpx.Response:  # noqa: ANN401 - Org
    return await world.call("GET", SETTINGS, org, user)


async def save(
    world: World,
    org: Any,  # noqa: ANN401 - Org
    user: uuid.UUID,
    version: int,
    **body: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "PUT", SETTINGS, org, user, json=body, headers={"If-Match": f'"{version}"'}
    )


async def brand_upload(world: World, org: Any, user: uuid.UUID, data: bytes) -> str:  # noqa: ANN401
    created = await upload(world, org, user, ("branding", org.tenant), data, "logo.png")
    assert created.status_code == 201, created.text
    await scan_waiting(world)
    return str(created.json()["id"])


async def slug_of(world: World, org: Any) -> str:  # noqa: ANN401 - Org
    rows = await world.sql("SELECT slug FROM tenants WHERE id = $1", org.tenant)
    return str(rows[0]["slug"])


async def test_a_new_tenant_shows_the_supportx_default(world: World) -> None:
    a = world.a
    found = await world.call("GET", "/organization/branding", a, a.tech_a)
    assert found.status_code == 200, found.text
    body = found.json()
    assert (body["customised"], body["primary_colour"], body["version"]) == (False, "#7e40d1", 0)
    assert body["logos"]["full"] is None
    assert found.headers["etag"] == '"0"'


async def test_an_unreadable_colour_is_refused_with_the_nearest_passing_one(world: World) -> None:
    a = world.a
    refused = await save(world, a, a.admin, 0, primary_colour="#1E90FF")
    assert problem(refused) == (422, "brand_colour_contrast")  # REQ-ADM-055 AC2
    params = refused.json()["params"]
    assert "text_on_primary" in params["checks"].split(",")
    suggestion = params["suggested_primary"]
    check = await world.call(
        "POST", "/organization/branding/check", a, a.admin, json={"primary_colour": suggestion}
    )
    assert check.status_code == 200, check.text
    assert check.json()["passes"] is True
    saved = await save(world, a, a.admin, 0, primary_colour=suggestion, product_name={"en": "Acme"})
    assert saved.status_code == 200, saved.text
    assert (saved.json()["primary_colour"], saved.json()["version"]) == (suggestion, 1)
    assert saved.headers["etag"] == '"1"'
    # Saved once more with the old version: someone else's change is never overwritten.
    stale = await save(world, a, a.admin, 0, primary_colour=suggestion)
    assert problem(stale) == (409, "version_conflict")


async def test_saving_writes_the_event_and_the_audit_entry(world: World) -> None:
    a = world.a
    saved = await save(world, a, a.admin, 0, primary_colour="#0b5394", portal_name={"en": "Help"})
    assert saved.status_code == 200, saved.text
    events = await world.sql(
        "SELECT event_type FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'organization.branding.changed'",
        a.tenant,
    )
    assert len(events) == 1
    assert "branding.updated" in await audit_actions(world, a)
    rows = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = 'branding.updated'",
        a.tenant,
    )
    assert "primary_colour" in str(rows[0]["details"])


async def test_texts_need_english_and_stay_within_limits(world: World) -> None:
    a = world.a
    refused = await save(
        world, a, a.admin, 0, product_name={"ar": "دعم"}, welcome_text={"en": "x" * 501}
    )
    assert refused.status_code == 422, refused.text
    codes = {(e["field"], e["code"]) for e in refused.json()["errors"]}
    assert ("product_name.en", "english_text_required") in codes
    assert ("welcome_text.en", "value_too_long") in codes


async def test_a_logo_makes_every_variant_served_publicly_and_cached(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    logo = await brand_upload(world, a, a.admin, logo_png())
    saved = await save(world, a, a.admin, 0, primary_colour="#0b5394", logo_file_id=logo)
    assert saved.status_code == 200, saved.text
    logos = saved.json()["logos"]
    for variant in ("full", "full_on_dark", "full_high_contrast", "favicon", "icon_512"):
        assert logos[variant], variant
    image = await world.client.get(logos["full"])
    assert image.status_code == 200, image.text
    assert image.headers["content-type"] == "image/png"
    assert "immutable" in image.headers["cache-control"]
    assert Image.open(io.BytesIO(image.content)).height <= 240
    favicon = await world.client.get(logos["favicon"])
    assert favicon.headers["content-type"] == "image/x-icon"
    # Not the current version: cached briefly only.
    stale = await world.client.get(logos["full"].split("?")[0] + "?v=old")
    assert "immutable" not in stale.headers["cache-control"]
    # The sign-in page's stylesheet carries the colours and the logo (REQ-SEC-003).
    slug = await slug_of(world, a)
    css = await world.client.get(f"/api/v1/public/branding/{slug}/login.css")
    assert css.status_code == 200, css.text
    assert css.headers["content-type"].startswith("text/css")
    assert "--pf-v5-global--primary-color--100: #0b5394;" in css.text
    assert logos["full"] in css.text


async def test_an_svg_or_broken_image_is_refused(world: World, files: FileServices) -> None:
    del files
    a = world.a
    broken = await brand_upload(world, a, a.admin, b"\x89PNG\r\n\x1a\nnot really a png" * 10)
    refused = await save(world, a, a.admin, 0, logo_file_id=broken)
    assert refused.status_code == 422, refused.text


async def test_only_brand_managers_upload_and_save(world: World, files: FileServices) -> None:
    del files
    a = world.a
    denied = await upload(world, a, a.tech_a, ("branding", a.tenant), logo_png(), "logo.png")
    assert problem(denied) == (403, "permission_denied")
    assert problem(await save(world, a, a.tech_a, 0, primary_colour="#0b5394")) == (
        403,
        "permission_denied",
    )
    assert (await settings(world, a, a.tech_a)).status_code == 403
    # Everyone signed in reads the brand their screens show.
    assert (await world.call("GET", "/organization/branding", a, a.requester)).status_code == 200


async def test_another_tenants_upload_cannot_become_your_logo(
    world: World, files: FileServices
) -> None:
    del files
    a, b = world.a, world.b
    theirs = await brand_upload(world, b, b.admin, logo_png())
    refused = await save(world, a, a.admin, 0, logo_file_id=theirs)
    assert refused.status_code == 404, refused.text
    # Uploading into another tenant's branding is refused too.
    across = await upload(world, a, a.admin, ("branding", b.tenant), logo_png(), "logo.png")
    assert across.status_code == 404, across.text


async def test_tenant_isolation_of_branding_and_domains(world: World) -> None:
    a, b = world.a, world.b
    assert (await save(world, a, a.admin, 0, primary_colour="#0b5394")).status_code == 200
    seen_by_b = await world.call("GET", "/organization/branding", b, b.admin)
    assert seen_by_b.json()["primary_colour"] == "#7e40d1"  # B still has the default
    for table in ("tenant_branding", "branding_assets", "tenant_domains"):
        rls = await world.sql(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = $1", table
        )
        assert (rls[0]["relrowsecurity"], rls[0]["relforcerowsecurity"]) == (True, True), table


async def test_the_address_picks_the_brand_and_an_unknown_one_shows_the_default(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = world.a
    assert (await save(world, a, a.admin, 0, primary_colour="#0b5394")).status_code == 200
    settings_ = world.app.state.settings.model_copy(update={"tenant_base_domain": "brand.test"})
    monkeypatch.setattr(world.app.state, "settings", settings_)
    slug = await slug_of(world, a)
    mine = await world.client.get("/api/v1/public/branding", headers={"Host": f"{slug}.brand.test"})
    assert mine.status_code == 200, mine.text
    assert (mine.json()["tenant_slug"], mine.json()["primary_colour"]) == (slug, "#0b5394")
    for host in ("nobody.brand.test", "elsewhere.example", "[::1]", "x"):
        other = await world.client.get("/api/v1/public/branding", headers={"Host": host})
        assert other.status_code == 200, (host, other.text)
        assert (other.json()["tenant_slug"], other.json()["primary_colour"]) == (None, "#7e40d1")
    # A verified custom domain resolves; a pending one does not (REQ-SEC-004).
    await world.sql(
        "INSERT INTO tenant_domains (id, tenant_id, host, status, verify_token)"
        " VALUES ($1, $2, 'help.acme.test', 'pending', 't')",
        uuid.uuid4(),
        a.tenant,
    )
    pending = await world.client.get("/api/v1/public/branding", headers={"Host": "help.acme.test"})
    assert pending.json()["tenant_slug"] is None
    await world.sql("UPDATE tenant_domains SET status = 'verified' WHERE host = 'help.acme.test'")
    verified = await world.client.get(
        "/api/v1/public/branding", headers={"Host": "Help.Acme.test:443"}
    )
    assert verified.json()["tenant_slug"] == slug


async def test_public_routes_never_list_or_guess(world: World) -> None:
    assert (await world.client.get("/api/v1/public/branding/no-such/login.css")).status_code == 404
    assert (await world.client.get("/api/v1/public/branding/x/../../etc")).status_code == 404
    slug = await slug_of(world, world.a)
    unknown = await world.client.get(f"/api/v1/public/branding/{slug}/secrets.txt")
    assert unknown.status_code == 404
