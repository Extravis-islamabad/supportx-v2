"""Microsoft 365 and Gmail mailboxes over HTTP and on PostgreSQL (WP-024 session 2; REQ-INT-050).

The providers are `fake_providers` (no real account, no network). Covers: the settings an admin
enters, the consent round trip through the callback, reading mail into incidents, and a failing
mailbox or an expiring credential reaching the people who manage mailboxes.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.integrations.service import connections
from app.modules.integrations.service.fetching import fetch_mailbox, warn_expiring
from app.modules.integrations.tests.fake_providers import FakeProviders, endpoint_settings
from app.shared.files.keyring import KeyRing
from tests.db.test_files_api import audit_actions
from tests.db.test_incidents_api import World, field_codes, world
from tests.db.test_notifications_api import deliveries, run_engine

__all__ = ["world"]  # fixture, re-used

pytestmark = [pytest.mark.db]

BASE = "/integrations/mailboxes"
ADDRESS = "help@alpha.test"
SENDER = "it-requester@alpha.test"
GRAPH_APP: dict[str, Any] = {
    "address": ADDRESS,
    "protocol": "graph",
    "auth_model": "app",
    "directory_id": "dir-1",
    "client_id": "app-1",
    "credential_kind": "secret",
    "client_secret": "s3cret",
    "allowed_domains": ["alpha.test"],
}
GMAIL: dict[str, Any] = {
    "address": ADDRESS,
    "protocol": "gmail",
    "auth_model": "delegated",
    "client_id": "app-1",
    "credential_kind": "secret",
    "client_secret": "s3cret",
    "allowed_domains": ["alpha.test"],
}


@pytest.fixture
def fake() -> Iterator[FakeProviders]:
    providers = FakeProviders()
    connections.use_transport(providers.transport())
    yield providers
    connections.use_transport(None)


def _configure(world: World) -> KeyRing:
    keys = KeyRing.generate()
    world.app.state.settings = world.app.state.settings.model_copy(
        update={"files_keys": SecretStr(keys), **endpoint_settings()}
    )
    return KeyRing.parse(keys)


async def _add(world: World, body: dict[str, Any]) -> httpx.Response:
    return await world.call(
        "POST",
        BASE,
        world.a,
        world.a.admin,
        json=body,
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )


async def _sign_in(
    world: World, fake: FakeProviders, mailbox_id: str, account: str
) -> httpx.Response:
    started = await world.call("POST", f"{BASE}/{mailbox_id}/sign-in", world.a, world.a.admin)
    assert started.status_code == 200, started.text
    state, code = fake.sign_in(account, started.json()["authorize_url"])
    return await world.call(
        "GET",
        "/integrations/oauth/callback",
        world.a,
        world.a.admin,
        params={"state": state, "code": code},
    )


def _back(response: httpx.Response) -> dict[str, str]:
    """Where the callback sends the browser: Admin > Mail with the result."""
    assert response.status_code == 303, response.text
    location = urlsplit(response.headers["location"])
    assert location.path.endswith("/admin/mail")
    return {k: v[0] for k, v in parse_qs(location.query).items()}


async def _fetch(world: World, mailbox_id: str, ring: KeyRing) -> int:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        return await fetch_mailbox(
            database, world.app.state.settings, world.a.tenant, uuid.UUID(mailbox_id), ring=ring
        )
    finally:
        await database.dispose()


async def _requester(world: World) -> None:
    """A known sender: the org's requester gets the test address."""
    await world.sql("UPDATE users SET email = $1 WHERE id = $2", SENDER, world.a.requester)


def _raw(subject: str) -> bytes:
    return (
        f"From: Sara <{SENDER}>\r\nTo: {ADDRESS}\r\nSubject: {subject}\r\n"
        f"Message-ID: <{uuid.uuid4().hex}@alpha.test>\r\n\r\nIt jams every morning.\r\n"
    ).encode()


