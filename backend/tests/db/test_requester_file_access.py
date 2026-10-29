"""A requester reaches the files of their own incident (WP-024 session 2 finding, lane B).

Mail attachments upload as the sender, and the portal (WP-028) will do the same, so the owner
check must know the requester's side: the record's requester or the person it is for may see the
record's files and those of its public entries, and attach to the record and to their own public
replies. Removing files, and anything private, stays with staff. Staff keep their own rules.
"""

import subprocess
import sys
import uuid
from typing import Any

from app.core.database import Database
from app.core.errors import NotFound, PermissionDenied
from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.work_items.service.file_access import FILE_ACCESS
from app.shared.files.ports import Action, OwnerType
from tests.db.test_conversation_api import say, timeline
from tests.db.test_incidents_api import BASE, Org, World, world

__all__ = ["world"]  # the fixture, re-used

PORTAL = {"X-SupportX-Client": "portal"}


async def _check(
    app_db: Database,
    org: Org,
    user: uuid.UUID,
    owner_type: OwnerType,
    owner_id: str,
    action: Action,
) -> Any:  # noqa: ANN401 - the Owner, or the error raised
    async with app_db.tenant_session(TenantContext(org.tenant, user_id=user)) as session:
        subject = await subject_for(session, org.tenant, user)
        try:
            return await FILE_ACCESS.check(
                session, subject, owner_type, uuid.UUID(owner_id), action
            )
        except (NotFound, PermissionDenied) as error:
            return error


async def _visible(app_db: Database, org: Org, user: uuid.UUID, item: dict[str, Any]) -> Any:  # noqa: ANN401
    async with app_db.tenant_session(TenantContext(org.tenant, user_id=user)) as session:
        subject = await subject_for(session, org.tenant, user)
        try:
            return await FILE_ACCESS.visible_owners(
                session, subject, "incident", uuid.UUID(item["id"])
            )
        except NotFound as error:
            return error


async def _requester_reply(world: World, org: Org, item: dict[str, Any]) -> str:
    """The requester's own public reply: rejecting a resolution (REQ-INC-096 AC2)."""
    resolved = (await world.act(org, org.admin, item, "resolve")).json()
    rejected = await world.call(
        "POST",
        f"{BASE}/{resolved['id']}/resolution/reject",
        org,
        org.requester,
        json={"comment": "Still jams."},
        headers=PORTAL,
    )
    assert rejected.status_code == 200, rejected.text
    entries = (await timeline(world, org, org.admin, item)).json()["items"]
    return str(next(e["id"] for e in entries if e["created_by"] == str(org.requester)))


async def test_a_requester_sees_and_attaches_to_their_own_incident_but_never_removes(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = await world.create(org, org.admin, group_id=str(org.ga))
    for action in (Action.VIEW, Action.ATTACH):
        owner = await _check(app_db, org, org.requester, OwnerType.WORK_ITEM, item["id"], action)
        assert not isinstance(owner, Exception), (action, owner)
        assert (owner.record_id, owner.private) == (uuid.UUID(item["id"]), False)
    removed = await _check(
        app_db, org, org.requester, OwnerType.WORK_ITEM, item["id"], Action.REMOVE
    )
    assert isinstance(removed, PermissionDenied)  # they see it, but removing is staff work


async def test_another_requester_does_not_even_see_the_incident(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = await world.create(org, org.admin, group_id=str(org.ga))
    for action in (Action.VIEW, Action.ATTACH):
        found = await _check(app_db, org, org.requester2, OwnerType.WORK_ITEM, item["id"], action)
        assert isinstance(found, NotFound), action
    assert isinstance(await _visible(app_db, org, org.requester2, item), NotFound)


async def test_a_requester_attaches_to_their_own_public_reply_only(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = await world.create(org, org.admin, group_id=str(org.ga))
    own = await _requester_reply(world, org, item)
    for action in (Action.VIEW, Action.ATTACH):
        owner = await _check(app_db, org, org.requester, OwnerType.CONVERSATION_ENTRY, own, action)
        assert not isinstance(owner, Exception), (action, owner)
        assert owner.private is False
    assert isinstance(
        await _check(app_db, org, org.requester, OwnerType.CONVERSATION_ENTRY, own, Action.REMOVE),
        PermissionDenied,
    )
    # A technician's public reply: seen, never added to by the requester.
    staff = await say(world, org, org.admin, item, kind="reply", body="<p>On it.</p>")
    assert staff.status_code == 201, staff.text
    theirs = staff.json()["entry"]["id"]
    seen = await _check(
        app_db, org, org.requester, OwnerType.CONVERSATION_ENTRY, theirs, Action.VIEW
    )
    assert not isinstance(seen, Exception), seen
    assert isinstance(
        await _check(
            app_db, org, org.requester, OwnerType.CONVERSATION_ENTRY, theirs, Action.ATTACH
        ),
        PermissionDenied,
    )


async def test_a_private_note_stays_hidden_from_the_requester(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = await world.create(org, org.admin, group_id=str(org.ga))
    note = await say(world, org, org.admin, item, body="<p>Internal.</p>")
    assert note.status_code == 201, note.text
    private = note.json()["entry"]["id"]
    for action in (Action.VIEW, Action.ATTACH, Action.REMOVE):
        found = await _check(
            app_db, org, org.requester, OwnerType.CONVERSATION_ENTRY, private, action
        )
        assert isinstance(found, NotFound), action
    owners = await _visible(app_db, org, org.requester, item)
    assert (OwnerType.WORK_ITEM, uuid.UUID(item["id"])) in owners
    assert (OwnerType.CONVERSATION_ENTRY, uuid.UUID(private)) not in owners


async def test_staff_keep_their_own_rules(world: World, app_db: Database) -> None:
    org = world.a
    item = await world.create(org, org.admin, group_id=str(org.ga))
    owner = await _check(app_db, org, org.tech_a, OwnerType.WORK_ITEM, item["id"], Action.REMOVE)
    assert not isinstance(owner, Exception), owner  # tech_a may edit GA's incident
    hidden = await _check(app_db, org, org.tech_b, OwnerType.WORK_ITEM, item["id"], Action.VIEW)
    assert isinstance(hidden, NotFound)  # GB's technician still cannot see it


def test_file_access_is_registered_at_import_for_the_worker() -> None:
    """The mail fetch runs in the worker, which imports modules without their startup hooks."""
    code = (
        "import app.modules.work_items\n"
        "from app.shared.files.ports import OwnerType, owner_access\n"
        "owner_access(OwnerType.WORK_ITEM); owner_access(OwnerType.CONVERSATION_ENTRY)\n"
    )
    done = subprocess.run(  # noqa: S603 - our own interpreter and a fixed program
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
