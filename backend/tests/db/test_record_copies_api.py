"""Copying an incident one or more times over HTTP (WP-046a S5c; REQ-INC-033).

Each copy is a new record through the same create, its history naming the original, its
subject marked as a copy. Tasks come when chosen, as new open tasks; conversations, worklogs and
history never do (AC2). How many at once is limited, and the refusal says the limit (AC3).
"""

import json
import time
import uuid
from typing import Any

import httpx
import pytest

from app.core.errors import NotFound
from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.shared.files.infra.scanner import EICAR
from app.shared.files.ports import OwnerType
from app.shared.files.service.copies import copy_to_records
from app.shared.files.service.core import MB, FileServices
from app.shared.storage import S3Storage
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_conversation_api import say
from tests.db.test_files_api import files, record_files, scan_waiting, storage, upload
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, field_codes, problem
from tests.db.test_parts_api import add_task, tasks

pytestmark = MODULE_LOOP

__all__ = ["files", "module_world", "shared_world", "storage"]  # fixtures, re-used

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


async def copy(
    world: World,
    org: Org,
    user: uuid.UUID,
    item: dict[str, Any],
    **body: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "POST",
        f"{BASE}/{item['id']}/copies",
        org,
        user,
        json=body,
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def test_req_inc_033_ac1_two_copies_name_the_original(world: World) -> None:
    a = world.a
    original = await world.create(
        a, a.admin, subject="Printer jammed", impact="team", tags=["printer"]
    )
    made = await copy(world, a, a.admin, original, count=2)
    assert made.status_code == 201, made.text
    copies = made.json()["items"]
    assert [c["subject"] for c in copies] == [
        "Copy 1 of: Printer jammed",
        "Copy 2 of: Printer jammed",
    ]
    for c in copies:
        assert c["id"] != original["id"]
        assert c["display_id"] != original["display_id"]
        assert (c["impact"], c["tags"], c["requester_id"]) == (
            "team",
            ["printer"],
            original["requester_id"],
        )
        history = await world.history(a, c)
        changes = [ch for e in history for ch in e.get("changes", [])]
        assert any(
            ch["field"] == "copied_from" and ch["new"] == original["display_id"] for ch in changes
        ), history


async def test_req_inc_033_ac2_tasks_when_chosen_never_the_conversation(world: World) -> None:
    a = world.a
    original = await world.create(a, a.admin, group_id=str(a.ga))
    assert (await add_task(world, a, a.admin, original, title="Swap toner")).status_code == 201
    await say(world, a, a.admin, original)
    plain, with_tasks = (
        (await copy(world, a, a.admin, original)).json()["items"][0],
        (await copy(world, a, a.admin, original, parts=["tasks"])).json()["items"][0],
    )
    assert (await tasks(world, a, a.admin, plain))["items"] == []
    copied = (await tasks(world, a, a.admin, with_tasks))["items"]
    assert [(t["title"], t["status"]) for t in copied] == [("Swap toner", "open")]
    for c in (plain, with_tasks):
        talk = await world.call("GET", f"{BASE}/{c['id']}/conversation", a, a.admin)
        assert [e for e in talk.json()["items"] if e["kind"] in {"note", "reply"}] == []
        rows = await world.sql(
            "SELECT count(*) AS n FROM work_item_worklogs"
            " WHERE tenant_id = $1 AND work_item_id = $2",
            a.tenant,
            uuid.UUID(c["id"]),
        )
        assert rows[0]["n"] == 0
    # The group came (the admin may assign); a person never does.
    assert (plain["group_id"], plain["technician_id"]) == (str(a.ga), None)


async def test_req_inc_033_ac3_the_limit_is_said(world: World) -> None:
    a = world.a
    original = await world.create(a, a.admin)
    refused = await copy(world, a, a.admin, original, count=21)
    assert field_codes(refused) == {"count": "too_many_copies"}
    params = [e["params"] for e in refused.json()["errors"]]
    assert params == [{"max": 20}], json.dumps(refused.json())


async def test_copies_need_create_and_a_visible_original(world: World) -> None:
    a, b = world.a, world.b
    original = await world.create(a, a.admin)
    other_tenant = await copy(world, b, b.admin, original)
    assert problem(other_tenant) == (404, "work_item_not_found")
    requester = await copy(world, a, a.requester, original)
    assert requester.status_code == 403, requester.text


async def test_req_inc_033_ac3_the_limit_is_the_types_own(world: World) -> None:
    """The type's copy limit (0156) is what the refusal says; it stays within 1 to 100."""
    a = world.a
    settings = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
    assert settings["closure"]["copy_limit"] == 20

    async def save(limit: int) -> httpx.Response:
        current = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
        return await world.call(
            "PATCH",
            f"{BASE}/settings/closure",
            a,
            a.admin,
            json={"copy_limit": limit},
            headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
        )

    assert field_codes(await save(101)) == {"copy_limit": "out_of_range"}
    assert (await save(3)).status_code == 200
    try:
        original = await world.create(a, a.admin)
        refused = await copy(world, a, a.admin, original, count=4)
        assert [e["params"] for e in refused.json()["errors"]] == [{"max": 3}]
        assert (await copy(world, a, a.admin, original, count=3)).status_code == 201
    finally:
        assert (await save(20)).status_code == 200  # the shared world's other tests use 20


async def _copied_files(world: World, org: Org) -> list[Any]:
    return await world.sql(
        "SELECT id, object_key, copied_from FROM files WHERE tenant_id = $1 AND source = 'copy'",
        org.tenant,
    )


async def test_attachments_come_as_new_files_and_images_point_at_them(
    world: World, files: FileServices
) -> None:
    """Lane B's rules: each copy gets its own files; what cannot be opened now stays behind,
    is listed, and its image is removed from the copy's description."""
    del files
    a = world.a
    original = await world.create(a, a.admin)
    owner = ("work_item", original["id"])
    kept = (await upload(world, a, a.admin, owner, b"report", "report.txt")).json()
    image = (await upload(world, a, a.admin, owner, PNG, "shot.png", inline="true")).json()
    infected = (await upload(world, a, a.admin, owner, EICAR, "x.txt")).json()
    await scan_waiting(world)
    waiting = (await upload(world, a, a.admin, owner, PNG, "later.png", inline="true")).json()
    html = (
        f'<p>See</p><img src="x" data-file-id="{image["id"]}">'
        f'<img src="x" data-file-id="{waiting["id"]}">'
    )
    fresh = (await world.get(a, a.admin, original)).json()
    patched = await world.patch(a, a.admin, fresh, description=html)
    assert patched.status_code == 200, patched.text
    before = len(await _copied_files(world, a))
    made = await copy(world, a, a.admin, original, count=2, parts=["attachments"])
    assert made.status_code == 201, made.text
    body = made.json()
    assert sorted((n["file_id"], n["reason"]) for n in body["files_not_copied"]) == sorted(
        [(infected["id"], "infected"), (waiting["id"], "scanning")]
    )
    copied = await _copied_files(world, a)
    assert len(copied) - before == 4  # report and image, on each of the two copies
    for c in body["items"]:
        listed = await record_files(world, a, a.admin, c)
        assert sorted(f["name"] for f in listed) == ["report.txt", "shot.png"]
        assert {f["id"] for f in listed}.isdisjoint({kept["id"], image["id"]})
        shot = next(f for f in listed if f["name"] == "shot.png")
        assert f'data-file-id="{shot["id"]}"' in c["description"]
        # Never the original's files, and the image still being checked is gone.
        assert image["id"] not in c["description"]
        assert waiting["id"] not in c["description"]
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = 'file.copied'",
        a.tenant,
    )
    assert audit[0]["n"] >= 4


