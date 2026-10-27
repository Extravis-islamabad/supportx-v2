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

from app.core.tenancy import TenantContext
from app.modules.organization import email_branding, header_html
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
    # Loaded by the sign-in page (another origin) and mail clients.
    assert image.headers["cross-origin-resource-policy"] == "cross-origin"
    assert Image.open(io.BytesIO(image.content)).height <= 240
    favicon = await world.client.get(logos["favicon"])
    assert favicon.headers["content-type"] == "image/x-icon"
    # Not the current version: cached briefly only.
    stale = await world.client.get(logos["full"].split("?")[0] + "?v=old")
    assert "immutable" not in stale.headers["cache-control"]
    # The sign-in page's stylesheet carries the colours and the logo (REQ-SEC-003).
    css = await world.client.get(f"/api/v1/public/branding/{a.tenant}/login.css")
    assert css.status_code == 200, css.text
    assert css.headers["content-type"].startswith("text/css")
    assert css.headers["cross-origin-resource-policy"] == "cross-origin"
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

    async def colour(host: str) -> str:
        found = await world.client.get("/api/v1/public/branding", headers={"Host": host})
        assert found.status_code == 200, (host, found.text)
        return str(found.json()["primary_colour"])

    assert await colour(f"{slug}.brand.test") == "#0b5394"
    for host in ("nobody.brand.test", "elsewhere.example", "[::1]", "x"):
        assert await colour(host) == "#7e40d1", host
    # A verified custom domain resolves; a pending one does not (REQ-SEC-004).
    await world.sql(
        "INSERT INTO tenant_domains (id, tenant_id, host, status, verify_token)"
        " VALUES ($1, $2, 'help.acme.test', 'pending', 't')",
        uuid.uuid4(),
        a.tenant,
    )
    assert await colour("help.acme.test") == "#7e40d1"
    await world.sql("UPDATE tenant_domains SET status = 'verified' WHERE host = 'help.acme.test'")
    assert await colour("Help.Acme.test:443") == "#0b5394"


PUBLIC_KEYS = {"customised", "primary_colour", "gradient", "logos"}
LOGO_KEYS = {
    "full",
    "full_on_dark",
    "full_high_contrast",
    "icon",
    "icon_high_contrast",
    "favicon",
    "apple_touch_icon",
    "icon_192",
    "icon_512",
}


