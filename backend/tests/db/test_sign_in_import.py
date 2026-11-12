"""Keycloak's login events into the right tenant's sign-in log (REQ-AUD-015; WP-057 S1b).

Lane B's rules: an event goes to the one tenant its identity provider or address names, never
to every tenant the person is in; the shared address is counted, not guessed; re-reading the
same events writes nothing twice; the cursor moves on after the rows are in.
"""

import uuid
from dataclasses import dataclass, field

from app.core.database import Database, create_engine
from app.modules.identity_access.domain.sign_in_import import KeycloakEvent
from app.modules.identity_access.service.sign_in_import import import_once
from tests.db.test_identity_api import World, _admin_rows, world

__all__ = ["world"]  # the fixture, re-used

BASE = "tenants.test"
NOW_MS = 1_800_000_000_000
REALM = "supportx-import-test"


@dataclass
class FakeReader:
    """The realm's events, served oldest first from `since_ms` like Keycloak (inclusive)."""

    events: list[KeycloakEvent]
    realm: str = REALM
    asked_since: list[int] = field(default_factory=list)

    async def realm_events(
        self, types: tuple[str, ...], since_ms: int, *, first: int, limit: int
    ) -> list[KeycloakEvent]:
        self.asked_since.append(since_ms)
        found = sorted(
            (e for e in self.events if e.type in types and e.time_ms >= since_ms),
            key=lambda e: e.time_ms,
        )
        return found[first : first + limit]

    async def close(self) -> None:
        return None


def _event(
    event_id: str,
    at_ms: int,
    *,
    client_id: str = "supportx-console",
    error: str = "invalid_user_credentials",
    user_id: str | None = None,
    identity_provider: str | None = None,
    redirect_uri: str | None = None,
) -> KeycloakEvent:
    return KeycloakEvent(
        id=event_id,
        type="LOGIN_ERROR",
        time_ms=at_ms,
        client_id=client_id,
        error=error,
        user_id=user_id,
        ip="192.0.2.7",
        identity_provider=identity_provider,
        redirect_uri=redirect_uri,
    )


async def _slug(world: World, tenant: uuid.UUID) -> str:
    (row,) = await _admin_rows(world.db, "SELECT slug FROM tenants WHERE id = $1", tenant)
    return str(row["slug"])


async def _rows(world: World, tenant: uuid.UUID) -> list[dict[str, object]]:
    found = await _admin_rows(
        world.db,
        "SELECT keycloak_event_id, outcome, reason, method, app, user_id, host(ip) AS ip,"
        " identity_provider FROM sign_in_events WHERE tenant_id = $1 AND source = 'keycloak'"
        " ORDER BY occurred_at",
        tenant,
    )
    return [dict(r) for r in found]


async def test_events_land_in_the_one_tenant_they_name_once(world: World) -> None:
    a, b = world.a, world.b
    assert (await world.add_oidc(a)).status_code == 201
    (alias,) = set(world.admin.providers)
    slug_a, slug_b = await _slug(world, a.tenant), await _slug(world, b.tenant)
    await _admin_rows(
        world.db, "UPDATE users SET external_subject = 'kc-import' WHERE id = $1", b.tech
    )
    reader = FakeReader(
        [
            # a's identity provider refused: a's log, single sign-on.
            _event(
                "e-idp",
                NOW_MS - 3000,
                error="identity_provider_login_failure",
                identity_provider=alias,
            ),
            # A wrong password on b's address, by a person b knows.
            _event(
                "e-host",
                NOW_MS - 2000,
                user_id="kc-import",
                redirect_uri=f"https://{slug_b}.{BASE}/api/v1/auth/callback",
            ),
            # The shared address names nobody: counted, never written.
            _event("e-shared", NOW_MS - 1500, redirect_uri=f"https://{BASE}/api/v1/auth/callback"),
            # A service account's own failure is no person's sign-in.
            _event("e-service", NOW_MS - 1000, client_id="supportx-identity"),
            # An alias that names a's slug but is not a's provider: refused as a hint.
            _event("e-forged", NOW_MS - 500, identity_provider=f"sx-{slug_a}-zz"),
        ]
    )
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        assert await import_once(database, reader, base_domain=BASE, now_ms=NOW_MS) == 2
        # Read again (the cursor is inclusive): nothing written twice.
        assert await import_once(database, reader, base_domain=BASE, now_ms=NOW_MS) == 0
    finally:
        await database.dispose()

    assert await _rows(world, a.tenant) == [
        {
            "keycloak_event_id": "e-idp",
            "outcome": "failed",
            "reason": "identity_provider_refused",
            "method": "single_sign_on",
            "app": "console",
            "user_id": None,
            "ip": "192.0.2.7",
            "identity_provider": alias,
        }
    ]
    (host_row,) = await _rows(world, b.tenant)
    assert (host_row["keycloak_event_id"], host_row["reason"], host_row["user_id"]) == (
        "e-host",
        "wrong_password",
        b.tech,
    )
    assert host_row["method"] == "password"
    (cursor,) = await _admin_rows(
        world.db, "SELECT last_time_ms FROM sign_in_import_cursor WHERE realm = $1", REALM
    )
    assert cursor["last_time_ms"] == NOW_MS - 500
    # The first run read the last day; the second began at the cursor.
    assert reader.asked_since[0] == NOW_MS - 24 * 3600 * 1000
    assert reader.asked_since[-1] == NOW_MS - 500
    # Each new row is announced for the open log screens (outbox, rule 5b/5c).
    announced = await _admin_rows(
        world.db,
        "SELECT count(*) AS n FROM outbox_events WHERE event_type = $1"
        " AND tenant_id = ANY($2::uuid[])",
        "identity_access.sign_in.recorded",
        [a.tenant, b.tenant],
    )
    assert announced[0]["n"] == 2
