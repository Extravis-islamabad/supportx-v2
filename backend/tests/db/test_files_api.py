"""Files and safe attachments over HTTP (WP-022; REQ-INC-079 AC1-AC4; D-082; ADR-028).

Same world as test_incidents_api.py. Files go to a fresh bucket on real S3-compatible storage
(MinIO in dev, SeaweedFS in CI); scanning uses the fake scanner (EICAR is malware), the real ClamAV
runs in the e2e job (D-082 D9). The scan consumer is driven by hand (`scan_waiting`).
"""

import base64
import io
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from PIL import Image
from sqlalchemy import select, text

from app.core.tenancy import TenantContext
from app.modules.system.service import files as system_files
from app.shared.files.infra.models import StoredFile
from app.shared.files.infra.scanner import EICAR, FakeScanner, NoScanner
from app.shared.files.keyring import KeyRing
from app.shared.files.ports import QuotaSource, register_quota
from app.shared.files.service.cleanup import purge_record
from app.shared.files.service.core import FileServices, rewrap_data_keys, rotate_data_key
from app.shared.storage import S3Storage
from tests.db.test_audit_exports import storage
from tests.db.test_conversation_api import say
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, role, world
from tooling import files_keys

if TYPE_CHECKING:
    from app.core.database import Database

__all__ = ["storage", "world"]  # fixtures, re-used

pytestmark = [pytest.mark.db]


# One key ring for the module: tenants' data keys outlive a single test.
KEYRING = KeyRing.parse(KeyRing.generate())


@pytest.fixture
async def files(world: World, storage: S3Storage) -> AsyncIterator[FileServices]:
    """The world's API and worker use real storage, the key ring and the fake scanner."""
    services = FileServices(storage=storage, keyring=KEYRING, scanner=FakeScanner())
    setattr(world.app.state, system_files.FILES_STATE, services)
    system_files.use_services(services)
    yield services
    system_files.use_services(None)
    register_quota(system_files.storage_limit_bytes)


def use(world: World, services: FileServices) -> None:
    setattr(world.app.state, system_files.FILES_STATE, services)
    system_files.use_services(services)