async def test_the_public_brand_tells_only_logo_and_colours_and_cannot_find_tenants(
    world: World, files: FileServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP-017 review: nothing beyond the address's own logo and colours; no list, no probing."""
    del files
    a, b = world.a, world.b
    logo = await brand_upload(world, a, a.admin, logo_png())
    saved = await save(
        world,
        a,
        a.admin,
        0,
        primary_colour="#0b5394",
        logo_file_id=logo,
        product_name={"en": "Secret Product Name"},
        portal_name={"en": "Secret Portal"},
        welcome_text={"en": "Secret welcome"},
    )
    assert saved.status_code == 200, saved.text
    settings_ = world.app.state.settings.model_copy(update={"tenant_base_domain": "brand.test"})
    monkeypatch.setattr(world.app.state, "settings", settings_)
    slug_a, slug_b = await slug_of(world, a), await slug_of(world, b)

    # 1. The address's own logo and colours, nothing else: no names, texts, slug, IDs or files.
    mine = await world.client.get(
        "/api/v1/public/branding", headers={"Host": f"{slug_a}.brand.test"}
    )
    body = mine.json()
    assert set(body) == PUBLIC_KEYS
    assert set(body["logos"]) == LOGO_KEYS
    text = mine.text
    for secret in ("Secret", slug_a, str(logo), "version", "tenant", "file_id"):
        assert secret not in text, secret
    for url in filter(None, body["logos"].values()):
        assert url.startswith(f"/api/v1/public/branding/{a.tenant}/")  # its own images only
    # Another tenant's address gives that tenant's (default) brand, never A's.
    theirs = await world.client.get(
        "/api/v1/public/branding", headers={"Host": f"{slug_b}.brand.test"}
    )
    assert theirs.json() == {**theirs.json(), "customised": False, "primary_colour": "#7e40d1"}
    assert str(a.tenant) not in theirs.text
    unknown_host = await world.client.get(
        "/api/v1/public/branding", headers={"Host": "x.brand.test"}
    )
    assert unknown_host.json() == theirs.json()  # an unbranded tenant looks like no tenant at all

    # 2. The stylesheet: an unknown, malformed or slug key gets exactly an unbranded tenant's.
    unbranded = (await world.client.get(f"/api/v1/public/branding/{b.tenant}/login.css")).text
    for key in (uuid.uuid4(), "not-a-uuid", slug_a, slug_b, "%00", "1" * 36):
        probe = await world.client.get(f"/api/v1/public/branding/{key}/login.css")
        assert probe.status_code == 200, key
        assert probe.text == unbranded, key
    branded = (await world.client.get(f"/api/v1/public/branding/{a.tenant}/login.css")).text
    assert "#0b5394" in branded
    assert "Secret" not in branded

    # 3. Images: one and the same 404 for an unknown tenant, a slug, a missing image or a name.
    expected = await world.client.get(f"/api/v1/public/branding/{b.tenant}/logo.png")
    for path in (
        f"{uuid.uuid4()}/logo.png",
        f"{slug_a}/logo.png",
        f"{a.tenant}/secrets.txt",
        f"{b.tenant}/favicon.ico",
    ):
        probe = await world.client.get(f"/api/v1/public/branding/{path}")
        assert probe.status_code == 404, path
        assert probe.json()["code"] == expected.json()["code"] == "branding_not_found", path

    # 4. No listing or settings route exists without signing in.
    slash = await world.client.get("/api/v1/public/branding/", follow_redirects=True)
    assert set(slash.json()) == PUBLIC_KEYS  # the address's own brand again, nothing more
    assert (await world.client.get(f"/api/v1/public/branding/{a.tenant}")).status_code == 404
    assert (await world.client.get("/api/v1/organization/branding/settings")).status_code == 401
    assert (await world.client.get("/api/v1/organization/domains")).status_code == 401


async def test_only_the_public_stylesheet_and_images_may_be_used_cross_origin(
    world: World, files: FileServices
) -> None:
    """WP-017 review: `Cross-Origin-Resource-Policy: cross-origin` on these two only."""
    del files
    a = world.a
    logo = await brand_upload(world, a, a.admin, logo_png())
    saved = await save(world, a, a.admin, 0, logo_file_id=logo)
    assert saved.status_code == 200, saved.text
    image = saved.json()["logos"]["full"]
    cross = [f"/api/v1/public/branding/{a.tenant}/login.css", image]
    for path in cross:
        found = await world.client.get(path)
        assert found.status_code == 200, path
        assert found.headers["cross-origin-resource-policy"] == "cross-origin", path
    same_origin = [
        ("GET", "/api/v1/public/branding", None),
        ("GET", f"/api/v1/public/branding/{a.tenant}/nothing.png", None),  # a 404
        ("GET", "/api/v1/public/domain-check/tok", None),
        ("GET", "/api/v1/health", None),
        ("GET", "/api/v1/auth/me", None),  # a 401
        ("GET", "/api/v1/organization/branding", a.admin),
        ("GET", SETTINGS, a.admin),
        ("POST", "/organization/branding/check", a.admin),
        ("GET", "/api/v1/organization/domains", a.admin),
        ("GET", f"/files/{logo}", a.admin),
        ("GET", "/api/v1/incidents", a.admin),
    ]
    for method, path, user in same_origin:
        if user is None:
            found = await world.client.request(method, path)
        else:
            found = await world.call(
                method, path.removeprefix("/api/v1"), a, user, json={} if method == "POST" else None
            )
        assert found.headers["cross-origin-resource-policy"] == "same-origin", (
            path,
            found.status_code,
        )


async def test_emails_get_absolute_public_logo_urls_and_the_tenant_name(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    logo = await brand_upload(world, a, a.admin, logo_png())
    saved = await save(
        world,
        a,
        a.admin,
        0,
        logo_file_id=logo,
        product_name={"en": "Acme <Desk>", "ar": "مكتب أكمي"},
    )
    assert saved.status_code == 200, saved.text
    settings_ = world.app.state.settings.model_copy(
        update={"tenant_base_domain": "brand.test", "console_url": "https://x.example"}
    )
    slug = await slug_of(world, a)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        english = await email_branding(session, settings_, a.tenant, "en")
        arabic = await email_branding(session, settings_, a.tenant, "ar")
        urdu = await email_branding(session, settings_, a.tenant, "ur")
    assert english.logo_url is not None
    assert english.logo_url.startswith(
        f"https://{slug}.brand.test/api/v1/public/branding/{a.tenant}/"
    )
    assert english.portal_url == f"https://{slug}.brand.test/"
    assert (arabic.product_name, urdu.product_name) == ("مكتب أكمي", "Acme <Desk>")
    html = header_html(english)
    assert "Acme &lt;Desk&gt;" in html
    assert "<Desk>" not in html
