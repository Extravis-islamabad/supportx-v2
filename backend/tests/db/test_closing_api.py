"""Resolving, closing and reopening over HTTP (WP-020f; REQ-INC-090, 093-095, 097, 100).

Real PostgreSQL, the incidents test world. Each test names the requirement and criterion.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio

from app.core.database import Database
from app.core.errors import NotFound
from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.work_items.domain.closure import OpenItem, OpenWorkKind
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import closing, conversations, parts, resolution
from tests.db.test_conversation_api import say, timeline
from tests.db.test_incidents_api import BASE, Org, World, field_codes, incidents_world, problem
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    async with incidents_world(migrated_db) as built:
        yield built


async def settings(world: World, org: Org) -> dict[str, Any]:
    read = await world.call("GET", f"{BASE}/settings", org, org.admin)
    assert read.status_code == 200, read.text
    return dict(read.json())


async def change_closure(world: World, org: Org, **body: Any) -> Any:  # noqa: ANN401 - JSON
    current = await settings(world, org)
    return await world.call(
        "PATCH",
        f"{BASE}/settings/closure",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{current["version"]}"'},
    )


async def fresh(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    return dict((await world.get(org, org.admin, item)).json())


async def test_req_inc_090_ac1_resolve_needs_a_resolution_and_keeps_it(world: World) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    refused = await world.act(org, org.admin, item, "resolve", resolution="<p> </p>")
    assert problem(refused) == (422, "closure_rules")
    assert field_codes(refused) == {"resolution": "required"}
    resolved = await world.act(
        org,
        org.admin,
        item,
        "resolve",
        resolution="<p>Restarted the <strong>spooler</strong><script>x</script></p>",
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status_category"] == "resolved"
    assert body["resolved_at"] is not None
    assert body["resolution"] == "<p>Restarted the <strong>spooler</strong></p>"  # sanitised
    assert body["resolution_notified_at"] is None  # nobody has told the requester yet


async def test_req_inc_093_and_094_ac1_close_asks_only_for_the_closure_code(world: World) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    resolved = (await world.act(org, org.admin, item, "resolve")).json()
    refused = await world.act(org, org.admin, resolved, "close", closure_code="")
    assert problem(refused) == (422, "closure_rules")
    assert field_codes(refused) == {"closure_code": "required"}
    wrong = await world.act(org, org.admin, resolved, "close", closure_code="nope")
    assert field_codes(wrong) == {"closure_code": "invalid_choice"}
    closed = await world.act(org, org.admin, resolved, "close", closure_code="workaround")
    assert closed.status_code == 200, closed.text
    assert closed.json()["closure_code"] == "workaround"


async def test_req_inc_094_ac3_rule_fields_are_named_with_the_codes_the_ui_shows(
    world: World,
) -> None:
    org = world.a
    saved = await change_closure(world, org, resolve_requires=["resolution", "category_id"])
    assert saved.status_code == 200, saved.text
    assert saved.json()["closure"]["resolve_requires"] == ["resolution", "category_id"]
    item = await world.create(org, org.admin)
    # The record says what is missing before anyone tries (the move asks for its own field).
    (state,) = [a for a in (await fresh(world, org, item))["actions"] if a["action"] == "resolve"]
    assert state["missing"] == ["category_id"]
    refused = await world.act(org, org.admin, item, "resolve")
    assert field_codes(refused) == {"category_id": "required_to_resolve"}


async def test_req_inc_094_only_known_fields_can_be_required(world: World) -> None:
    org = world.a
    refused = await change_closure(world, org, close_requires=["closure_code", "favourite_colour"])
    assert field_codes(refused) == {"close_requires": "invalid_choice"}


@pytest.fixture
def open_task(world: World) -> Iterator[None]:
    """A fake task checker, after the app registered the real one (WP-020e), then the real one."""
    del world

    async def tasks(_session: object, _record: object) -> list[OpenItem]:
        return [OpenItem(OpenWorkKind.TASKS, "Replace the toner")]

    closing.register_open_work(OpenWorkKind.TASKS, tasks)
    yield
    closing.register_open_work(OpenWorkKind.TASKS, parts.open_tasks, parts.complete_tasks)


@pytest.mark.usefixtures("open_task")
async def test_req_inc_095_ac1_ac4_open_tasks_warn_and_the_confirmation_is_recorded(
    world: World,
) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    warned = await world.act(org, org.admin, item, "resolve")
    assert problem(warned) == (409, "open_work_unconfirmed")
    assert warned.json()["params"]["items"] == "Replace the toner"
    confirmed = await world.act(org, org.admin, item, "resolve", confirm_open_work=True)
    assert confirmed.status_code == 200, confirmed.text
    history = await world.history(org, confirmed.json())
    lines = [c for h in history for c in h["changes"] if c["field"] == "open_work_confirmed"]
    assert [line["new"] for line in lines] == [["Replace the toner"]]


@pytest.mark.usefixtures("open_task")
async def test_req_inc_095_ac2_an_admin_turns_the_warning_into_a_block(world: World) -> None:
    org = world.a
    assert (await change_closure(world, org, open_work={"tasks": "block"})).status_code == 200
    item = await world.create(org, org.admin)
    refused = await world.act(org, org.admin, item, "resolve", confirm_open_work=True)
    assert problem(refused) == (409, "open_work_blocked")


async def test_req_inc_097_reopen_keeps_the_past_and_asks_again(world: World) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    resolved = (
        await world.act(org, org.admin, item, "resolve", resolution="<p>Rebooted</p>")
    ).json()
    closed = (await world.act(org, org.admin, resolved, "close", closure_code="fixed")).json()
    reopened = await world.act(
        org, org.admin, closed, "reopen", reason_code="not_fixed", reason_text="Still jams"
    )
    assert reopened.status_code == 200, reopened.text
    body = reopened.json()
    assert (body["resolution"], body["closure_code"], body["reopen_count"]) == (None, None, 1)
    history = await world.history(org, body)
    seen = {(c["field"], str(c["old"])) for h in history for c in h["changes"]}
    # The earlier resolution and closure code stay in history (REQ-INC-097 AC2).
    assert ("resolution", "<p>Rebooted</p>") in seen
    assert ("closure_code", "fixed") in seen


async def _reaches(session: object) -> str | None:
    """A requester channel that reaches every tenant (the port is per tenant since BUG-02)."""
    del session
    return None


async def test_req_inc_096_auto_close_waits_for_a_channel_that_tells_requesters(
    world: World,
) -> None:
    org = world.a
    assert (await settings(world, org))["closure"]["auto_close_days"] is None  # off by default
    refused = await change_closure(world, org, auto_close_days=3)
    assert field_codes(refused) == {"auto_close_days": "auto_close_needs_notifications"}
    closing.register_requester_channel("email", _reaches)
    try:
        allowed = await change_closure(world, org, auto_close_days=3)
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["closure"]["requester_channels"] == ["email"]
        assert field_codes(await change_closure(world, org, auto_close_days=31)) == {
            "auto_close_days": "out_of_range"
        }
    finally:
        closing.unregister_requester_channel("email")


async def test_req_inc_100_ac2_a_canceled_record_takes_no_edits(world: World) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    canceled = (
        await world.act(org, org.admin, item, "cancel", reason_code="duplicate", reason_text="x")
    ).json()
    edited = await world.call(
        "PATCH",
        f"{BASE}/{canceled['id']}",
        org,
        org.admin,
        json={"subject": "Changed"},
        headers={"If-Match": f'"{canceled["version"]}"'},
    )
    assert problem(edited) == (409, "record_closed")


# --- the requester (session 2) ---------------------------------------------------------------


async def as_requester(world: World, org: Org) -> dict[str, Any]:
    """An assigned incident whose requester is technician B (who may reply in the console)."""
    return await world.create(
        org,
        org.admin,
        requester_id=str(org.tech_b),
        group_id=str(org.gb),
        technician_id=str(org.tech_c),
    )


async def requester_reply(world: World, org: Org, item: dict[str, Any], text: str) -> Any:  # noqa: ANN401 - JSON
    return await say(world, org, org.tech_b, item, kind="reply", body=f"<p>{text}</p>")


async def test_req_inc_051_ac1_a_requester_reply_resumes_awaiting_requester(world: World) -> None:
    org = world.a
    item = await as_requester(world, org)
    waiting = await world.act(
        org,
        org.admin,
        item,
        "wait_requester",
        reason_code="more_information",
        reason_text="Which floor?",
    )
    assert waiting.status_code == 200, waiting.text
    assert (await requester_reply(world, org, waiting.json(), "Third floor")).status_code == 201
    now = await fresh(world, org, item)
    assert now["status"] == "in_progress"
    history = await world.history(org, now)
    assert any((h.get("automation") or {}).get("rule") == "requester_reply" for h in history)


async def test_req_inc_051_ac2_waiting_on_a_third_party_does_not_move(world: World) -> None:
    org = world.a
    item = await as_requester(world, org)
    waiting = await world.act(
        org, org.admin, item, "wait_third_party", reason_code="vendor", reason_text="Vendor"
    )
    assert waiting.status_code == 200, waiting.text
    await requester_reply(world, org, waiting.json(), "Any news?")
    assert (await fresh(world, org, item))["status"] == "awaiting_third_party"


async def test_req_inc_098_ac1_a_reply_within_the_window_reopens(world: World) -> None:
    org = world.a
    item = await as_requester(world, org)
    resolved = (await world.act(org, org.admin, item, "resolve")).json()
    closed = (await world.act(org, org.admin, resolved, "close")).json()
    await requester_reply(world, org, closed, "It jams again")
    now = await fresh(world, org, item)
    assert (now["status"], now["reopen_count"]) == ("in_progress", 1)


async def test_req_inc_098_ac2_a_reply_after_the_window_starts_a_new_record(world: World) -> None:
    org = world.a
    item = await as_requester(world, org)
    resolved = (await world.act(org, org.admin, item, "resolve")).json()
    closed = (await world.act(org, org.admin, resolved, "close")).json()
    await world.sql(
        "UPDATE work_items SET closed_at = now() - interval '8 days' WHERE id = $1",
        uuid.UUID(closed["id"]),
    )
    replied = await requester_reply(world, org, closed, "New problem with the same printer")
    assert replied.status_code == 201, replied.text
    follow_up = replied.json()["follow_up"]
    assert follow_up is not None
    assert (await fresh(world, org, item))["status"] == "closed"  # the old one stays closed
    new = (await world.call("GET", f"{BASE}/{follow_up['id']}", org, org.admin)).json()
    assert new["follows_id"] == closed["id"]
    assert new["display_id"] == follow_up["display_id"]
    # WP-020e: the follow-up is a `follows` link, shown on both records.
    on_new = (await world.call("GET", f"{BASE}/{follow_up['id']}/links", org, org.admin)).json()
    on_old = (await world.call("GET", f"{BASE}/{closed['id']}/links", org, org.admin)).json()
    assert [(x["kind"], x["relation"], x["other_id"]) for x in on_new] == [
        ("follows", "follows", closed["id"])
    ]
    assert [(x["relation"], x["other_id"]) for x in on_old] == [("followed_by", follow_up["id"])]
    assert "New problem with the same printer" in (new["description"] or "")


async def test_req_inc_096_ac1_the_requester_confirms_and_it_closes(world: World) -> None:
    org = world.a
    item = await as_requester(world, org)
    resolved = (await world.act(org, org.admin, item, "resolve")).json()
    stranger = await world.call(
        "POST", f"{BASE}/{resolved['id']}/resolution/confirm", org, org.tech_a
    )
    assert stranger.status_code == 404  # only the record's own requester
    confirmed = await world.call(
        "POST", f"{BASE}/{resolved['id']}/resolution/confirm", org, org.tech_b
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["closed"] is True
    now = await fresh(world, org, item)
    assert (now["status_category"], now["closure_code"]) == ("closed", "confirmed_by_requester")
    again = await world.call("POST", f"{BASE}/{resolved['id']}/resolution/confirm", org, org.tech_b)
    assert problem(again) == (409, "not_resolved")


async def test_req_inc_096_ac2_not_fixed_reopens_with_the_comment(world: World) -> None:
    org = world.a
    item = await as_requester(world, org)
    resolved = (await world.act(org, org.admin, item, "resolve")).json()
    empty = await world.call(
        "POST", f"{BASE}/{resolved['id']}/resolution/reject", org, org.tech_b, json={"comment": " "}
    )
    assert field_codes(empty) == {"comment": "required"}
    rejected = await world.call(
        "POST",
        f"{BASE}/{resolved['id']}/resolution/reject",
        org,
        org.tech_b,
        json={"comment": "Still jams on page 2"},
    )
    assert rejected.status_code == 200, rejected.text
    now = await fresh(world, org, item)
    assert (now["status"], now["reopen_count"]) == ("in_progress", 1)
    entries = (await timeline(world, org, org.admin, item)).json()["items"]
    assert any(
        e["kind"] == "reply" and e["visibility"] == "public" and "page 2" in e["body"]
        for e in entries
    )


async def test_req_inc_096_ac3_auto_close_only_after_the_requester_was_told(
    world: World, app_db: Database
) -> None:
    org = world.a
    told = (await world.act(org, org.admin, await world.create(org, org.admin), "resolve")).json()
    never_told = (
        await world.act(org, org.admin, await world.create(org, org.admin), "resolve")
    ).json()
    closing.register_requester_channel("email", _reaches)
    try:
        assert (await change_closure(world, org, auto_close_days=1)).status_code == 200
        async with app_db.tenant_session(TenantContext(org.tenant)) as session:
            assert await closing.resolution_notified(
                session,
                uuid.UUID(told["id"]),
                event_at=datetime.now(UTC),
                at=datetime.now(UTC) - timedelta(days=4),
            )
        async with app_db.tenant_session(TenantContext(org.tenant)) as session:
            closed = await resolution.auto_close_due(session, INCIDENT, datetime.now(UTC))
        assert closed == 1
    finally:
        closing.unregister_requester_channel("email")
    now = await fresh(world, org, told)
    assert (now["status_category"], now["closure_code"]) == ("closed", "confirmed_by_requester")
    history = await world.history(org, now)
    assert any((h.get("automation") or {}).get("rule") == "auto_close" for h in history)
    # Resolved for days, but nobody told the requester: never auto-closed.
    assert (await fresh(world, org, never_told))["status_category"] == "resolved"


async def test_req_inc_094_a_closure_code_required_to_resolve_is_asked_by_the_move(
    world: World,
) -> None:
    """The resolution and the closure code are not record fields: the move asks for either."""
    org = world.a
    assert (
        await change_closure(world, org, resolve_requires=["resolution", "closure_code"])
    ).status_code == 200
    item = await world.create(org, org.admin)
    (state,) = [a for a in (await fresh(world, org, item))["actions"] if a["action"] == "resolve"]
    assert state["missing"] == []  # nothing to fill on the record: the dialog asks for both
    refused = await world.act(org, org.admin, item, "resolve")
    assert field_codes(refused) == {"closure_code": "required"}
    resolved = await world.act(org, org.admin, item, "resolve", closure_code="workaround")
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["closure_code"] == "workaround"


async def test_d107_existing_tenants_get_the_requester_closure_code_once(world: World) -> None:
    """Seed version 3: tenants seeded before it get "confirmed by requester", exactly once."""
    org = world.a
    await settings(world, org)  # seeded at the current version
    await world.sql(
        "DELETE FROM work_item_reasons WHERE tenant_id = $1 AND code = 'confirmed_by_requester'",
        org.tenant,
    )
    await world.sql(
        "UPDATE work_item_type_settings SET seed_version = 2 WHERE tenant_id = $1", org.tenant
    )
    for _ in range(2):  # the top-up runs once; a second read changes nothing
        codes = [c["code"] for c in (await settings(world, org))["closure_codes"]]
        assert codes.count("confirmed_by_requester") == 1


# --- the requester's reply from outside the console (e-mail WP-024, portal WP-028) ------------


async def _reply_from_outside(
    world: World,
    app_db: Database,
    org: Org,
    item: dict[str, Any],
    user: uuid.UUID,
    *,
    automatic: bool = False,
) -> Any:  # noqa: ANN401 - the follow-up record or None
    async with app_db.tenant_session(TenantContext(org.tenant, user_id=user)) as session:
        subject = await subject_for(session, org.tenant, user)
        record = await session.get(WorkItem, uuid.UUID(item["id"]))
        assert record is not None
        return await conversations.add_requester_reply(
            session,
            INCIDENT,
            record,
            body="<p>It jams again</p>",
            source="email",
            automatic=automatic,
            subject=subject,
            holders=world.app.state.policy,
        )


async def test_a_requester_reply_from_outside_reopens_and_an_auto_reply_does_nothing(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = await world.create(org, org.admin)  # the requester holds no console permission
    resolved = (await world.act(org, org.admin, item, "resolve")).json()
    # An out-of-office: recorded, nothing moves.
    assert (
        await _reply_from_outside(world, app_db, org, resolved, org.requester, automatic=True)
        is None
    )
    assert (await fresh(world, org, item))["status_category"] == "resolved"
    # The requester's own words: reopened within the window (REQ-INC-098).
    assert await _reply_from_outside(world, app_db, org, resolved, org.requester) is None
    assert (await fresh(world, org, item))["status"] == "in_progress"
    entries = (await timeline(world, org, org.admin, item)).json()["items"]
    assert sum(1 for e in entries if e["kind"] == "reply") == 2
    # Anyone else: as if the record did not exist.
    with pytest.raises(NotFound):
        await _reply_from_outside(world, app_db, org, resolved, org.tech_a)
