"""All of a record's files in one place, and several as one zip (WP-046a S2; REQ-INC-080).

Same world and real storage as test_files_api.py. Lane B's rules: the record must be visible
first (else 404, no file name); each file is checked again; ones left out are listed by ID and
reason in `manifest.txt`, never zipped; private notes' files never reach a requester, not even
by name; the zip is audited as a bulk export.
"""

import io
import uuid
import zipfile
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.shared.files.infra import blobs
from app.shared.files.infra.scanner import EICAR
from app.shared.files.service import archive_slots
from app.shared.files.service.core import FileServices
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_conversation_api import say
from tests.db.test_files_api import (
    audit_actions,
    files,
    record_files,
    scan_waiting,
    storage,
    upload,
)
from tests.db.test_incidents_api import CONSOLE, Org, World, problem

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["files", "module_world", "shared_world", "storage"]  # fixtures, re-used


async def _archive(
    world: World, org: Org, user: uuid.UUID, item: dict[str, Any], ids: list[str]
) -> httpx.Response:
    return await world.call(
        "POST",
        f"/files/records/incident/{item['id']}/archive",
        org,
        user,
        json={"file_ids": ids},
        headers=CONSOLE,
    )


async def _record_with_files(world: World, org: Org) -> tuple[dict[str, Any], list[str]]:
    item = await world.create(org, org.admin, group_id=str(org.ga))
    made = []
    for name, data in (("report.pdf", b"%PDF-1.4 one"), ("report.pdf", b"%PDF-1.4 two")):
        sent = await upload(world, org, org.admin, ("work_item", item["id"]), data, name)
        assert sent.status_code == 201, sent.text
        made.append(sent.json()["id"])
    await scan_waiting(world)
    return item, made


async def test_req_inc_080_ac2_picked_files_download_as_one_zip_with_a_manifest(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    item, ids = await _record_with_files(world, a)
    infected = await upload(world, a, a.admin, ("work_item", item["id"]), EICAR, "bad.txt")
    assert infected.status_code == 201, infected.text
    await scan_waiting(world)
    stranger = str(uuid.uuid4())
    got = await _archive(world, a, a.admin, item, [*ids, infected.json()["id"], stranger])
    assert got.status_code == 200, got.text
    assert got.headers["content-type"] == "application/zip"
    assert got.headers["cache-control"] == "no-store"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "attachment;" in got.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(got.content))
    names = archive.namelist()
    assert names[:2] == ["report.pdf", "report (2).pdf"]  # never one over the other
    assert archive.read("report.pdf") == b"%PDF-1.4 one"
    manifest = archive.read("manifest.txt").decode()
    assert stranger in manifest
    assert infected.json()["id"] in manifest
    assert "bad.txt" not in manifest  # by ID and reason only
    assert "file.archive_downloaded" in await audit_actions(world, a)


async def test_a_hidden_record_answers_404_with_no_file_name(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    item, ids = await _record_with_files(world, a)
    outside = await _archive(world, a, a.tech_b, item, ids)  # tech_b is not in GA
    assert problem(outside)[0] == 404, outside.text
    assert "content-disposition" not in outside.headers
    too_many = await _archive(world, a, a.admin, item, [str(uuid.uuid4()) for _ in range(201)])
    assert too_many.status_code == 422, too_many.text


async def test_a_requester_never_sees_a_private_note_s_files_not_even_by_name(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))  # a.requester raised it
    note = await say(world, a, a.admin, item, kind="note", visibility="private")
    assert note.status_code == 201, note.text
    secret = await upload(
        world, a, a.admin, ("conversation_entry", note.json()["entry"]["id"]), b"pay", "pay.txt"
    )
    assert secret.status_code == 201, secret.text
    await scan_waiting(world)
    listed = await world.call("GET", f"/files/records/incident/{item['id']}", a, a.requester)
    if listed.status_code == 200:
        assert "pay.txt" not in {f["name"] for f in listed.json()}
    staff = {f["name"] for f in await record_files(world, a, a.admin, item)}
    assert "pay.txt" in staff
    zipped = await _archive(world, a, a.requester, item, [secret.json()["id"]])
    if zipped.status_code == 200:
        archive = zipfile.ZipFile(io.BytesIO(zipped.content))
        assert archive.namelist() == ["manifest.txt"]
        assert "pay.txt" not in archive.read("manifest.txt").decode()
    else:
        assert zipped.status_code == 404, zipped.text


async def test_a_third_download_at_once_waits_and_another_person_is_unaffected(
    world: World, files: FileServices
) -> None:
    """Lane B: at most two archive downloads per person at once; 429 `archive_busy` past them.

    The test transport buffers each response, so two downloads are held running by taking
    their slots directly; the route then sees them as running.
    """
    del files
    a = world.a
    settings = world.app.state.settings
    item, ids = await _record_with_files(world, a)
    tokens = [await archive_slots.take(settings, a.tenant, a.admin) for _ in range(2)]
    assert all(t is not None for t in tokens)
    busy = await _archive(world, a, a.admin, item, ids)
    assert problem(busy) == (429, "archive_busy"), busy.text
    assert busy.headers["retry-after"] == "60"
    assert "content-disposition" not in busy.headers
    other = await _archive(world, a, a.tech_a, item, ids)  # tech_a works GA: unaffected
    assert other.status_code == 200, other.text
    first = tokens[0]
    assert first is not None
    await archive_slots.give_back(settings, a.tenant, a.admin, first)
    freed = await _archive(world, a, a.admin, item, ids)
    assert freed.status_code == 200, freed.text
    # The finished download gave its slot back: only the one still held remains.
    assert await _running(world, a.tenant, a.admin) == 1
    second = tokens[1]
    assert second is not None
    await archive_slots.give_back(settings, a.tenant, a.admin, second)
    # Keeping a slot alive never brings back one given back (ZADD XX).
    await archive_slots.keep(settings, a.tenant, a.admin, second)
    assert await _running(world, a.tenant, a.admin) == 0


async def test_a_read_failing_mid_stream_never_ends_as_a_whole_zip_and_frees_the_slot(
    world: World, files: FileServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lane B: fail closed. The second file's read fails: the body is no valid zip."""
    del files
    a = world.a
    item, ids = await _record_with_files(world, a)
    real = blobs.read
    calls = {"n": 0}

    def failing(*args: Any, **kwargs: Any) -> AsyncIterator[bytes]:  # noqa: ANN401 - passthrough
        calls["n"] += 1
        if calls["n"] == 1:
            first: AsyncIterator[bytes] = real(*args, **kwargs)
            return first

        async def broken() -> AsyncIterator[bytes]:
            yield b"partial"
            gone = "storage went away"
            raise OSError(gone)

        return broken()

    monkeypatch.setattr(blobs, "read", failing)  # the archive service reads through it
    got = await _archive(world, a, a.admin, item, ids)
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(got.content))
    assert calls["n"] == 2
    assert await _running(world, a.tenant, a.admin) == 0


async def _running(world: World, tenant: uuid.UUID, user: uuid.UUID) -> int:
    """Downloads holding a slot for the person now (archive_slots' sorted set)."""
    settings = world.app.state.settings
    client = archive_slots._client(settings)  # noqa: SLF001 - the module's own client, read only
    return int(await client.zcard(archive_slots._key(settings, tenant, user)))  # noqa: SLF001