async def test_a_microsoft_365_mailbox_with_app_permission(
    world: World, fake: FakeProviders
) -> None:
    """Nobody signs in; the secret is sealed and never comes back (D-109 (8))."""
    _configure(world)
    created = await _add(world, GRAPH_APP)
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["protocol"], body["needs_sign_in"], body["signed_in"]) == ("graph", False, False)
    assert body["has_password"] is True
    assert "s3cret" not in created.text
    rows = await world.sql(
        "SELECT secret_sealed FROM mailboxes WHERE id = $1", uuid.UUID(body["id"])
    )
    assert b"s3cret" not in bytes(rows[0]["secret_sealed"])
    tested = await world.call("POST", f"{BASE}/{body['id']}/test", world.a, world.a.admin, json={})
    assert tested.json() == {"ok": False, "reason": "mailbox_not_found_at_provider"}
    fake.mailboxes[ADDRESS] = []
    tested = await world.call("POST", f"{BASE}/{body['id']}/test", world.a, world.a.admin, json={})
    assert tested.json() == {"ok": True, "reason": None}


async def test_the_form_asks_for_what_each_kind_needs(world: World) -> None:
    _configure(world)
    graph = await _add(world, GRAPH_APP | {"directory_id": None, "client_secret": None})
    assert field_codes(graph) == {"directory_id": "required", "client_secret": "required"}
    gmail = await _add(world, GMAIL | {"auth_model": "app"})
    assert field_codes(gmail) == {"auth_model": "mailbox_auth_model_unsupported"}
    imap = await _add(world, {"address": ADDRESS, "host": "imap.alpha.test", "username": "u"})
    assert field_codes(imap) == {"password": "required"}
    certificate = await _add(world, GRAPH_APP | {"credential_kind": "certificate"})
    assert field_codes(certificate) == {"client_secret": "oauth_certificate_invalid"}


async def test_gmail_signs_in_as_the_mailbox_and_reads_mail_into_incidents(
    world: World, fake: FakeProviders
) -> None:
    ring = _configure(world)
    await _requester(world)
    created = (await _add(world, GMAIL)).json()
    assert created["needs_sign_in"] is True
    back = _back(await _sign_in(world, fake, created["id"], ADDRESS))
    assert back == {"sign_in": "ok", "mailbox": created["id"]}
    listed = (await world.call("GET", BASE, world.a, world.a.admin)).json()
    assert listed[0]["signed_in"] is True
    actions = await audit_actions(world, world.a)
    assert {"mailbox.consent_started", "mailbox.connected"} <= set(actions)

    fake.deliver(ADDRESS, _raw("Printer jams"))
    assert await _fetch(world, created["id"], ring) == 1
    made = await world.sql(
        "SELECT subject, channel FROM work_items WHERE tenant_id = $1 AND subject = 'Printer jams'",
        world.a.tenant,
    )
    assert [(r["subject"], r["channel"]) for r in made] == [("Printer jams", "email")]
    assert fake.mailboxes[ADDRESS][0].unread is False  # marked only after it was stored
    assert await _fetch(world, created["id"], ring) == 0  # read once


async def test_a_sign_in_as_another_account_is_refused_and_shown(
    world: World, fake: FakeProviders
) -> None:
    _configure(world)
    created = (await _add(world, GMAIL)).json()
    back = _back(await _sign_in(world, fake, created["id"], "ceo@alpha.test"))
    assert back == {"sign_in": "oauth_wrong_account", "mailbox": created["id"]}
    rows = await world.sql(
        "SELECT token_sealed, oauth_state_hash FROM mailboxes WHERE id = $1",
        uuid.UUID(created["id"]),
    )
    assert (rows[0]["token_sealed"], rows[0]["oauth_state_hash"]) == (None, None)


