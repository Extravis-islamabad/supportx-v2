"""A vendor support account on the desk (WP-057 S4c-2, lane B (4), (ii)).

- Never offered as an assignee: it holds work rights from its grant, never a technician's role.

Same world as test_files_api.py. A support account at "view and change" never holds add_note, so
it is never staff: a private note's file is not found for it, while staff still open it. A
public file opens, and every download it makes is audited (a person's public download is not,
D-082 D7).
"""

import uuid

from app.shared.files.service.core import FileServices
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_audit_exports import storage
from tests.db.test_conversation_api import say
from tests.db.test_files_api import files, open_file, record_files, scan_waiting, upload
from tests.db.test_incidents_api import World, problem
from tests.db.test_users_api import seed_users

pytestmark = MODULE_LOOP

__all__ = ["files", "module_world", "shared_world", "storage"]  # fixtures, re-used


async def _support_account(world: World) -> uuid.UUID:
    """A vendor support account with an open view-and-change grant, as #552 makes one."""
    a = world.a
    (user_id,) = await seed_users(
        world.db, a.tenant, [{"user_type": "technician", "display_name": "Extravis support"}]
    )
    await world.sql(
        "UPDATE users SET user_type = 'vendor_support', roles_mapped_at = now() WHERE id = $1",
        user_id,
    )
    await world.sql(
        "INSERT INTO support_grants (id, tenant_id, engineer_name, engineer_email, reason, access,"
        " change_reason, starts_at, ends_at, state, verification, support_user_id)"
        " VALUES ($1, $2, 'Omar', 'omar@extravis.com', 'r', 'view_and_change', 'fix INC-12',"
        " now() - interval '1 hour', now() + interval '1 hour', 'active', 'email', $3)",
        uuid.uuid4(),
        a.tenant,
        user_id,
    )
    await world.app.state.policy.invalidate(a.tenant)
    return user_id


async def _downloads_by(world: World, user_id: uuid.UUID) -> int:
    rows = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'file.downloaded' AND actor_id = $2",
        world.a.tenant,
        user_id,
    )
    return int(rows[0]["n"])


async def test_support_never_sees_private_files_and_every_download_is_audited(
    world: World, files: FileServices
) -> None:
    del files
    a = world.a
    support = await _support_account(world)
    item = await world.create(a, a.tech_a)
    note = await say(world, a, a.tech_a, item, kind="note", visibility="private")
    assert note.status_code == 201, note.text
    reply = await say(world, a, a.tech_a, item, kind="reply", visibility="public", to=["x@y.test"])
    assert reply.status_code == 201, reply.text
    secret = await upload(
        world, a, a.tech_a, ("conversation_entry", note.json()["entry"]["id"]), b"pay", "pay.txt"
    )
    public = await upload(
        world, a, a.tech_a, ("conversation_entry", reply.json()["entry"]["id"]), b"g", "guide.txt"
    )
    assert secret.status_code == 201, secret.text
    assert public.status_code == 201, public.text
    await scan_waiting(world)
    assert {f["name"] for f in await record_files(world, a, support, item)} == {"guide.txt"}
    for path, method in (
        (f"/files/{secret.json()['id']}", "GET"),
        (f"/files/{secret.json()['id']}/link", "POST"),
    ):
        refused = await world.call(method, path, a, support, json={})
        assert problem(refused) == (404, "file_not_found"), path
    # Staff still see and open both (the control).
    assert {f["name"] for f in await record_files(world, a, a.tech_a, item)} == {
        "pay.txt",
        "guide.txt",
    }
    # A public file opens for support, and the download is audited.
    before = await _downloads_by(world, support)
    opened = await open_file(world, a, support, public.json()["id"])
    assert opened.status_code == 200, opened.text
    assert await _downloads_by(world, support) == before + 1


async def test_support_is_never_offered_as_an_assignee(world: World) -> None:
    """Lane B (ii): its grant gives work rights, never a technician's place in pickers."""
    a = world.a
    support = await _support_account(world)
    offered = await world.call("GET", "/incidents/assignees", a, a.admin, params={"limit": 100})
    assert offered.status_code == 200, offered.text
    ids = {row["id"] for row in offered.json()}
    assert str(a.tech_a) in ids  # the control
    assert str(support) not in ids
    searched = await world.call(
        "GET", "/incidents/assignees", a, a.admin, params={"search": "Extravis"}
    )
    assert searched.status_code == 200, searched.text
    assert str(support) not in {row["id"] for row in searched.json()}
