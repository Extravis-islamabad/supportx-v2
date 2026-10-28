"""WP-020f QA findings (~/Desktop/qa-wp020f/QA-REPORT.md): one test per bug, named after it.

Real PostgreSQL, the incidents test world.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY, Database
from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import closing, conversations
from app.modules.work_items.service.notifications import IncidentNotifications
from tests.db.test_closing_api import change_closure, fresh, settings
from tests.db.test_incidents_api import BASE, World, field_codes, incidents_world
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    async with incidents_world(migrated_db) as built:
        yield built


@pytest.fixture
def email_reaches(world: World) -> Iterator[dict[uuid.UUID, str | None]]:
    """An "email" channel whose reach per tenant the test sets (None: reaches)."""
    reach: dict[uuid.UUID, str | None] = {}

    async def reaches(session: AsyncSession) -> str | None:
        context = session.info[SESSION_TENANT_KEY]
        assert isinstance(context, TenantContext)
        return reach.get(context.tenant_id, "mail_not_configured")

    del world  # registered after the app started
    closing.register_requester_channel("email", reaches)
    yield reach
    closing.unregister_requester_channel("email")


async def _resolved_at(app_db: Database, tenant: uuid.UUID, record_id: str) -> datetime:
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        row = await session.get(WorkItem, uuid.UUID(record_id))
        assert row is not None
        assert row.resolved_at is not None
        return row.resolved_at


# --- BUG-02: nothing told the record that the requester was notified -----------------------------


async def test_bug_02_a_channel_reaches_each_tenant_on_its_own_and_says_why(
    world: World, email_reaches: dict[uuid.UUID, str | None]
) -> None:
    a, b = world.a, world.b
    email_reaches[a.tenant] = None  # tenant A's mail works; B's mail is failing
    email_reaches[b.tenant] = "mail_failing"
    assert (await change_closure(world, a, auto_close_days=3)).status_code == 200
    refused = await change_closure(world, b, auto_close_days=3)
    assert field_codes(refused) == {"auto_close_days": "auto_close_needs_notifications"}
    closure_a = (await settings(world, a))["closure"]
    closure_b = (await settings(world, b))["closure"]
    assert closure_a["requester_channels"] == ["email"]
    assert closure_b["requester_channels"] == []
    # The settings screen says why a channel does not reach this tenant's requesters.
    assert closure_b["requester_channel_states"] == [{"channel": "email", "reason": "mail_failing"}]


async def test_bug_02_only_the_current_resolution_starts_the_clock(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = (await world.act(org, org.admin, await world.create(org, org.admin), "resolve")).json()
    first = await _resolved_at(app_db, org.tenant, item["id"])
    reopened = await world.act(
        org, org.admin, item, "reopen", reason_code="not_fixed", reason_text="Still jams"
    )
    again = (await world.act(org, org.admin, reopened.json(), "resolve")).json()
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        # A late delivery of the first resolution's notice does not count for the second.
        assert not await closing.resolution_notified(
            session, uuid.UUID(again["id"]), event_at=first, at=datetime.now(UTC)
        )
    second = await _resolved_at(app_db, org.tenant, again["id"])
    told = datetime.now(UTC)
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        assert await closing.resolution_notified(
            session, uuid.UUID(again["id"]), event_at=second, at=told
        )
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        # Once per resolution: a second channel or a retry changes nothing.
        assert not await closing.resolution_notified(
            session, uuid.UUID(again["id"]), event_at=second, at=told + timedelta(hours=1)
        )
    assert (await fresh(world, org, again))["resolution_notified_at"] is not None


async def test_bug_02_a_delivered_resolution_notice_to_the_requester_starts_the_clock(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = (await world.act(org, org.admin, await world.create(org, org.admin), "resolve")).json()
    resolved_at = await _resolved_at(app_db, org.tenant, item["id"])
    source = IncidentNotifications()
    record_id = uuid.UUID(item["id"])
    now = datetime.now(UTC)

    async def delivered(event_code: str, reasons: tuple[str, ...]) -> Any:  # noqa: ANN401
        async with app_db.tenant_session(TenantContext(org.tenant)) as session:
            await source.delivered(
                session,
                event_code=event_code,
                record_id=record_id,
                user_id=org.requester,
                reasons=reasons,
                event_at=resolved_at,
                at=now,
            )

    # Another notice, or the resolution notice to someone who is not the requester: no clock.
    await delivered("incident.assigned", ("requester",))
    await delivered("incident.resolved", ("assignee", "followers"))
    assert (await fresh(world, org, item))["resolution_notified_at"] is None
    await delivered("incident.resolved", ("requester",))
    assert (await fresh(world, org, item))["resolution_notified_at"] is not None


async def test_bug_02_auto_close_starts_once_a_channel_reaches_and_a_notice_is_delivered(
    world: World, app_db: Database, email_reaches: dict[uuid.UUID, str | None]
) -> None:
    from app.modules.work_items.domain.types import INCIDENT  # noqa: PLC0415 - test-only
    from app.modules.work_items.service import resolution  # noqa: PLC0415 - test-only

    org = world.a
    email_reaches[org.tenant] = None
    assert (await change_closure(world, org, auto_close_days=1)).status_code == 200
    item = (await world.act(org, org.admin, await world.create(org, org.admin), "resolve")).json()
    resolved_at = await _resolved_at(app_db, org.tenant, item["id"])
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        await IncidentNotifications().delivered(
            session,
            event_code="incident.resolved",
            record_id=uuid.UUID(item["id"]),
            user_id=org.requester,
            reasons=("requester",),
            event_at=resolved_at,
            at=datetime.now(UTC) - timedelta(days=4),
        )
    # The tenant's mail stops working: auto-close waits, never closing on a channel that broke.
    email_reaches[org.tenant] = "mail_failing"
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        assert await resolution.auto_close_due(session, INCIDENT, datetime.now(UTC)) == 0
    email_reaches[org.tenant] = None
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        assert await resolution.auto_close_due(session, INCIDENT, datetime.now(UTC)) == 1
    assert (await fresh(world, org, item))["status_category"] == "closed"


# --- BUG-01: a requester's own reply showed as an unsent outgoing reply ------------------------


async def _replies(world: World, org: Any, item: dict[str, Any]) -> list[dict[str, Any]]:  # noqa: ANN401 - the Org fixture
    found = await world.call("GET", f"{BASE}/{item['id']}/conversation", org, org.admin)
    assert found.status_code == 200, found.text
    return [e for e in found.json()["items"] if e["kind"] == "reply"]


async def test_bug_01_a_requester_reply_from_outside_is_received_not_unsent(
    world: World, app_db: Database
) -> None:
    """Whatever the path (reject, e-mail reply), words the requester sent in are received."""
    org = world.a
    item = await world.create(org, org.admin)
    resolved = (await world.act(org, org.admin, item, "resolve")).json()
    # The requester rejects the fix through the portal: their comment is an incoming reply.
    rejected = await world.call(
        "POST",
        f"{BASE}/{item['id']}/resolution/reject",
        org,
        org.requester,
        json={"comment": "Still jams."},
        headers={"X-SupportX-Client": "portal"},
    )
    assert rejected.status_code == 200, rejected.text
    # And replies by e-mail (lane B's WP-024 path through add_requester_reply).
    async with app_db.tenant_session(TenantContext(org.tenant, user_id=org.requester)) as session:
        record = await session.get(WorkItem, uuid.UUID(resolved["id"]))
        assert record is not None
        await conversations.add_requester_reply(
            session,
            INCIDENT,
            record,
            body="<p>Thanks, it works now.</p>",
            source="email",
            automatic=False,
            subject=await subject_for(session, org.tenant, org.requester),
            holders=world.app.state.policy,
        )
    replies = await _replies(world, org, item)
    assert [(r["delivery_state"], r["delivery_reason"]) for r in replies] == [
        ("received", None),
        ("received", None),
    ]


async def test_bug_01_a_technician_reply_still_waits_for_the_email_channel(
    world: World,
) -> None:
    """The same decision keeps staff replies outbound (unchanged behaviour)."""
    org = world.a
    item = await world.create(org, org.admin)
    said = await world.call(
        "POST",
        f"{BASE}/{item['id']}/conversation",
        org,
        org.admin,
        json={
            "kind": "reply",
            "visibility": "public",
            "body": "<p>On it.</p>",
            "reply_mode": "reply",
        },
    )
    assert said.status_code == 201, said.text
    replies = await _replies(world, org, item)
    assert replies[0]["delivery_state"] in {"not_sent", "queued"}


# --- BUG-03: the requester's own moves were filed as automation -----------------------------------


async def _latest_status(world: World, org: Any, item: dict[str, Any], query: str = "") -> Any:  # noqa: ANN401 - JSON
    found = await world.call("GET", f"{BASE}/{item['id']}/history{query}", org, org.admin)
    assert found.status_code == 200, found.text
    return next(e for e in found.json()["items"] if e["kind"] == "status")


async def test_bug_03_confirm_and_reject_are_the_requesters_own_acts(world: World) -> None:
    org = world.a
    for answer, words in (("confirm", "requester_confirmed"), ("reject", "requester_rejected")):
        item = (
            await world.act(org, org.admin, await world.create(org, org.admin), "resolve")
        ).json()
        done = await world.call(
            "POST",
            f"{BASE}/{item['id']}/resolution/{answer}",
            org,
            org.requester,
            json={"comment": "Still jams."} if answer == "reject" else None,
            headers={"X-SupportX-Client": "portal"},
        )
        assert done.status_code == 200, done.text
        entry = await _latest_status(world, org, item)
        assert entry["automation"] is None, answer  # a person did it: no "Automatic" tag
        assert (entry["actor_type"], entry["actor_id"], entry["source"]) == (
            "user",
            str(org.requester),
            "portal",
        )
        assert {"field": "requester_action", "old": None, "new": words} in entry["changes"]
        # The "People" filter shows it; "Automation" does not.
        people = await _latest_status(world, org, item, "?actors=people")
        assert people["change_id"] == entry["change_id"]


async def test_bug_03_an_e_mail_reply_that_resumes_is_the_requesters_act(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = await world.create(org, org.admin, technician_id=str(org.tech_a))
    waiting = (await world.act(org, org.tech_a, item, "wait_requester", "confirmation")).json()
    async with app_db.tenant_session(TenantContext(org.tenant, user_id=org.requester)) as session:
        record = await session.get(WorkItem, uuid.UUID(waiting["id"]))
        assert record is not None
        await conversations.add_requester_reply(
            session,
            INCIDENT,
            record,
            body="<p>Here is the screenshot.</p>",
            source="email",
            automatic=False,
            subject=await subject_for(session, org.tenant, org.requester),
            holders=world.app.state.policy,
        )
    entry = await _latest_status(world, org, item)
    assert entry["automation"] is None
    assert (entry["actor_id"], entry["source"]) == (str(org.requester), "email")
    assert {"field": "requester_action", "old": None, "new": "requester_reply_resumed"} in entry[
        "changes"
    ]


async def test_bug_04_only_the_requesters_confirmation_sets_confirmed_by_requester(
    world: World,
) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    # Not at resolve, not at close: a technician choosing it would hide their own closure.
    for action in ("resolve", "close"):
        if action == "close":
            item = (await world.act(org, org.admin, item, "resolve")).json()
        refused = await world.act(
            org, org.admin, item, action, closure_code="confirmed_by_requester"
        )
        assert refused.status_code == 422, action
        assert field_codes(refused) == {"closure_code": "requester_only"}, action
    # The requester's confirmation still sets it where the rules ask for a code (D-107).
    done = await world.call(
        "POST",
        f"{BASE}/{item['id']}/resolution/confirm",
        org,
        org.requester,
        headers={"X-SupportX-Client": "portal"},
    )
    assert done.status_code == 200, done.text
    assert (await fresh(world, org, item))["closure_code"] == "confirmed_by_requester"


async def test_bug_05_closure_code_and_level_are_pick_lists_in_the_list_fields(
    world: World,
) -> None:
    org = world.a
    retired = await world.call(
        "PATCH",
        f"{BASE}/settings/lists/closure_code/values/duplicate",
        org,
        org.admin,
        json={"disabled": True},
        headers={"If-Match": f'"{(await settings(world, org))["version"]}"'},
    )
    assert retired.status_code == 200, retired.text
    found = await world.call("GET", f"{BASE}/list-fields", org, org.tech_a)
    assert found.status_code == 200, found.text
    fields = {f["name"]: f for f in found.json()}
    # Retired codes too: old records still carry them and a filter must find them.
    assert set(fields["closure_code"]["values"]) == {
        "fixed",
        "workaround",
        "no_fault_found",
        "duplicate",
        "user_error",
        "confirmed_by_requester",
    }
    assert set(fields["level"]["values"]) == {"tier_1", "tier_2", "tier_3", "tier_4"}
    for name in ("closure_code", "level"):
        assert fields[name]["dimension"]["kind"] == "admin_code", name


async def test_wp024_bug_04_an_automatic_reply_keeps_its_flag_on_the_entry(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    async with app_db.tenant_session(TenantContext(org.tenant, user_id=org.requester)) as session:
        record = await session.get(WorkItem, uuid.UUID(item["id"]))
        assert record is not None
        for automatic in (True, False):
            await conversations.add_requester_reply(
                session,
                INCIDENT,
                record,
                body="<p>I am out of office.</p>" if automatic else "<p>Thanks.</p>",
                source="email",
                automatic=automatic,
                subject=await subject_for(session, org.tenant, org.requester),
                holders=world.app.state.policy,
            )
    flags = [e["automatic"] for e in await _replies(world, org, item)]
    assert flags == [True, False]
