"""WP-020d QA fix round (~/Desktop/qa-wp020d/QA-REPORT.md). Test names cite the bug.

BUG-01: view counts must follow every change that moves a record in or out of a count. Record
changes (create, assign, status, group, delete, restore) reach the incident lists; personal
changes (follow, unfollow, sharing, a reply by someone else, a new direct report) reach the
person whose counts they change, on their own channel, because a user who sees every incident
follows only the shared list channel (realtime.md).
"""

import uuid

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.identity_access.service.realtime import ROUTES as PEOPLE_ROUTES
from app.modules.work_items.service.realtime import ROUTES
from app.shared.events import EventEnvelope
from tests.db.test_conversation_api import events_of, follow, say
from tests.db.test_incidents_api import BASE, Org, World, world

__all__ = ["world"]  # the fixture, re-used

LISTS_CHANGED = "work_items.lists_changed"
CHANGED = "work_items.changed"


async def _routed(app_db: Database, org: Org, envelope: EventEnvelope) -> set[tuple[str, str]]:
    """(channel, message type) of every publication the event's route makes."""
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        for spec in [*ROUTES, *PEOPLE_ROUTES]:
            if envelope.event_type in spec.event_types:
                effects = await spec.route(envelope, session)
                return {(p.channel.name, p.type) for p in effects.publications}
    return set()


async def _last(world: World, aggregate: str, event_type: str) -> EventEnvelope:
    return [e for e in await events_of(world, aggregate) if e.event_type == event_type][-1]


def _personal(org: Org, user: uuid.UUID) -> tuple[str, str]:
    return (f"t:{org.tenant}:user:{user}", LISTS_CHANGED)


def _all_list(org: Org) -> tuple[str, str]:
    return (f"t:{org.tenant}:queue:incidents", CHANGED)


# --- personal changes: the person's own channel -------------------------------------------------


async def test_bug_01_a_follow_reaches_the_followers_counts(world: World, app_db: Database) -> None:
    org = world.a
    item = await world.create(org, org.tech_a, group_id=str(org.ga))
    assert (await follow(world, org, org.admin, item, org.admin, on=True)).status_code == 200
    routed = await _routed(
        app_db, org, await _last(world, "work_item_follower", "work_items.follower.added")
    )
    assert _personal(org, org.admin) in routed  # "Followed by me" (the QA case)


