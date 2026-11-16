"""Merging duplicate incidents, with a preview and undo (WP-046b S2; REQ-INC-088, -150).

Lane B's and the coordinator's conditions: the preview counts who would newly see the duplicate
and the merge waits for a confirmation; notes keep their own visibility (two requesters: the
survivor's never sees the duplicate's private notes, and the other requester stays nameless);
undo needs its right and puts things back exactly, or refuses.
"""

from typing import Any

from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, world  # noqa: F401 - fixture

PORTAL = "/portal/incidents"


def _problem(response: Any) -> tuple[int, str | None]:  # noqa: ANN401 - an httpx response
    body = response.json()
    codes = [e.get("code") for e in body.get("errors") or []]
    return response.status_code, (codes[0] if codes else body.get("code"))


async def _note(
    world: World,  # noqa: F811
    org: Org,
    item: dict[str, Any],
    body: str,
    *,
    public: bool,
) -> None:
    kind = {"kind": "note", "visibility": "public" if public else "private"}
    added = await world.call(
        "POST",
        f"{BASE}/{item['id']}/conversation",
        org,
        org.admin,
        json={**kind, "body": f"<p>{body}</p>"},
        headers=CONSOLE,
    )
    assert added.status_code == 201, added.text


async def _fresh(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    found = await world.get(org, org.admin, item)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def _merge(
    world: World,  # noqa: F811
    org: Org,
    user: Any,  # noqa: ANN401 - a user ID
    duplicate: dict[str, Any],
    survivor: dict[str, Any],
    *,
    confirm: bool,
) -> Any:  # noqa: ANN401 - an httpx response
    return await world.call(
        "POST",
        f"{BASE}/{duplicate['id']}/merge",
        org,
        user,
        json={"into_id": survivor["id"], "confirm_wider_audience": confirm},
        headers={"If-Match": f'"{duplicate["version"]}"', **CONSOLE},
    )


async def test_preview_confirm_merge_and_undo(world: World) -> None:  # noqa: F811
    a = world.a
    survivor = await world.create(a, a.admin, group_id=str(a.ga))  # requester: a.requester
    duplicate = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    child = await world.create(a, a.admin, group_id=str(a.ga))
    linked = await world.call(
        "POST",
        f"{BASE}/{duplicate['id']}/children",
        a,
        a.admin,
        json={"child_id": child["id"]},
        headers=CONSOLE,
    )
    assert linked.status_code == 201, linked.text
    shown = await world.call(
        "GET", f"{BASE}/{duplicate['id']}/merge-preview?into_id={survivor['id']}", a, a.admin
    )
    assert shown.status_code == 200, shown.text
    preview = shown.json()
    assert preview["child_ids"] == [child["id"]]
    # The survivor's requester would see the duplicate's public side: confirm first.
    assert preview["requesters_newly_seeing"] == 1
    assert preview["needs_confirmation"] is True
    # Not the same department (none set): the duplicate's requester is not added.
    assert preview["followers_not_added"] == [str(a.requester2)]
    duplicate = await _fresh(world, a, duplicate)
    waiting = await _merge(world, a, a.admin, duplicate, survivor, confirm=False)
    assert _problem(waiting) == (409, "merge_widens_audience")
    done = await _merge(world, a, a.admin, duplicate, survivor, confirm=True)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "merged"
    assert done.json()["moved_child_ids"] == [child["id"]]
    # The merged record stays readable, and its child now sits under the survivor.
    links = (await world.call("GET", f"{BASE}/{child['id']}/links", a, a.admin)).json()
    assert [(x["relation"], x["other_id"]) for x in links] == [("child_of", survivor["id"])]
    # Undo puts it back exactly, audited with both IDs.
    undone = await world.call(
        "POST",
        f"{BASE}/{duplicate['id']}/undo-merge",
        a,
        a.admin,
        headers={"If-Match": f'"{done.json()["version"]}"', **CONSOLE},
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["status"] == duplicate["status"]
    links = (await world.call("GET", f"{BASE}/{child['id']}/links", a, a.admin)).json()
    assert [(x["relation"], x["other_id"]) for x in links] == [("child_of", duplicate["id"])]
    (audit,) = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'incident.merge_undone' AND object_id = $2",
        a.tenant,
        duplicate["id"],
    )
    assert survivor["id"] in str(audit["details"])


async def test_notes_keep_their_visibility_for_two_requesters(world: World) -> None:  # noqa: F811
    a = world.a
    survivor = await world.create(a, a.admin, group_id=str(a.ga))  # requester: a.requester
    duplicate = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    await _note(world, a, duplicate, "Private duplicate note", public=False)
    await _note(world, a, duplicate, "Public duplicate note", public=True)
    duplicate = await _fresh(world, a, duplicate)
    done = await _merge(world, a, a.admin, duplicate, survivor, confirm=True)
    assert done.status_code == 200, done.text
    # Staff see both, marked with where they came from.
    staff = (await world.call("GET", f"{BASE}/{survivor['id']}/conversation", a, a.admin)).json()
    marked = {e["body"]: e["from_record"] for e in staff["items"]}
    assert marked["<p>Private duplicate note</p>"] == duplicate["display_id"]
    assert marked["<p>Public duplicate note</p>"] == duplicate["display_id"]
    # The survivor's requester: the public one only, never the private note.
    portal = await world.call("GET", f"{PORTAL}/{survivor['id']}/conversation", a, a.requester)
    assert portal.status_code == 200, portal.text
    bodies = [e["body"] for e in portal.json()["items"]]
    assert "<p>Public duplicate note</p>" in bodies
    assert "<p>Private duplicate note</p>" not in bodies
    # The duplicate's requester gains nothing: the survivor is not theirs.
    other = await world.call("GET", f"{PORTAL}/{survivor['id']}/conversation", a, a.requester2)
    assert other.status_code == 404, other.text


async def test_staff_audience_counted_and_undo_needs_right_and_exactness(
    world: World,  # noqa: F811
) -> None:
    a = world.a
    # tech_a sees group A's records and not group B's: merging B's duplicate into an A record
    # widens its audience by at least tech_a.
    survivor = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    duplicate = await world.create(a, a.admin, group_id=str(a.gb), requester_id=str(a.requester2))
    shown = await world.call(
        "GET", f"{BASE}/{duplicate['id']}/merge-preview?into_id={survivor['id']}", a, a.admin
    )
    assert shown.json()["staff_newly_seeing"] >= 1
    assert shown.json()["requesters_newly_seeing"] == 0  # same requester on both
    duplicate = await _fresh(world, a, duplicate)
    done = await _merge(world, a, a.admin, duplicate, survivor, confirm=True)
    assert done.status_code == 200, done.text
    merged = done.json()
    # A technician holds no undo right.
    refused = await world.call(
        "POST",
        f"{BASE}/{duplicate['id']}/undo-merge",
        a,
        a.lead,
        headers={"If-Match": f'"{merged["version"]}"', **CONSOLE},
    )
    assert refused.status_code in {403, 404}, refused.text
    # The survivor closed since: undo can no longer be exact.
    survivor = await _fresh(world, a, survivor)
    resolved = await world.act(a, a.admin, survivor, "resolve")
    assert (await world.act(a, a.admin, resolved.json(), "close")).status_code == 200
    late = await world.call(
        "POST",
        f"{BASE}/{duplicate['id']}/undo-merge",
        a,
        a.admin,
        headers={"If-Match": f'"{merged["version"]}"', **CONSOLE},
    )
    assert _problem(late) == (409, "merge_undo_not_exact")


async def test_two_runs_at_once_one_wins_and_the_other_is_refused(world: World) -> None:  # noqa: F811
    """Lane B: the record is locked; a second merge or conversion with the same version 409s."""
    import asyncio  # noqa: PLC0415

    from tests.db.test_service_requests_api import an_item  # noqa: PLC0415

    a = world.a
    keep_a = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    keep_b = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    duplicate = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    duplicate = await _fresh(world, a, duplicate)
    both = await asyncio.gather(
        _merge(world, a, a.admin, duplicate, keep_a, confirm=True),
        _merge(world, a, a.admin, duplicate, keep_b, confirm=True),
    )
    assert sorted(r.status_code for r in both) == [200, 409], [r.text for r in both]
    # Conversions too: one new record, never two.
    other = await world.create(a, a.admin, group_id=str(a.ga))
    other = await _fresh(world, a, other)
    item = await an_item(world, a)
    body = {"catalog_item_id": item["id"], "answers": {"model": "air"}}
    headers = {"If-Match": f'"{other["version"]}"', **CONSOLE}
    runs = await asyncio.gather(
        *(
            world.call(
                "POST", f"{BASE}/{other['id']}/convert", a, a.admin, json=body, headers=headers
            )
            for _ in range(2)
        )
    )
    assert sorted(r.status_code for r in runs) == [200, 409], [r.text for r in runs]


async def test_a_follower_brought_by_a_merge_is_counted_and_confirmed(
    world: World,  # noqa: F811
) -> None:
    """Lane B: the duplicate's requester as follower widens the audience, so it is confirmed."""
    a = world.a
    survivor = await world.create(a, a.admin, group_id=str(a.ga))  # requester: a.requester
    duplicate = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    department = await world.sql(
        "SELECT id FROM departments WHERE tenant_id = $1 LIMIT 1", a.tenant
    )
    if not department:
        department = await world.sql(
            "INSERT INTO departments (tenant_id, id, name) VALUES ($1, gen_random_uuid(), 'Ops')"
            " RETURNING id",
            a.tenant,
        )
    await world.sql(
        "UPDATE work_items SET department_id = $1 WHERE tenant_id = $2 AND id = ANY($3::uuid[])",
        department[0]["id"],
        a.tenant,
        [survivor["id"], duplicate["id"]],
    )
    reply = await world.call(
        "POST",
        f"{PORTAL}/{survivor['id']}/replies",
        a,
        a.requester,
        json={"body": "<p>Still broken here.</p>"},
        headers=CONSOLE,
    )
    assert reply.status_code == 201, reply.text
    shown = await world.call(
        "GET", f"{BASE}/{duplicate['id']}/merge-preview?into_id={survivor['id']}", a, a.admin
    )
    preview = shown.json()
    assert preview["followers_added"] == [str(a.requester2)]
    assert preview["followers_newly_seeing"] == 1
    assert preview["needs_confirmation"] is True
    duplicate = await _fresh(world, a, duplicate)
    waiting = await _merge(world, a, a.admin, duplicate, survivor, confirm=False)
    assert _problem(waiting) == (409, "merge_widens_audience")
    assert waiting.json()["params"]["followers"] == "1"
    done = await _merge(world, a, a.admin, duplicate, survivor, confirm=True)
    assert done.status_code == 200, done.text
    # A requester's follow grants no portal reach: the survivor stays out of their portal; what
    # they gain is the survivor's public replies and notes by e-mail (counted above).
    seen = await world.call("GET", f"{PORTAL}/{survivor['id']}/conversation", a, a.requester2)
    assert seen.status_code == 404, seen.text
    follows = await world.sql(
        "SELECT grants_access FROM work_item_followers WHERE tenant_id = $1"
        " AND work_item_id = $2 AND user_id = $3 AND deleted_at IS NULL",
        a.tenant,
        survivor["id"],
        a.requester2,
    )
    assert [r["grants_access"] for r in follows] == [False]
