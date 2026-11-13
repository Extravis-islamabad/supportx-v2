"""A sign-in from a new browser or device tells the person (REQ-SEC-033; WP-057 S2b-1).

Through the real BFF sign-in and the real notification engine:
- the first sign-in ever is remembered and tells nobody;
- the same browser again tells nobody;
- another browser does: the person gets a security notice naming the device and the place,
  never the address;
- a rotated session ring still recognises the device (the fingerprint moves to the new key);
- only keyed fingerprints are stored, and erasure deletes them.
"""

import json
import uuid
from datetime import UTC, datetime

import asyncpg

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.known_device import fingerprint, fingerprints
from app.modules.identity_access.service import known_devices
from app.modules.notifications.service.engine import dispatch
from app.shared.events import EventEnvelope
from tests.db.test_auth_bff import Bff, bff
from tests.db.test_notifications_api import NO_MAIL

__all__ = ["bff"]  # the fixture, re-used

FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
EVENT = "identity_access.new_device.signed_in"


async def _sql(bff: Bff, query: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(bff.db.admin_url)
    try:
        return list(await conn.fetch(query, *args))
    finally:
        await conn.close()


async def _sign_in_again(bff: Bff, person: object) -> None:
    await bff.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": await bff.csrf()})
    assert (await bff.login(person)).status_code == 302  # type: ignore[arg-type]


async def test_req_sec_033_a_new_browser_tells_the_person_the_same_one_does_not(bff: Bff) -> None:
    a, _b = bff.tenants
    email = f"devices-{uuid.uuid4().hex[:8]}@demo.test"
    person = bff.user("a", email=email)
    assert (await bff.login(person)).status_code == 302  # the first sign-in ever
    await _sign_in_again(bff, person)  # the same browser
    events = await _sql(
        bff, "SELECT 1 FROM outbox_events WHERE tenant_id = $1 AND event_type = $2", a, EVENT
    )
    assert events == []  # neither tells anyone
    bff.client.headers["user-agent"] = FIREFOX_LINUX
    await _sign_in_again(bff, person)  # another browser
    (row,) = await _sql(
        bff, "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2", a, EVENT
    )
    envelope = EventEnvelope.model_validate(json.loads(row["envelope"]))
    assert envelope.payload["device"] == "firefox:linux"
    assert envelope.payload["place"] == {"kind": "internal"}
    assert "ip" not in envelope.payload  # never the address
    # The notification engine tells the person, in the app and (once mail works) by e-mail.
    database = Database(create_engine(bff.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(a)) as session:
            await dispatch(session, NO_MAIL, envelope)
    finally:
        await database.dispose()
    told = await _sql(
        bff,
        "SELECT d.channel, d.state, u.email FROM notification_deliveries d JOIN users u"
        " ON u.tenant_id = d.tenant_id AND u.id = d.user_id"
        " WHERE d.tenant_id = $1 AND d.event_code = 'security.new_device'",
        a,
    )
    assert ("in_app", "sent", email) in {(r["channel"], r["state"], r["email"]) for r in told}
    # Two devices, as keyed fingerprints only.
    stored = await _sql(
        bff,
        "SELECT k.fingerprint FROM known_devices k JOIN users u"
        " ON u.tenant_id = k.tenant_id AND u.id = k.user_id WHERE u.email = $1",
        email,
    )
    assert len(stored) == 2
    assert all(len(r["fingerprint"]) == 32 for r in stored)


async def test_a_rotated_ring_still_knows_the_device_and_erasure_forgets_it(bff: Bff) -> None:
    a, _b = bff.tenants
    person = bff.user("a", email=f"rotate-{uuid.uuid4().hex[:8]}@demo.test")
    assert (await bff.login(person)).status_code == 302
    (user,) = await _sql(
        bff, "SELECT id FROM users WHERE tenant_id = $1 AND email = $2", a, person.email
    )
    user_id = user["id"]
    old_key, new_key = b"o" * 32, b"n" * 32
    device, ip = "chrome:windows", "203.0.113.7"
    now = datetime.now(UTC)
    database = Database(create_engine(bff.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(a)) as session:
            first = await known_devices.remember(
                session, user_id, fingerprints([old_key], user_id, device, ip), now, a
            )
        # The sign-in above remembered the test client's device: this one is another.
        assert first is known_devices.Seen.NEW
        # The ring rotates: the new key leads, the old one is still listed.
        async with database.tenant_session(TenantContext(a)) as session:
            again = await known_devices.remember(
                session, user_id, fingerprints([new_key, old_key], user_id, device, ip), now, a
            )
        assert again is known_devices.Seen.KNOWN  # not "new": nobody is told
        moved = await _sql(
            bff,
            "SELECT 1 FROM known_devices"
            " WHERE tenant_id = $1 AND user_id = $2 AND fingerprint = $3",
            a,
            user_id,
            fingerprint(new_key, user_id, device, ip),
        )
        assert len(moved) == 1  # now under the newest key
        async with database.tenant_session(TenantContext(a)) as session:
            gone = await known_devices.forget(session, user_id)
        assert gone >= 1
    finally:
        await database.dispose()
    left = await _sql(
        bff, "SELECT 1 FROM known_devices WHERE tenant_id = $1 AND user_id = $2", a, user_id
    )
    assert left == []
