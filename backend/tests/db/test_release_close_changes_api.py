"""Closing a release's changes from the release (WP-058b S5a; REQ-REL-052).

Each change not closed yet closes by lane A's change close (`close_change`), as the person, in
its own savepoint: one at its review closes; one that cannot close from where it is is skipped
with why, and the other one still closes. Nothing is forced, and the release itself is not
touched. Another tenant gets a 404.
"""

from typing import Any

from tests.db.test_change_closure_api import _in_review
from tests.db.test_changes_api import a_change
from tests.db.test_incidents_api import CONSOLE, Org, World, world
from tests.db.test_releases_api import REL, a_release

__all__ = ["world"]  # the fixture, re-used


async def _in(world: World, org: Org, release: dict[str, Any], change: dict[str, Any]) -> None:
    added = await world.call(
        "POST",
        f"{REL}/{release['id']}/changes",
        org,
        org.admin,
        json={"change_id": change["id"]},
        headers=CONSOLE,
    )
    assert added.status_code in {200, 201, 204}, added.text


async def test_req_rel_052_closes_the_changes_it_may_and_says_why_for_the_rest(
    world: World,
) -> None:
    a = world.a
    release = await a_release(world, a)
    ready = await _in_review(world, a)
    early = await a_change(world, a)
    await _in(world, a, release, ready)
    await _in(world, a, release, early)
    codes = (await world.call("GET", "/changes/settings", a, a.admin)).json()["closure_codes"]
    done = await world.call(
        "POST",
        f"{REL}/{release['id']}/changes/close",
        a,
        a.admin,
        json={"closure_code": codes[0]["code"]},
        headers=CONSOLE,
    )
    assert done.status_code == 200, done.text
    by_id = {r["id"]: r for r in done.json()}
    assert by_id[ready["id"]]["closed"] is True
    assert (by_id[early["id"]]["closed"], by_id[early["id"]]["code"]) == (
        False,
        "not_closable_from_here",
    )
    closed = (await world.call("GET", f"/changes/{ready['id']}", a, a.admin)).json()
    assert closed["status_category"] == "closed"
    still = (await world.call("GET", f"/changes/{early['id']}", a, a.admin)).json()
    assert still["status_category"] != "closed"
    # The release itself is untouched.
    after = (await world.call("GET", f"{REL}/{release['id']}", a, a.admin)).json()
    assert after["version"] == release["version"]
    # A second run closes nothing more and skips the same change.
    again = await world.call(
        "POST",
        f"{REL}/{release['id']}/changes/close",
        a,
        a.admin,
        json={"closure_code": codes[0]["code"]},
        headers=CONSOLE,
    )
    assert [r["id"] for r in again.json()] == [early["id"]]
    # Another tenant sees nothing of it.
    b = world.b
    theirs = await world.call(
        "POST",
        f"{REL}/{release['id']}/changes/close",
        b,
        b.admin,
        json={"closure_code": codes[0]["code"]},
        headers=CONSOLE,
    )
    assert theirs.status_code == 404, theirs.text
