"""Keycloak user events become notices to the person (REQ-SEC-033 part 2; WP-057 S2b-2).

Lane B's conditions, through the real import run:
- a hint-less event goes to the one tenant the subject is a person in; in two tenants, nothing is
  sent and it is counted unattributed;
- each Keycloak event is marked once: a re-read tells nobody twice;
- at most one lock-out notice an hour, the rest marked quiet; the lock-out says the earliest time;
- a first password is marked quiet as `password_set`, a later one is told;
- an event with no userId is nobody's notice; the marks hold no address.
"""

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.sign_in_import import KeycloakEvent
from app.modules.identity_access.service import security_notice_import as notices
from app.modules.identity_access.service import sign_in_import
from app.modules.identity_access.service.sign_in_import import import_once
from tests.db.test_identity_api import World, _admin_rows, _person, world
from tests.db.test_sign_in_import import FakeReader

__all__ = ["world"]  # the fixture, re-used

BASE = "tenants.test"
EVENT = "identity_access.account_security.changed"
MINUTE = 60_000


def _now_ms() -> int:
    """Real time: a first password is judged against the person's (just made) account."""
    return int(time.time() * 1000) - 30 * MINUTE


def _event(
    event_id: str,
    at_ms: int,
    kind: str,
    *,
    user_id: str | None,
    credential: str | None = None,
) -> KeycloakEvent:
    return KeycloakEvent(
        id=event_id,
        type=kind,
        time_ms=at_ms,
        client_id="supportx-console",
        error=None,
        user_id=user_id,
        ip="192.0.2.7",
        identity_provider=None,
        redirect_uri=None,  # no hint: the one tenant the subject is a person in
        credential_type=credential,
    )


async def _run(world: World, reader: FakeReader, now_ms: int) -> None:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        await import_once(database, reader, base_domain=BASE, now_ms=now_ms + 10_000)
    finally:
        await database.dispose()


async def _told(world: World, tenant: uuid.UUID) -> list[dict[str, Any]]:
    rows = await _admin_rows(
        world.db,
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2 ORDER BY id",
        tenant,
        EVENT,
    )
    return [json.loads(r["envelope"])["payload"] for r in rows]


async def _marks(world: World, tenant: uuid.UUID) -> list[tuple[str, str, bool]]:
    rows = await _admin_rows(
        world.db,
        "SELECT keycloak_event_id, kind, told FROM security_notice_marks WHERE tenant_id = $1"
        " ORDER BY occurred_at",
        tenant,
    )
    return [(r["keycloak_event_id"], r["kind"], r["told"]) for r in rows]


async def _subject(world: World, user: uuid.UUID, subject: str) -> None:
    """Each test its own subject: the database is shared, and two tenants holding one subject
    is exactly what the fallback refuses to guess."""
    await _admin_rows(
        world.db, "UPDATE users SET external_subject = $1 WHERE id = $2", subject, user
    )


async def test_lock_outs_tell_the_person_once_an_hour_with_the_earliest_time(
    world: World,
) -> None:
    subject = f"kc-{uuid.uuid4().hex}"
    await _subject(world, world.a.tech, subject)
    now = _now_ms()
    lock = "USER_DISABLED_BY_TEMPORARY_LOCKOUT"
    reader = FakeReader(
        [
            _event("l1", now - 25 * MINUTE, lock, user_id=subject),
            _event("l2", now - 5 * MINUTE, lock, user_id=subject),  # 20 minutes on: kept quiet
            _event("anon", now - 4 * MINUTE, lock, user_id=None),  # an unknown name: nobody's
        ]
    )
    await _run(world, reader, now)
    await _run(world, reader, now)  # read again: nothing twice
    (told,) = await _told(world, world.a.tenant)
    locked_at = datetime.fromtimestamp((now - 25 * MINUTE) / 1000, UTC)
    assert told["kind"] == "locked_out"
    assert told["user_id"] == str(world.a.tech)
    assert datetime.fromisoformat(told["opens_at"]) == locked_at + timedelta(minutes=15)
    assert "192.0.2.7" not in json.dumps(told)  # never the address
    assert await _marks(world, world.a.tenant) == [
        ("l1", "locked_out", True),
        ("l2", "locked_out", False),
    ]


async def test_a_first_password_is_quiet_and_later_changes_are_told(world: World) -> None:
    newcomer = uuid.UUID(await _person(world, "new@acme.test"))  # made just now
    subject = f"kc-{uuid.uuid4().hex}"
    await _subject(world, newcomer, subject)
    now = _now_ms()
    reader = FakeReader(
        [
            _event(
                "p1", now - 20 * MINUTE, "UPDATE_CREDENTIAL", credential="password", user_id=subject
            ),
            _event(
                "p2", now - 10 * MINUTE, "UPDATE_CREDENTIAL", credential="password", user_id=subject
            ),
            _event("m1", now - 5 * MINUTE, "UPDATE_CREDENTIAL", credential="otp", user_id=subject),
            _event("m2", now - 2 * MINUTE, "REMOVE_CREDENTIAL", credential="otp", user_id=subject),
            _event(
                "x1", now - MINUTE, "REMOVE_CREDENTIAL", credential="password", user_id=subject
            ),  # no notice
        ]
    )
    await _run(world, reader, now)
    assert [t["kind"] for t in await _told(world, world.a.tenant)] == [
        "password_changed",
        "mfa_added",
        "mfa_removed",
    ]
    assert await _marks(world, world.a.tenant) == [
        ("p1", "password_set", False),
        ("p2", "password_changed", True),
        ("m1", "mfa_added", True),
        ("m2", "mfa_removed", True),
    ]


async def test_a_person_in_two_tenants_with_no_hint_is_not_guessed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    counted: list[int] = []
    monkeypatch.setattr(
        sign_in_import, "_unattributed", type("C", (), {"add": lambda _s, n: counted.append(n)})()
    )
    both = f"kc-{uuid.uuid4().hex}"
    await _subject(world, world.a.tech, both)
    await _subject(world, world.b.tech, both)
    now = _now_ms()
    reader = FakeReader(
        [_event("both", now - MINUTE, "UPDATE_CREDENTIAL", user_id=both, credential="otp")]
    )
    await _run(world, reader, now)
    assert await _told(world, world.a.tenant) == []
    assert await _told(world, world.b.tenant) == []
    assert await _marks(world, world.a.tenant) == []
    assert counted == [1]


async def test_marks_go_after_30_days_and_on_erasure(world: World) -> None:
    """Lane B: the daily purge drops marks past 30 days; erasure drops the person's."""
    subject = f"kc-{uuid.uuid4().hex}"
    await _subject(world, world.a.tech, subject)
    now = _now_ms()
    old = now - 31 * 24 * 60 * MINUTE
    reader = FakeReader(
        [
            _event("old", old, "UPDATE_CREDENTIAL", user_id=subject, credential="otp"),
            _event("new", now - MINUTE, "UPDATE_CREDENTIAL", user_id=subject, credential="otp"),
        ]
    )
    await _run(world, reader, old)  # the first run reads a day back: the old one
    await _run(world, reader, now)
    assert [m[0] for m in await _marks(world, world.a.tenant)] == ["old", "new"]
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(world.a.tenant)) as session:
            assert await notices.purge(session, datetime.now(UTC)) == 1
        assert [m[0] for m in await _marks(world, world.a.tenant)] == ["new"]
        async with database.tenant_session(TenantContext(world.a.tenant)) as session:
            assert await notices.forget(session, world.a.tech) == 1
    finally:
        await database.dispose()
    assert await _marks(world, world.a.tenant) == []
