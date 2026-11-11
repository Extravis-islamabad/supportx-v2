"""The connector secrets store with real mailboxes (WP-040 session 1; REQ-INT-003, REQ-SEC-042).

Expand phase (migration 0045): every write goes to the store and to the mailbox's old column,
reads prefer the store, and a store copy that cannot be read falls back to the old column
without ever being silent (counted, logged by code, the mailbox degraded in the catalogue).
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from structlog.testing import capture_logs

from app.core.tenancy import TenantContext
from app.modules.integrations.service import secrets
from app.modules.integrations.tests.fake_providers import FakeProviders
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World
from tests.db.test_mail_oauth_api import (
    ADDRESS,
    GMAIL,
    _add,
    _back,
    _configure,
    _fetch,
    _raw,
    _requester,
    _sign_in,
    fake,
)
from tests.db.test_mailboxes_api import add, with_key_ring

__all__ = ["fake", "module_world", "shared_world"]  # fixtures, re-used

pytestmark = [pytest.mark.db, MODULE_LOOP]

BASE = "/integrations/mailboxes"


class Counted:
    """Stands in for the fallback counter: what was counted, by code."""

    def __init__(self) -> None:
        self.codes: list[str] = []

    def add(self, amount: int, attributes: dict[str, str]) -> None:
        assert amount == 1
        self.codes.append(attributes["code"])


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> Counted:
    counter = Counted()
    monkeypatch.setattr(secrets, "_fallbacks", counter)
    return counter


async def _store(world: World, mailbox_id: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT s.id, s.role, s.secret_type, s.sealed, s.set_at, s.deleted_at,"
        " m.secret_ref, m.token_ref, m.secret_sealed, m.token_sealed"
        " FROM connector_secrets s JOIN mailboxes m ON m.id = s.owner_id"
        " WHERE s.owner_id = $1 ORDER BY s.created_at",
        uuid.UUID(mailbox_id),
    )
    return [dict(r) for r in rows]


async def _catalogue_instance(world: World) -> dict[str, Any]:
    response = await world.call("GET", "/integrations/catalogue", world.a, world.a.admin)
    (kind,) = [k for k in response.json() if k["code"] == "mailbox"]
    (instance,) = kind["instances"]
    assert isinstance(instance, dict)
    return instance


async def test_a_saved_password_lives_in_the_store_and_rotating_keeps_its_reference(
    world: World,
) -> None:
    with_key_ring(world)
    created = (await add(world)).json()
    (first,) = await _store(world, created["id"])
    assert (first["role"], first["secret_type"]) == ("credential", "password")
    assert first["secret_ref"] == first["id"]
    assert bytes(first["sealed"]) == bytes(first["secret_sealed"])  # both copies the same
    assert b"s3cret-imap" not in bytes(first["sealed"])

    rotated = await world.call(
        "PATCH",
        f"{BASE}/{created['id']}",
        world.a,
        world.a.admin,
        json={"password": "n3w-imap"},
        headers={"If-Match": f'"{created["version"]}"'},
    )
    assert rotated.status_code == 200, rotated.text
    assert "n3w-imap" not in rotated.text
    (second,) = await _store(world, created["id"])
    assert second["id"] == first["id"]  # the same reference: what uses it never changes
    assert bytes(second["sealed"]) != bytes(first["sealed"])
    assert bytes(second["sealed"]) == bytes(second["secret_sealed"])
    assert second["set_at"] > first["set_at"]  # its age starts again


async def test_a_broken_store_copy_still_fetches_and_shows_degraded(
    world: World, fake: FakeProviders, counted: Counted
) -> None:
    ring = _configure(world)
    await _requester(world)
    created = (await _add(world, GMAIL)).json()
    _back(await _sign_in(world, fake, created["id"], ADDRESS))
    stored = {r["role"]: r for r in await _store(world, created["id"])}
    assert set(stored) == {"credential", "refresh_token"}
    (refresh,) = fake.refresh_tokens
    # The move went wrong for the refresh token: its store copy no longer opens.
    await world.sql(
        "UPDATE connector_secrets SET sealed = $1 WHERE id = $2",
        b"\x00" * 64,
        stored["refresh_token"]["id"],
    )
    fake.deliver(ADDRESS, _raw("Printer on fire"))
    with capture_logs() as logged:
        assert await _fetch(world, created["id"], ring) == 1  # the mailbox keeps working
    assert counted.codes == ["store_unreadable"]
    (mailbox,) = await world.sql(
        "SELECT state, secret_fallback_at FROM mailboxes WHERE id = $1", uuid.UUID(created["id"])
    )
    assert mailbox["state"] == "working"
    assert mailbox["secret_fallback_at"] is not None
    degraded = await _catalogue_instance(world)
    assert (degraded["status"], degraded["reason"]) == ("degraded", "secret_store_fallback")
    (listed,) = (await world.call("GET", BASE, world.a, world.a.admin)).json()
    assert listed["degraded_reason"] == "secret_store_fallback"  # the mail page too
    (warning,) = [e for e in logged if e["event"] == "connector_secret_fallback"]
    assert warning["code"] == "store_unreadable"
    for value in ("s3cret", refresh):
        assert value not in repr(logged)  # codes only, never a secret

    # Fixed (the store's copy opens again): the next fetch clears the mark.
    await world.sql(
        "UPDATE connector_secrets SET sealed = m.token_sealed FROM mailboxes m"
        " WHERE connector_secrets.id = $1 AND m.id = connector_secrets.owner_id",
        stored["refresh_token"]["id"],
    )
    await _fetch(world, created["id"], ring)
    assert (await _catalogue_instance(world))["status"] == "active"
    assert counted.codes == ["store_unreadable"]


async def test_when_both_copies_are_broken_the_mailbox_fails_visibly(
    world: World, fake: FakeProviders, counted: Counted
) -> None:
    ring = _configure(world)
    created = (await _add(world, GMAIL)).json()
    _back(await _sign_in(world, fake, created["id"], ADDRESS))
    await world.sql(
        "UPDATE connector_secrets SET sealed = $1 WHERE owner_id = $2 AND role = 'refresh_token'",
        b"\x00" * 64,
        uuid.UUID(created["id"]),
    )
    await world.sql(
        "UPDATE mailboxes SET token_sealed = $1 WHERE id = $2",
        b"\x00" * 64,
        uuid.UUID(created["id"]),
    )
    assert await _fetch(world, created["id"], ring) == 0
    failed = await _catalogue_instance(world)
    assert (failed["status"], failed["reason"]) == ("failed", "mailbox_secret_unreadable")
    assert counted.codes == []  # nothing fell back: it failed, and the failing notice says so


async def test_a_connection_test_saves_no_degraded_mark(
    world: World, fake: FakeProviders, counted: Counted
) -> None:
    _configure(world)
    created = (await _add(world, GMAIL)).json()
    _back(await _sign_in(world, fake, created["id"], ADDRESS))
    await world.sql(
        "UPDATE mailboxes SET secret_ref = NULL WHERE id = $1", uuid.UUID(created["id"])
    )
    tested = await world.call(
        "POST", f"{BASE}/{created['id']}/test", world.a, world.a.admin, json={}
    )
    assert tested.json()["ok"] is True, tested.text
    assert counted.codes == ["not_moved"]  # counted all the same
    (mailbox,) = await world.sql(
        "SELECT secret_fallback_at FROM mailboxes WHERE id = $1", uuid.UUID(created["id"])
    )
    assert mailbox["secret_fallback_at"] is None  # REQ-INT-002 AC1: a test saves nothing


async def test_a_removed_mailbox_keeps_no_secret(world: World) -> None:
    with_key_ring(world)
    created = (await add(world)).json()
    removed = await world.call(
        "DELETE",
        f"{BASE}/{created['id']}",
        world.a,
        world.a.admin,
        headers={"If-Match": f'"{created["version"]}"'},
    )
    assert removed.status_code == 204, removed.text
    (row,) = await _store(world, created["id"])
    assert row["deleted_at"] is not None
    assert (row["secret_ref"], row["secret_sealed"]) == (None, None)


async def test_the_secrets_store_is_isolated_by_rls(world: World) -> None:
    with_key_ring(world)
    created = (await add(world)).json()
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        rows = (await session.execute(text("SELECT id FROM connector_secrets"))).all()
        assert rows == []
        changed = await session.execute(
            text("UPDATE connector_secrets SET key_id = 'x' WHERE owner_id = :id"),
            {"id": uuid.UUID(created["id"])},
        )
        assert changed.rowcount == 0
    (row,) = await _store(world, created["id"])
    assert row["deleted_at"] is None


# --- "ending in ..." (product owner, 2026-11-02: display only, never for a password) ----------

LONG_SECRET = "Q8~kz1rT0vYp4Lm2Xc7Wn9Bf3a"


async def test_a_password_never_shows_any_of_its_characters(world: World) -> None:
    with_key_ring(world)
    created = await add(world)
    credential = created.json()["credential"]
    assert (credential["secret_type"], credential["last_four"]) == ("password", None)
    (row,) = await _store(world, created.json()["id"])
    with pytest.raises(Exception, match="no_password_ending"):  # the table refuses it too
        await world.sql("UPDATE connector_secrets SET last_four = 'imap' WHERE id = $1", row["id"])


async def test_a_long_client_secret_shows_only_its_last_four(
    world: World, fake: FakeProviders
) -> None:
    del fake
    _configure(world)
    created = await _add(world, GMAIL | {"client_secret": LONG_SECRET})
    assert created.status_code == 201, created.text
    assert created.json()["credential"]["last_four"] == "Bf3a"
    assert LONG_SECRET not in created.text
    listed = await world.call("GET", BASE, world.a, world.a.admin)
    assert LONG_SECRET not in listed.text
    assert listed.json()[0]["credential"]["name"].endswith(".credential")


async def test_a_moved_secret_gets_its_ending_when_next_used(
    world: World, fake: FakeProviders
) -> None:
    ring = _configure(world)
    fake.client_secret = LONG_SECRET  # the provider knows the app by this secret
    created = (await _add(world, GMAIL | {"client_secret": LONG_SECRET})).json()
    _back(await _sign_in(world, fake, created["id"], ADDRESS))
    await world.sql(  # as migration 0045 left it: copied, never opened
        "UPDATE connector_secrets SET last_four = NULL WHERE owner_id = $1",
        uuid.UUID(created["id"]),
    )
    await _fetch(world, created["id"], ring)
    endings = {
        r["role"]: r["last_four"]
        for r in await world.sql(
            "SELECT role, last_four FROM connector_secrets WHERE owner_id = $1",
            uuid.UUID(created["id"]),
        )
    }
    assert endings["credential"] == "Bf3a"
    (refresh,) = fake.refresh_tokens
    assert endings["refresh_token"] == (refresh[-4:] if len(refresh) >= 16 else None)
