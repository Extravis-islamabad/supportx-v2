"""All of a record's files in one place, and several as one zip (WP-046a S2; REQ-INC-080).

Same world and real storage as test_files_api.py. Lane B's rules: the record must be visible
first (else 404, no file name); each file is checked again; ones left out are listed by ID and
reason in `manifest.txt`, never zipped; private notes' files never reach a requester, not even
by name; the zip is audited as a bulk export.
"""

import io
import uuid
import zipfile
from typing import Any

import httpx
import pytest

from app.shared.files.infra.scanner import EICAR
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