async def upload(
    world: World,
    org: Org,
    user: uuid.UUID,
    owner: tuple[str, uuid.UUID | str],
    data: bytes,
    name: str = "notes.txt",
    **params: Any,  # noqa: ANN401 - query parameters
) -> httpx.Response:
    owner_type, owner_id = owner
    return await world.call(
        "POST",
        "/files",
        org,
        user,
        params={"owner_type": owner_type, "owner_id": str(owner_id), "name": name, **params},
        content=data,
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def scan_waiting(world: World) -> None:
    """What the scan consumer and sweep do in the worker."""
    database: Database = world.app.state.db
    await system_files.scan_sweep(database, world.app.state.settings)


async def record_files(world: World, org: Org, user: uuid.UUID, item: dict[str, Any]) -> list[Any]:
    found = await world.call("GET", f"/files/records/incident/{item['id']}", org, user)
    assert found.status_code == 200, found.text
    return list(found.json())


async def open_file(
    world: World,
    org: Org,
    user: uuid.UUID,
    file_id: str,
    disposition: str = "attachment",
    **kw: Any,  # noqa: ANN401 - request options
) -> httpx.Response:
    link = await world.call(
        "POST", f"/files/{file_id}/link", org, user, json={"disposition": disposition}
    )
    if link.status_code != 200:
        return link
    url = link.json()["url"].removeprefix("/api/v1")
    return await world.call("GET", url, org, user, **kw)


async def audit_actions(world: World, org: Org) -> list[str]:
    rows = await world.sql(
        "SELECT action FROM audit_entries WHERE tenant_id = $1 ORDER BY occurred_at", org.tenant
    )
    return [r["action"] for r in rows]


# --- REQ-INC-079 ---------------------------------------------------------------------------------


async def test_upload_scan_and_download_with_a_short_lived_link(
    world: World, files: FileServices
) -> None:
    a = world.a
    item = await world.create(a, a.tech_a)
    data = ("مرحبا report line\n" * 5000).encode()
    created = await upload(world, a, a.tech_a, ("work_item", item["id"]), data, "تقرير.txt")
    assert created.status_code == 201, created.text
    stored = created.json()
    assert (stored["state"], stored["openable"], stored["name"]) == ("scanning", False, "تقرير.txt")
    assert stored["size"] == len(data)
    # While it is being checked nobody opens it (AC1's other half: only clean files open).
    assert problem(await open_file(world, a, a.tech_a, stored["id"])) == (409, "file_not_ready")
    await scan_waiting(world)
    listed = await record_files(world, a, a.tech_a, item)
    assert [(f["id"], f["state"], f["openable"]) for f in listed] == [(stored["id"], "clean", True)]
    whole = await open_file(world, a, a.tech_a, stored["id"])
    assert whole.status_code == 200, whole.text
    assert whole.content == data
    assert whole.headers["x-content-type-options"] == "nosniff"
    assert whole.headers["content-disposition"].startswith("attachment;")
    assert "filename*=UTF-8''" in whole.headers["content-disposition"]
    # A range (PDF viewers ask for these) decrypts only the chunks it touches.
    part = await open_file(world, a, a.tech_a, stored["id"], headers={"Range": "bytes=10-99"})
    assert part.status_code == 206
    assert part.content == data[10:100]
    assert part.headers["content-range"] == f"bytes 10-99/{len(data)}"
    # Stored encrypted: the bucket never holds the text.
    assert files.storage is not None
    raw = await files.storage.get(f"tenants/{a.tenant}/files/{stored['id']}")
    assert raw is not None
    assert b"report line" not in raw
    # Audited: the upload (download of a public file is not, D-082 D7).
    actions = await audit_actions(world, a)
    assert "file.uploaded" in actions
    assert "file.downloaded" not in actions


async def test_ac3_links_expire_and_belong_to_their_user(world: World, files: FileServices) -> None:
    a = world.a
    item = await world.create(a, a.tech_a)
    stored = (await upload(world, a, a.tech_a, ("work_item", item["id"]), b"hello")).json()
    await scan_waiting(world)
    link = await world.call("POST", f"/files/{stored['id']}/link", a, a.tech_a, json={})
    url = link.json()["url"].removeprefix("/api/v1")
    expires = datetime.fromisoformat(link.json()["expires_at"])
    assert timedelta(minutes=4) < expires - datetime.now(UTC) <= timedelta(minutes=5)
    # Someone else holding the URL gets nothing (the link is bound to its user).
    assert problem(await world.call("GET", url, a, a.admin)) == (404, "file_not_found")
    files_soon = FileServices(
        storage=files.storage,
        keyring=files.keyring,
        scanner=files.scanner,
        link_ttl=timedelta(seconds=-1),
    )
    use(world, files_soon)
    old = await world.call("POST", f"/files/{stored['id']}/link", a, a.tech_a, json={})
    expired = await world.call("GET", old.json()["url"].removeprefix("/api/v1"), a, a.tech_a)
    assert problem(expired) == (410, "file_link_expired")
    assert problem(await world.call("GET", "/files/content/forged.token", a, a.tech_a)) == (
        404,
        "file_not_found",
    )


async def test_ac1_an_infected_file_is_blocked_and_never_downloadable(
    world: World, files: FileServices
) -> None:
    a = world.a
    item = await world.create(a, a.tech_a)
    stored = (await upload(world, a, a.tech_a, ("work_item", item["id"]), EICAR, "x.txt")).json()
    await scan_waiting(world)
    found = await world.call("GET", f"/files/{stored['id']}", a, a.tech_a)
    assert (found.json()["state"], found.json()["openable"]) == ("infected", False)
    assert problem(await open_file(world, a, a.tech_a, stored["id"])) == (409, "file_not_ready")
    assert files.storage is not None
    assert await files.storage.get(f"tenants/{a.tenant}/files/{stored['id']}") is None
    assert "file.blocked" in await audit_actions(world, a)
    usage = await world.call("GET", "/files/settings/usage", a, a.admin)
    assert (usage.json()["bytes_used"], usage.json()["files"]) == (0, 0)
    # A rescan cannot bring it back.
    rescan = await world.call("POST", f"/files/{stored['id']}/rescan", a, a.admin)
    assert problem(rescan) == (422, "file_not_rescannable")


async def test_ac2_size_limit_refused_before_upload_with_the_limit(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    item = await world.create(a, a.tech_a)
    saved = await world.call(
        "PUT",
        "/files/settings/rules",
        a,
        a.admin,
        json={"max_file_mb": 1, "max_batch": 5, "blocked_extensions": ["exe"]},
        headers={"If-Match": '"0"'},
    )
    assert saved.status_code == 200, saved.text
    too_big = await upload(world, a, a.tech_a, ("work_item", item["id"]), b"x" * 1_000_001)
    assert problem(too_big) == (422, "file_too_large")
    assert too_big.json()["params"] == {"limit_mb": 1, "size_mb": 2}
    assert (await record_files(world, a, a.tech_a, item)) == []
    rules = await world.call("GET", "/files/settings/rules", a, a.tech_a)
    assert rules.json()["max_file_mb"] == 1  # everyone reads the rules, to refuse early in the UI
    assert "file_settings.changed" in await audit_actions(world, a)
    stale = await world.call(
        "PUT",
        "/files/settings/rules",
        a,
        a.admin,
        json={"max_file_mb": 2, "max_batch": 5, "blocked_extensions": []},
        headers={"If-Match": '"0"'},
    )
    assert stale.status_code == 409
    over = await world.call(
        "PUT",
        "/files/settings/rules",
        a,
        a.admin,
        json={"max_file_mb": 101, "max_batch": 5, "blocked_extensions": []},
        headers={"If-Match": '"1"'},
    )
    assert over.status_code == 422  # D-082 D7: at most 100 MB
    refused = await world.call("GET", "/files/settings/usage", a, a.tech_a)
    assert refused.status_code == 403  # files.manage only


async def test_dangerous_types_blocked_by_name_and_by_real_type(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    item = await world.create(a, a.tech_a)
    owner = ("work_item", item["id"])
    for name in ("setup.exe", "run.bat", "x.js", "deploy.sh", "tool.ps1", "app.jar", "a.vbs"):
        refused = await upload(world, a, a.tech_a, owner, b"echo hi", name)
        assert problem(refused) == (422, "file_type_blocked"), name
    renamed = await upload(world, a, a.tech_a, owner, b"MZ\x90\x00" + b"\x00" * 100, "cat.jpg")
    assert problem(renamed) == (422, "file_type_blocked")
    assert renamed.json()["params"]["reason"] == "blocked_content"
    script = await upload(world, a, a.tech_a, owner, b"#!/bin/sh\nrm -rf /", "readme.txt")
    assert problem(script) == (422, "file_type_blocked")
    # The list is the tenant's (D-082): an administrator may allow executables knowingly.
    saved = await world.call(
        "PUT",
        "/files/settings/rules",
        a,
        a.admin,
        json={"max_file_mb": 25, "max_batch": 20, "blocked_extensions": ["bat"]},
        headers={"If-Match": '"0"'},
    )
    assert saved.status_code == 200
    allowed = await upload(world, a, a.tech_a, owner, b"MZ\x90\x00", "tool.exe")
    assert allowed.status_code == 201, allowed.text


async def test_private_note_files_are_for_staff_only(world: World, files: FileServices) -> None:
    del files
    a = world.a
    viewer = await role(world, a, "Viewer", [("incidents.view", "all")])
    assigned = await world.call("PUT", f"/users/{a.requester2}/roles/{viewer}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    item = await world.create(a, a.tech_a)
    note = await say(world, a, a.tech_a, item, kind="note", visibility="private")
    assert note.status_code == 201, note.text
    reply = await say(world, a, a.tech_a, item, kind="reply", visibility="public", to=["x@y.test"])
    assert reply.status_code == 201, reply.text
    secret = await upload(
        world,
        a,
        a.tech_a,
        ("conversation_entry", note.json()["entry"]["id"]),
        b"payroll",
        "pay.txt",
    )
    public = await upload(
        world,
        a,
        a.tech_a,
        ("conversation_entry", reply.json()["entry"]["id"]),
        b"guide",
        "guide.txt",
    )
    assert secret.status_code == 201, secret.text
    assert public.status_code == 201, public.text
    await scan_waiting(world)
    staff = {f["name"] for f in await record_files(world, a, a.tech_a, item)}
    assert staff == {"pay.txt", "guide.txt"}
    seen = {f["name"] for f in await record_files(world, a, a.requester2, item)}
    assert seen == {"guide.txt"}
    for path in (f"/files/{secret.json()['id']}", f"/files/{secret.json()['id']}/link"):
        method = "POST" if path.endswith("link") else "GET"
        assert problem(await world.call(method, path, a, a.requester2, json={})) == (
            404,
            "file_not_found",
        )
    # Staff opening a private note's file is an audited read (D-082 D7).
    opened = await open_file(world, a, a.tech_a, secret.json()["id"])
    assert opened.status_code == 200
    assert "file.downloaded" in await audit_actions(world, a)
    # The viewer may not attach to the private note either (it is hidden from them).
    attach = await upload(
        world, a, a.requester2, ("conversation_entry", note.json()["entry"]["id"]), b"x", "x.txt"
    )
    assert problem(attach) == (404, "file_owner_not_found")


async def test_other_tenants_and_hidden_records_see_nothing(
    world: World, files: FileServices
) -> None:
    del files
    a, b = world.a, world.b
    item = await world.create(a, a.tech_a)
    stored = (await upload(world, a, a.tech_a, ("work_item", item["id"]), b"alpha")).json()
    assert problem(await world.call("GET", f"/files/{stored['id']}", b, b.admin)) == (
        404,
        "file_not_found",
    )
    hidden = await world.call("GET", f"/files/records/incident/{item['id']}", b, b.admin)
    assert hidden.status_code == 404
    # tech_b (group GB, site S2) cannot see tech_a's group incident, nor its files.
    assert problem(await world.call("GET", f"/files/{stored['id']}", a, a.tech_b)) == (
        404,
        "file_not_found",
    )


async def test_rls_keeps_file_tables_per_tenant(world: World, files: FileServices) -> None:
    del files
    a, b = world.a, world.b
    item = await world.create(a, a.tech_a)
    await upload(world, a, a.tech_a, ("work_item", item["id"]), b"alpha")
    database: Database = world.app.state.db
    for table in ("files", "file_links", "tenant_data_keys", "tenant_storage_usage"):
        async with database.tenant_session(TenantContext(b.tenant)) as session:
            assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar() == 0  # noqa: S608 - fixed table names
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            mine = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()  # noqa: S608
            assert mine is not None
            assert mine >= 1
    async with database.tenant_session(TenantContext(b.tenant)) as session:
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text("INSERT INTO file_settings (tenant_id, blocked_extensions) VALUES (:t, '{}')"),
                {"t": a.tenant},
            )


async def test_quota_refuses_uploads_beyond_the_limit(world: World, files: FileServices) -> None:
    del files
    a = world.a
    item = await world.create(a, a.tech_a)

    def limit(size: int) -> QuotaSource:
        async def source(session: Any) -> int | None:  # noqa: ANN401 - AsyncSession
            del session
            return size

        return source

    register_quota(limit(10))
    assert (
        await upload(world, a, a.tech_a, ("work_item", item["id"]), b"0123456789")
    ).status_code == 201
    full = await upload(world, a, a.tech_a, ("work_item", item["id"]), b"x")
    assert problem(full) == (403, "storage_quota_exceeded")
    usage = await world.call("GET", "/files/settings/usage", a, a.admin)
    assert usage.json() == {"bytes_used": 10, "files": 1, "limit_bytes": 10}


async def test_editor_drafts_are_private_until_attached(world: World, files: FileServices) -> None:
    del files
    a = world.a
    item = await world.create(a, a.tech_a)
    draft = await upload(
        world,
        a,
        a.tech_a,
        ("draft", a.tech_a),
        b"\x89PNG\r\n\x1a\n" + b"0" * 64,
        "shot.png",
        inline="true",
    )
    assert draft.status_code == 201, draft.text
    other = await upload(world, a, a.tech_c, ("draft", a.tech_a), b"x")
    assert problem(other) == (404, "file_owner_not_found")  # drafts belong to their uploader
    assert problem(await world.call("GET", f"/files/{draft.json()['id']}", a, a.tech_c)) == (
        404,
        "file_not_found",
    )
    note = await say(world, a, a.tech_a, item, kind="note", visibility="public")
    stolen = await world.call(
        "POST",
        "/files/attach",
        a,
        a.tech_c,
        json={
            "owner_type": "conversation_entry",
            "owner_id": note.json()["entry"]["id"],
            "file_ids": [draft.json()["id"]],
        },
    )
    assert stolen.json() == []  # someone else's draft is not theirs to attach
    attached = await world.call(
        "POST",
        "/files/attach",
        a,
        a.tech_a,
        json={
            "owner_type": "conversation_entry",
            "owner_id": note.json()["entry"]["id"],
            "file_ids": [draft.json()["id"]],
        },
    )
    assert attached.json() == [draft.json()["id"]]
    listed = await record_files(world, a, a.tech_c, item)
    assert [(f["owner_type"], f["inline"]) for f in listed] == [("conversation_entry", True)]


async def test_delete_then_purge_after_the_grace_period(world: World, files: FileServices) -> None:
    a = world.a
    item = await world.create(a, a.tech_a)
    stored = (await upload(world, a, a.tech_a, ("work_item", item["id"]), b"gone soon")).json()
    deleted = await world.call("DELETE", f"/files/{stored['id']}", a, a.tech_a)
    assert deleted.status_code == 204
    assert await record_files(world, a, a.tech_a, item) == []
    assert "file.deleted" in await audit_actions(world, a)
    database: Database = world.app.state.db
    await system_files.purge(database, world.app.state.settings)
    assert files.storage is not None
    key = f"tenants/{a.tenant}/files/{stored['id']}"
    assert await files.storage.get(key) is not None  # still inside the 24 h undo window
    await world.sql(
        "UPDATE files SET purge_after = now() - interval '1 minute' WHERE id = $1",
        uuid.UUID(stored["id"]),
    )
    await system_files.purge(database, world.app.state.settings)
    assert await files.storage.get(key) is None
    async with database.tenant_session(TenantContext(a.tenant)) as session:
        assert (
            await session.scalar(select(StoredFile).where(StoredFile.id == uuid.UUID(stored["id"])))
            is None
        )
    usage = await world.call("GET", "/files/settings/usage", a, a.admin)
    assert (usage.json()["bytes_used"], usage.json()["files"]) == (0, 0)
    assert "file.purged" in await audit_actions(world, a)


def _photo_with_gps() -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x8825] = {2: (51.0, 30.0, 0.0)}
    out = io.BytesIO()
    Image.new("RGB", (1200, 800), "orange").save(out, "JPEG", exif=exif, comment=b"serial 42")
    return out.getvalue()


async def test_images_lose_their_metadata_and_get_a_thumbnail(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    item = await world.create(a, a.tech_a)
    photo = _photo_with_gps()
    stored = (
        await upload(world, a, a.tech_a, ("work_item", item["id"]), photo, "photo.jpg")
    ).json()
    await scan_waiting(world)
    found = (await world.call("GET", f"/files/{stored['id']}", a, a.tech_a)).json()
    assert (found["previewable"], found["has_thumbnail"]) == (True, True)
    inline = await world.call("GET", f"/files/{stored['id']}/inline", a, a.tech_a)
    assert inline.status_code == 200
    assert b"serial 42" not in inline.content
    with Image.open(io.BytesIO(inline.content)) as cleaned:
        assert 0x8825 not in cleaned.getexif()  # GPS gone (D-082 D4)
        assert cleaned.getexif().get(0x0112) == 6  # orientation kept
    thumb = await world.call("GET", f"/files/{stored['id']}/thumbnail", a, a.tech_a)
    assert thumb.status_code == 200
    assert thumb.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(thumb.content)) as small:
        assert max(small.size) <= 320
    preview = await open_file(world, a, a.tech_a, stored["id"], disposition="inline")
    assert preview.headers["content-disposition"].startswith("inline;")
    assert preview.headers["content-type"] == "image/jpeg"


async def test_markup_is_never_served_inline(world: World, files: FileServices) -> None:
    del files
    a = world.a
    item = await world.create(a, a.tech_a)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    stored = (await upload(world, a, a.tech_a, ("work_item", item["id"]), svg, "logo.svg")).json()
    await scan_waiting(world)
    found = (await world.call("GET", f"/files/{stored['id']}", a, a.tech_a)).json()
    assert found["previewable"] is False
    opened = await open_file(world, a, a.tech_a, stored["id"], disposition="inline")
    assert opened.headers["content-disposition"].startswith("attachment;")
    assert opened.headers["content-type"] == "application/octet-stream"
    assert "sandbox" in opened.headers["content-security-policy"]
    inline = await world.call("GET", f"/files/{stored['id']}/inline", a, a.tech_a)
    assert inline.status_code == 404


async def test_without_a_scanner_files_wait_and_admins_are_warned(
    world: World, files: FileServices
) -> None:
    a = world.a
    use(world, FileServices(storage=files.storage, keyring=files.keyring, scanner=NoScanner()))
    item = await world.create(a, a.tech_a)
    stored = (await upload(world, a, a.tech_a, ("work_item", item["id"]), b"hi")).json()
    await scan_waiting(world)
    assert (await world.call("GET", f"/files/{stored['id']}", a, a.tech_a)).json()[
        "state"
    ] == "scanning"
    status = (await world.call("GET", "/files/settings/status", a, a.admin)).json()
    assert status["warnings"] == ["scanner_not_installed"]
    assert (status["scan_required"], status["waiting"]) == (True, 1)
    # Scanning not required (an operator's knowing choice): files show "not scanned" and open.
    relaxed = FileServices(
        storage=files.storage, keyring=files.keyring, scanner=NoScanner(), scan_required=False
    )
    use(world, relaxed)
    later = (await upload(world, a, a.tech_a, ("work_item", item["id"]), b"later")).json()
    assert later["state"] == "not_scanned"
    assert later["openable"] is True
    status = (await world.call("GET", "/files/settings/status", a, a.admin)).json()
    assert "files_not_scanned" in status["warnings"]
    # The scanner comes back: the waiting file is checked by the sweep.
    use(world, files)
    await scan_waiting(world)
    assert (await world.call("GET", f"/files/{stored['id']}", a, a.tech_a)).json()[
        "state"
    ] == "clean"


async def test_stale_signatures_and_an_unreachable_scanner_are_warned(
    world: World, files: FileServices
) -> None:
    a = world.a
    old = FakeScanner(signature_date=datetime.now(UTC) - timedelta(days=8))
    use(world, FileServices(storage=files.storage, keyring=files.keyring, scanner=old))
    status = (await world.call("GET", "/files/settings/status", a, a.admin)).json()
    assert status["warnings"] == ["signatures_stale"]
    down = FakeScanner(down=True)
    use(world, FileServices(storage=files.storage, keyring=files.keyring, scanner=down))
    item = await world.create(a, a.tech_a)
    stored = (await upload(world, a, a.tech_a, ("work_item", item["id"]), b"hi")).json()
    for _ in range(3):  # three attempts, then "could not be checked"
        await scan_waiting(world)
    found = (await world.call("GET", f"/files/{stored['id']}", a, a.tech_a)).json()
    assert found["state"] == "scan_failed"
    status = (await world.call("GET", "/files/settings/status", a, a.admin)).json()
    assert set(status["warnings"]) == {"scanner_unreachable", "files_scan_failed"}
    use(world, files)
    again = await world.call("POST", f"/files/{stored['id']}/rescan", a, a.admin)
    assert again.json()["state"] == "scanning"
    await scan_waiting(world)
    assert (await world.call("GET", f"/files/{stored['id']}", a, a.tech_a)).json()[
        "state"
    ] == "clean"


async def test_uploads_are_idempotent_and_emit_events(world: World, files: FileServices) -> None:
    del files
    a = world.a
    item = await world.create(a, a.tech_a)
    key = str(uuid.uuid4())

    async def send() -> httpx.Response:
        return await world.call(
            "POST",
            "/files",
            a,
            a.tech_a,
            params={"owner_type": "work_item", "owner_id": item["id"], "name": "a.txt"},
            content=b"same",
            headers={"Idempotency-Key": key, **CONSOLE},
        )

    first, second = await send(), await send()
    assert first.json()["id"] == second.json()["id"]
    assert second.headers.get("idempotent-replayed") == "true"
    rows = await world.sql(
        "SELECT envelope->>'event_type' AS t FROM outbox_events WHERE tenant_id = $1 "
        "AND envelope->>'aggregate_type' = 'file'",
        a.tenant,
    )
    assert [r["t"] for r in rows] == ["system.file.uploaded"]


async def test_storage_or_keys_missing_is_said_not_silent(
    world: World, files: FileServices
) -> None:
    a = world.a
    item = await world.create(a, a.tech_a)
    use(world, FileServices(storage=files.storage, keyring=None, scanner=FakeScanner()))
    refused = await upload(world, a, a.tech_a, ("work_item", item["id"]), b"x")
    assert problem(refused) == (503, "files_not_configured")
    use(world, FileServices(storage=None, keyring=files.keyring, scanner=FakeScanner()))
    refused = await upload(world, a, a.tech_a, ("work_item", item["id"]), b"x")
    assert problem(refused) == (503, "storage_not_configured")


Check = Callable[[], None]


async def test_key_rotation_keeps_old_files_readable(world: World, files: FileServices) -> None:
    """D-082 D2: rotate the tenant key and the installation key; every file still opens."""
    a = world.a
    item = await world.create(a, a.tech_a)
    old = (await upload(world, a, a.tech_a, ("work_item", item["id"]), b"before")).json()
    database: Database = world.app.state.db
    assert files.keyring is not None
    async with database.tenant_session(TenantContext(a.tenant)) as session:
        await rotate_data_key(session, files.keyring)
    new = (await upload(world, a, a.tech_a, ("work_item", item["id"]), b"after")).json()
    # A new installation key first; the old one stays listed so it can still unwrap.
    previous = base64.b64encode(files.keyring.keys[files.keyring.active_id]).decode()
    rotated_ring = KeyRing.parse(f"{KeyRing.generate('k2')}, {files.keyring.active_id}:{previous}")
    rotated = FileServices(storage=files.storage, keyring=rotated_ring, scanner=files.scanner)
    use(world, rotated)
    async with database.tenant_session(TenantContext(a.tenant)) as session:
        assert await rewrap_data_keys(session, rotated_ring) >= 2
    # After the re-wrap the old installation key is no longer needed.
    only_new = KeyRing.parse(f"k2:{base64.b64encode(rotated_ring.keys['k2']).decode()}")
    use(world, FileServices(storage=files.storage, keyring=only_new, scanner=files.scanner))
    await scan_waiting(world)
    for stored, expected in ((old, b"before"), (new, b"after")):
        opened = await open_file(world, a, a.tech_a, stored["id"])
        assert opened.status_code == 200, opened.text
        assert opened.content == expected
    # Tenants outlive this test: move their keys back under the module's key ring.
    back = KeyRing.parse(
        f"{KEYRING.active_id}:{base64.b64encode(KEYRING.keys[KEYRING.active_id]).decode()}, "
        f"k2:{base64.b64encode(rotated_ring.keys['k2']).decode()}"
    )
    async with database.tenant_session(TenantContext(a.tenant)) as session:
        await rewrap_data_keys(session, back)


async def test_a_purged_record_takes_its_files_along(world: World, files: FileServices) -> None:
    """D-077 applied to files: purging a record removes its files, objects and usage."""
    a = world.a
    item = await world.create(a, a.tech_a)
    note = await say(world, a, a.tech_a, item, kind="note", visibility="private")
    await upload(world, a, a.tech_a, ("work_item", item["id"]), b"one")
    await upload(world, a, a.tech_a, ("conversation_entry", note.json()["entry"]["id"]), b"two")
    database: Database = world.app.state.db
    async with database.tenant_session(TenantContext(a.tenant)) as session:
        result = await purge_record(session, files, "incident", uuid.UUID(item["id"]))
    assert (result.files, result.bytes, result.left) == (2, 6, 0)
    assert files.storage is not None
    for file_id in result.file_ids:
        assert await files.storage.get(f"tenants/{a.tenant}/files/{file_id}") is None
    assert await record_files(world, a, a.tech_a, item) == []


async def test_ac4_a_pdf_previews_in_the_browser(world: World, files: FileServices) -> None:
    del files
    a = world.a
    item = await world.create(a, a.tech_a)
    pdf = b"%PDF-1.4\n" + b"0" * 3000 + b"\n%%EOF"
    stored = (await upload(world, a, a.tech_a, ("work_item", item["id"]), pdf, "plan.pdf")).json()
    await scan_waiting(world)
    found = (await world.call("GET", f"/files/{stored['id']}", a, a.tech_a)).json()
    assert (found["kind"], found["previewable"]) == ("pdf", True)
    preview = await open_file(world, a, a.tech_a, stored["id"], disposition="inline")
    assert preview.headers["content-type"] == "application/pdf"
    assert preview.headers["content-disposition"].startswith("inline;")
    # Browsers do not open their PDF viewer in a sandboxed document; scripts stay off anyway.
    assert "sandbox" not in preview.headers["content-security-policy"]
    assert "default-src 'none'" in preview.headers["content-security-policy"]
    page = await open_file(
        world, a, a.tech_a, stored["id"], disposition="inline", headers={"Range": "bytes=0-7"}
    )
    assert (page.status_code, page.content) == (206, b"%PDF-1.4")


async def test_operator_key_commands_check_rotate_and_rewrap(
    world: World, files: FileServices
) -> None:
    """tooling/files_keys: after a restore `check` names a missing installation key."""
    a = world.a
    item = await world.create(a, a.tech_a)
    await upload(world, a, a.tech_a, ("work_item", item["id"]), b"kept")
    database: Database = world.app.state.db
    assert files.keyring is not None
    checked = await files_keys.run(database, files.keyring, "check")
    assert checked.ok
    assert checked.done[a.tenant] >= 1
    rotated = await files_keys.run(database, files.keyring, "rotate")
    assert rotated.ok
    # Restored without the installation key that wrapped the data keys: named, not a crash.
    stranger = KeyRing.parse(KeyRing.generate("k9"))
    broken = await files_keys.run(database, stranger, "check")
    assert not broken.ok
    assert "not in the key ring" in broken.failed[a.tenant]


async def test_streamed_upload_creates_a_missing_bucket(storage: S3Storage) -> None:
    """A fresh installation or dev stack has no bucket yet: the first upload creates it, as
    `put` does (CI e2e found uploads refused with storage_unavailable on a new MinIO)."""
    for size in (3, 6 << 20):  # one PUT, and multipart
        fresh = S3Storage(
            storage.endpoint,
            storage.region,
            storage.access_key,
            storage.secret_key,
            f"sx-test-{uuid.uuid4().hex[:12]}",
            5,
        )

        async def parts(total: int = size) -> AsyncIterator[bytes]:
            yield b"x" * total

        try:
            assert await fresh.put_stream("first", parts(), "application/octet-stream") == size
            assert await fresh.get("first") == b"x" * size
        finally:
            await fresh.delete("first")
            async with fresh._client() as client:  # noqa: SLF001 - test cleanup of its own bucket
                await client.delete_bucket(Bucket=fresh.bucket)
