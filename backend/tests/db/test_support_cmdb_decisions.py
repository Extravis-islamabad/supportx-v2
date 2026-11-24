"""Vendor support never deletes, restores or merges CIs (D-173: deletes are tenant decisions).

Lane C's independent check, by the owner of the vendor allow-list. `cmdb.manage` stood in for every
CI write (`cis.writer`, the routes' DELETE-or-MANAGE gate, merge), so a "view and change" grant that
held it could delete, restore and merge CIs although `cmdb.delete` is never for support. The same
session still adds and edits CIs (the control), and the tenant's admin still deletes them.
"""

import uuid

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_api import _ci
from tests.db.test_incidents_api import World
from tests.db.test_knowledge_api import _match
from tests.db.test_support_desk import _support_account

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used


async def test_support_may_edit_a_ci_but_never_delete_restore_or_merge_one(world: World) -> None:
    a = world.a
    support = await _support_account(world)
    tag = uuid.uuid4().hex[:6]
    first = await _ci(world, a, f"Support kept {tag}")
    second = await _ci(world, a, f"Support twin {tag}")
    trashed = await _ci(world, a, f"Support trashed {tag}")
    for made in (first, second, trashed):
        assert made.status_code == 201, made.text
    ci, twin, old = first.json(), second.json(), trashed.json()

    # The control: the grant's own work, an edit, goes through.
    edited = await world.call(
        "PATCH", f"/cmdb/cis/{ci['id']}", a, support,
        json={"name": f"Support edited {tag}"}, headers=_match(ci["version"]),
    )  # fmt: skip
    assert edited.status_code == 200, edited.text
    ci = edited.json()

    # Never a delete, and the record page never offers one.
    shown = await world.call("GET", f"/cmdb/cis/{ci['id']}", a, support)
    assert shown.status_code == 200, shown.text
    assert shown.json()["can_delete"] is False
    gone = await world.call(
        "DELETE", f"/cmdb/cis/{ci['id']}", a, support, headers=_match(ci["version"])
    )
    assert gone.status_code == 403, gone.text

    # Never a restore of a CI the tenant put in the trash.
    removed = await world.call(
        "DELETE", f"/cmdb/cis/{old['id']}", a, a.admin, headers=_match(old["version"])
    )
    assert removed.status_code == 204, removed.text  # the admin may (the control)
    back = await world.call(
        "POST", f"/cmdb/cis/{old['id']}/restore", a, support, headers=_match(old["version"] + 1)
    )
    assert back.status_code in {403, 404}, back.text
    assert (await world.call("GET", f"/cmdb/cis/{old['id']}", a, a.admin)).status_code == 404

    # Never a merge (it removes the duplicate), not even its preview.
    preview = await world.call(
        "GET", "/cmdb/merges/preview", a, support,
        params={"first": ci["id"], "second": twin["id"]},
    )  # fmt: skip
    assert preview.status_code == 403, preview.text

    # The CI is still there, as the support session edited it.
    kept = await world.call("GET", f"/cmdb/cis/{ci['id']}", a, a.admin)
    assert kept.status_code == 200, kept.text
    assert kept.json()["deleted_at"] is None