async def test_an_unknown_or_declined_sign_in_changes_nothing(
    world: World, fake: FakeProviders
) -> None:
    _configure(world)
    created = (await _add(world, GMAIL)).json()
    unknown = await world.call(
        "GET",
        "/integrations/oauth/callback",
        world.a,
        world.a.admin,
        params={"state": "forged", "code": "x"},
    )
    assert _back(unknown) == {"sign_in": "oauth_consent_expired"}
    started = await world.call("POST", f"{BASE}/{created['id']}/sign-in", world.a, world.a.admin)
    state, _ = fake.sign_in(ADDRESS, started.json()["authorize_url"])
    declined = await world.call(
        "GET",
        "/integrations/oauth/callback",
        world.a,
        world.a.admin,
        params={"state": state, "error": "access_denied"},
    )
    assert _back(declined) == {"sign_in": "oauth_consent_declined", "mailbox": created["id"]}


async def test_a_sign_in_belongs_to_its_tenant(world: World, fake: FakeProviders) -> None:
    """RLS: another tenant's admin cannot finish (or even find) this tenant's consent."""
    _configure(world)
    created = (await _add(world, GMAIL)).json()
    started = await world.call("POST", f"{BASE}/{created['id']}/sign-in", world.a, world.a.admin)
    state, code = fake.sign_in(ADDRESS, started.json()["authorize_url"])
    stolen = await world.call(
        "GET",
        "/integrations/oauth/callback",
        world.b,
        world.b.admin,
        params={"state": state, "code": code},
    )
    assert _back(stolen) == {"sign_in": "oauth_consent_expired"}


async def test_only_mailbox_managers_start_a_sign_in(world: World, fake: FakeProviders) -> None:
    del fake
    _configure(world)
    created = (await _add(world, GMAIL)).json()
    refused = await world.call("POST", f"{BASE}/{created['id']}/sign-in", world.a, world.a.tech_a)
    assert refused.status_code == 403
    app_box = (await _add(world, GRAPH_APP | {"address": "other@alpha.test"})).json()
    not_needed = await world.call("POST", f"{BASE}/{app_box['id']}/sign-in", world.a, world.a.admin)
    assert not_needed.status_code == 409
    assert not_needed.json()["code"] == "mailbox_sign_in_not_needed"


async def test_a_failing_mailbox_tells_its_admins_once(world: World, fake: FakeProviders) -> None:
    """Never silent: the mail page shows it, and the people who manage mailboxes are told."""
    ring = _configure(world)
    created = (await _add(world, GRAPH_APP)).json()
    fake.refuse_with = "invalid_client"  # the secret expired at Microsoft
    await _fetch(world, created["id"], ring)
    await _fetch(world, created["id"], ring)  # still failing: no second notice
    rows = await world.sql(
        "SELECT state, state_reason FROM mailboxes WHERE id = $1", uuid.UUID(created["id"])
    )
    assert (rows[0]["state"], rows[0]["state_reason"]) == ("failing", "oauth_client_rejected")
    events = await world.sql(
        "SELECT envelope->'payload' AS payload FROM outbox_events"
        " WHERE tenant_id = $1 AND event_type = 'integrations.mailbox.failing'"
        " AND aggregate_id = $2",
        world.a.tenant,
        created["id"],
    )
    assert len(events) == 1
    assert "s3cret" not in str(events[0]["payload"])
    await run_engine(world, world.a)
    sent = await deliveries(world, world.a, created)
    assert {(r["event_code"], r["user_id"]) for r in sent} >= {("mailbox.failing", world.a.admin)}
    assert world.a.tech_a not in {r["user_id"] for r in sent}  # not a mailbox manager


async def test_an_expiring_secret_is_announced_ahead_once(
    world: World, fake: FakeProviders
) -> None:
    del fake
    _configure(world)
    soon = datetime.now(UTC) + timedelta(days=5)
    created = (await _add(world, GRAPH_APP | {"credential_expires_at": soon.isoformat()})).json()
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        for _ in range(2):
            async with database.tenant_session(TenantContext(world.a.tenant)) as session:
                await warn_expiring(session)
    finally:
        await database.dispose()
    await run_engine(world, world.a)
    sent = await deliveries(world, world.a, created)
    told = [
        r["channel"]
        for r in sent
        if r["user_id"] == world.a.admin and r["event_code"] == "mailbox.credential_expiring"
    ]
    assert sorted(told) == ["email", "in_app"]  # once, on each channel