async def test_bug_01_an_unfollow_reaches_the_followers_counts(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = await world.create(org, org.tech_a, group_id=str(org.ga))
    await follow(world, org, org.admin, item, org.admin, on=True)
    assert (await follow(world, org, org.admin, item, org.admin, on=False)).status_code in {
        200,
        204,
    }
    routed = await _routed(
        app_db, org, await _last(world, "work_item_follower", "work_items.follower.removed")
    )
    assert _personal(org, org.admin) in routed


async def test_bug_01_sharing_by_hand_over_reaches_the_former_owners_counts(
    world: World, app_db: Database
) -> None:
    """A hand-over that keeps the old technician following with access: "Shared with me"."""
    org = world.a
    item = await world.create(org, org.tech_a, group_id=str(org.ga), technician_id=str(org.tech_a))
    moved = await world.assign(
        org,
        org.tech_a,
        item,
        group=org.gb,
        reason_code="wrong_group",
        confirm_lose_access=True,
        keep_following=True,
    )
    assert moved.status_code == 200, moved.text
    followed = [
        e
        for e in await events_of(world, "work_item_follower")
        if e.event_type == "work_items.follower.added" and e.payload.get("grants_access")
    ]
    assert followed, "the hand-over kept the old technician as an access-granting follower"
    assert _personal(org, org.tech_a) in await _routed(app_db, org, followed[-1])


async def test_bug_01_a_reply_by_someone_else_reaches_the_assignees_counts(
    world: World, app_db: Database
) -> None:
    """ "Updated by others" counts entries by others on records you own or follow."""
    org = world.a
    item = await world.create(org, org.admin, group_id=str(org.ga), technician_id=str(org.tech_a))
    assert (await follow(world, org, org.admin, item, org.admin, on=True)).status_code == 200
    kind = "work_items.conversation.added"
    assert (await say(world, org, org.tech_a, item)).status_code == 201
    by_technician = await _routed(app_db, org, await _last(world, "work_item_conversation", kind))
    assert _personal(org, org.admin) in by_technician  # the follower recounts
    assert _personal(org, org.tech_a) not in by_technician  # not the writer
    assert (await say(world, org, org.admin, item)).status_code == 201
    by_follower = await _routed(app_db, org, await _last(world, "work_item_conversation", kind))
    assert _personal(org, org.tech_a) in by_follower  # the technician recounts
    assert _personal(org, org.admin) not in by_follower


async def test_bug_01_a_new_direct_report_reaches_the_managers_counts(
    world: World, app_db: Database
) -> None:
    """ "From my direct reports": the old and the new manager both recount."""
    org = world.a
    person = (await world.call("GET", f"/users/{org.requester}", org, org.admin)).json()
    first = await world.call(
        "PATCH",
        f"/users/{org.requester}/person",
        org,
        org.admin,
        json={"manager_id": str(org.tech_a)},
        headers={"If-Match": f'"{person["version"]}"'},
    )
    assert first.status_code == 200, first.text
    second = await world.call(
        "PATCH",
        f"/users/{org.requester}/person",
        org,
        org.admin,
        json={"manager_id": str(org.tech_b)},
        headers={"If-Match": f'"{first.json()["version"]}"'},
    )
    assert second.status_code == 200, second.text
    event = await _last(world, "user", "identity_access.user.updated")
    assert sorted(event.payload["managers"]) == sorted([str(org.tech_a), str(org.tech_b)])
    routed = await _routed(app_db, org, event)
    for manager in (org.tech_a, org.tech_b):
        assert (f"t:{org.tenant}:user:{manager}", "users.reports_changed") in routed


# --- record changes: the lists ------------------------------------------------------------------


async def _record_event(world: World, event_type: str) -> EventEnvelope:
    return await _last(world, "work_item", event_type)


async def test_bug_01_a_new_incident_reaches_the_lists(world: World, app_db: Database) -> None:
    org = world.a
    await world.create(org, org.admin, group_id=str(org.ga))
    routed = await _routed(app_db, org, await _record_event(world, "work_items.work_item.created"))
    assert {_all_list(org), (f"t:{org.tenant}:queue:incidents.group.{org.ga}", CHANGED)} <= routed


async def test_bug_01_an_assignment_reaches_old_and_new_audiences(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = await world.create(org, org.admin, group_id=str(org.ga), technician_id=str(org.tech_a))
    moved = await world.assign(
        org, org.admin, item, group=org.gb, technician=org.tech_b, reason_code="wrong_group"
    )
    assert moved.status_code == 200, moved.text
    routed = await _routed(app_db, org, await _record_event(world, "work_items.work_item.assigned"))
    assert _all_list(org) in routed
    for group in (org.ga, org.gb):  # "My groups, open" on both sides
        assert (f"t:{org.tenant}:queue:incidents.group.{group}", CHANGED) in routed
    for tech in (org.tech_a, org.tech_b):  # "My open" on both sides
        assert (f"t:{org.tenant}:user:{tech}", CHANGED) in routed


async def test_bug_01_a_status_change_reaches_the_lists(world: World, app_db: Database) -> None:
    org = world.a
    item = await world.create(org, org.admin, group_id=str(org.ga))
    assert (await world.act(org, org.admin, item, "resolve")).status_code == 200
    routed = await _routed(
        app_db, org, await _record_event(world, "work_items.work_item.status_changed")
    )
    assert _all_list(org) in routed


async def test_bug_01_delete_and_restore_reach_the_lists(world: World, app_db: Database) -> None:
    org = world.a
    item = await world.create(org, org.admin, group_id=str(org.ga))
    gone = await world.call(
        "DELETE", f"{BASE}/{item['id']}", org, org.admin, headers={"If-Match": '"1"'}
    )
    assert gone.status_code == 204, gone.text
    routed = await _routed(app_db, org, await _record_event(world, "work_items.work_item.deleted"))
    assert _all_list(org) in routed
    back = await world.call(
        "POST",
        f"{BASE}/{item['id']}/restore",
        org,
        org.admin,
        headers={"If-Match": '"2"'},
    )
    assert back.status_code == 200, back.text
    routed = await _routed(app_db, org, await _record_event(world, "work_items.work_item.restored"))
    assert _all_list(org) in routed
