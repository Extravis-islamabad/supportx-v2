"""Approval notifications with each approver's own link (WP-030 s3; REQ-SR-025, -026; lane B's
review: one link per recipient, nothing new on a retry or a redelivery, none in-app, no token
in the outbox or the logs).
"""

import json
import re
import uuid
from typing import Any

import pytest
import structlog
import structlog.testing

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.notifications.service.engine import dispatch
from app.shared.events import EventEnvelope
from app.shared.mail.infra import smtp
from tests.db.test_approvals_api import manager_of
from tests.db.test_incidents_api import Org, World, world
from tests.db.test_notifications_api import MAIL, run_engine
from tests.db.test_reply_delivery import FakeSmtp, _send
from tests.db.test_service_requests_api import an_item, raise_request

pytestmark = pytest.mark.db

__all__ = ["world"]  # the fixture, re-used

# The tenant by slug, then the token in the fragment (D-132; ?t= for shared addresses).
LINK = re.compile(r"/approve\?t=[a-z0-9-]+#([A-Za-z0-9_-]{43})")


async def two_approvers(world: World, org: Org) -> dict[str, Any]:
    item = await an_item(
        world,
        org,
        approval={
            "approvers": [
                {"kind": "person", "person_id": str(org.tech_a)},
                {"kind": "person", "person_id": str(org.tech_b)},
            ]
        },
    )
    made = await raise_request(
        world, org, org.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def rows(world: World, org: Org, record: dict[str, Any]) -> list[Any]:
    return await world.sql(
        "SELECT event_code, user_id, channel, text_body FROM notification_deliveries"
        " WHERE tenant_id = $1 AND record_id = $2 ORDER BY created_at",
        org.tenant,
        uuid.UUID(record["id"]),
    )


async def _mails(world: World, org: Org, record: dict[str, Any]) -> dict[uuid.UUID, uuid.UUID]:
    """{approver: queued mail} of the request's approval e-mails."""
    rows = await world.sql(
        "SELECT user_id, mail_id FROM notification_deliveries WHERE tenant_id = $1"
        " AND record_id = $2 AND channel = 'email' AND event_code LIKE '%requested'"
        " AND mail_id IS NOT NULL",
        org.tenant,
        uuid.UUID(record["id"]),
    )
    return {r["user_id"]: r["mail_id"] for r in rows}


async def test_no_token_is_stored_or_logged_until_the_mail_leaves(world: World) -> None:
    """D-132 (Haider's addition, lane B): the stored bodies hold a marker, never a token; the
    sender makes each approver's own link at send; no log line holds it; none in-app."""
    a = world.a
    record = await two_approvers(world, a)
    with structlog.testing.capture_logs() as logs:
        await run_engine(world, a, settings=MAIL)
    mails = await _mails(world, a, record)
    assert set(mails) == {a.tech_a, a.tech_b}
    stored = await world.sql(
        "SELECT text_body, html_body, links FROM mail_messages WHERE id = ANY($1::uuid[])",
        list(mails.values()),
    )
    for row in stored:
        assert "[[supportx-link:approval_link]]" in row["text_body"]
        assert not LINK.search(row["text_body"] + (row["html_body"] or ""))
        assert row["links"] is not None
    assert (
        await world.sql("SELECT count(*) AS n FROM action_links WHERE tenant_id = $1", a.tenant)
    )[0]["n"] == 0
    server = FakeSmtp()
    with structlog.testing.capture_logs() as more:
        for mail_id in mails.values():
            assert await _send(world, a, mail_id, server) == "sent"
    sent = {str(m["To"]): m.get_body(("plain",)).get_content() for m in server.sent}  # type: ignore[union-attr]  # a plain part is always built
    tokens = {to: LINK.findall(body) for to, body in sent.items()}
    assert all(len(found) == 1 for found in tokens.values())
    assert len({t[0] for t in tokens.values()}) == 2  # one link per recipient, never shared
    links = await world.sql("SELECT recipient_id FROM action_links WHERE tenant_id = $1", a.tenant)
    assert sorted(r["recipient_id"] for r in links) == sorted([a.tech_a, a.tech_b])
    after = await world.sql(
        "SELECT text_body, html_body FROM mail_messages WHERE id = ANY($1::uuid[])",
        list(mails.values()),
    )
    secrets = [t[0] for t in tokens.values()]
    assert not any(
        t in (r["text_body"] or "") + (r["html_body"] or "") for r in after for t in secrets
    )
    outbox = await world.sql("SELECT envelope FROM outbox_events WHERE tenant_id = $1", a.tenant)
    assert not any(t in str(r["envelope"]) for r in outbox for t in secrets)
    assert not any(t in str(entry) for entry in [*logs, *more] for t in secrets)
    in_app = await world.sql(
        "SELECT title, link FROM notifications WHERE tenant_id = $1 AND user_id = ANY($2::uuid[])",
        a.tenant,
        [a.tech_a, a.tech_b],
    )
    assert in_app
    assert not any("approval" in f"{r['link']}" and "#" in f"{r['link']}" for r in in_app)


async def test_a_retry_makes_a_fresh_link_and_the_old_one_dies(world: World) -> None:
    """Lane B: a fresh token invalidates the one from an attempt that never left."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    await raise_request(world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"})
    await run_engine(world, a, settings=MAIL)
    [row] = await world.sql(
        "SELECT id FROM mail_messages WHERE tenant_id = $1 AND links IS NOT NULL", a.tenant
    )
    server = FakeSmtp()
    server.answer = smtp.TemporaryFailure(code="server_busy")
    assert await _send(world, a, row["id"], server) == "queued"  # minted, never left
    server.answer = None
    await world.sql("UPDATE mail_messages SET next_attempt_at = now() WHERE id = $1", row["id"])
    assert await _send(world, a, row["id"], server) == "sent"
    live = await world.sql(
        "SELECT count(*) AS n FROM action_links WHERE tenant_id = $1 AND revoked_at IS NULL",
        a.tenant,
    )
    assert live[0]["n"] == 1  # only the link in the e-mail that left works


async def test_a_redelivered_event_sends_no_second_email(world: World) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    record = (
        await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
        )
    ).json()
    await run_engine(world, a, settings=MAIL)
    opened = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'work_items.approval.changed' ORDER BY id",
        a.tenant,
    )
    envelope = EventEnvelope.model_validate(json.loads(opened[0]["envelope"]))
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            await dispatch(session, MAIL, envelope)  # the same event again
    finally:
        await database.dispose()
    assert len(await _mails(world, a, record)) == 1


async def test_a_fallback_approval_tells_the_administrators_in_app_without_a_link(
    world: World,
) -> None:
    a = world.a
    item = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    record = (
        await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
        )
    ).json()  # the requester has no manager: the administrators hold it
    await run_engine(world, a)
    found = [r for r in await rows(world, a, record) if r["event_code"].endswith("fallback")]
    assert found
    assert {r["channel"] for r in found} == {"in_app"}
    assert a.admin in {r["user_id"] for r in found}
    links = await world.sql("SELECT count(*) AS n FROM action_links WHERE tenant_id = $1", a.tenant)
    assert links[0]["n"] == 0