async def test_another_tenants_record_copies_nothing(
    world: World, files: FileServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lane B: a source in another tenant is 404, with no rows and no objects written."""
    del files
    a, b = world.a, world.b
    original = await world.create(a, a.admin)
    await upload(world, a, a.admin, ("work_item", original["id"]), b"secret", "s.txt")
    await scan_waiting(world)
    before_a, before_b = len(await _copied_files(world, a)), len(await _copied_files(world, b))
    writes: list[str] = []
    for name in ("put", "put_stream"):
        real = getattr(S3Storage, name)

        async def counted(
            self: S3Storage,
            key: str,
            *args: Any,  # noqa: ANN401 - the storage call's own arguments
            _real: Any = real,  # noqa: ANN401 - the method replaced
            **kw: Any,  # noqa: ANN401 - the storage call's own arguments
        ) -> Any:  # noqa: ANN401 - whatever the storage returns
            writes.append(key)
            return await _real(self, key, *args, **kw)

        monkeypatch.setattr(S3Storage, name, counted)  # the class: its instances are frozen
    refused = await copy(world, b, b.admin, original, count=1, parts=["attachments"])
    assert problem(refused) == (404, "work_item_not_found")
    assert writes == []
    assert len(await _copied_files(world, a)) == before_a
    assert len(await _copied_files(world, b)) == before_b


async def test_a_target_the_actor_cannot_use_copies_nothing(
    world: World, files: FileServices
) -> None:
    """Lane B: one target the actor may not attach to refuses the whole call as not found."""
    a = world.a
    source = await world.create(a, a.tech_a, group_id=str(a.ga))
    unseen = await world.create(a, a.admin, group_id=str(a.gb))  # tech_a is not in GB
    await upload(world, a, a.tech_a, ("work_item", source["id"]), b"notes", "n.txt")
    await scan_waiting(world)
    before = len(await _copied_files(world, a))
    database = world.app.state.db
    async with database.tenant_session(TenantContext(a.tenant)) as session:
        actor = await subject_for(session, a.tenant, a.tech_a)
        with pytest.raises(NotFound):
            await copy_to_records(
                session,
                files,
                actor,
                owner_type=OwnerType.WORK_ITEM,
                source_id=uuid.UUID(source["id"]),
                target_ids=[uuid.UUID(unseen["id"])],
            )
    assert len(await _copied_files(world, a)) == before


async def test_two_copies_of_a_25_mb_file_in_good_time(world: World, files: FileServices) -> None:
    """Lane B's timing: a 25 MB attachment copied onto two copies (50 MB) in one request."""
    del files
    a = world.a
    original = await world.create(a, a.admin)
    big = (25 * MB) - 1024
    stored = await upload(world, a, a.admin, ("work_item", original["id"]), b"z" * big, "big.bin")
    assert stored.status_code == 201, stored.text
    await scan_waiting(world)
    started = time.monotonic()
    made = await copy(world, a, a.admin, original, count=2, parts=["attachments"])
    took = time.monotonic() - started
    assert made.status_code == 201, made.text
    assert made.json()["files_not_copied"] == []
    print(f"25 MB x 2 copied in {took:.1f} s")  # noqa: T201 - lane B asked for the number
    assert took < 60, took  # generous for CI's shared runners; the number goes in the PR
