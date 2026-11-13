"""The personal data access log and the key-wrap count (WP-057 S3b-1; 0163; lane B's conditions).

- The log is per tenant (RLS) and append-only: the app role can neither update nor delete it;
  rows leave only through `audit_purge_access()` (it computes its own cutoff, at least 365 days),
  for the tenant set in the transaction alone.
- Off by default; on, a view is written once per accessor, record and 15 minutes.
- `sx_kek_wraps()` gives counts per key-encryption key and nothing else, while the app role
  still cannot read another tenant's data keys.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from app.modules.audit.domain.catalogue import AuditActorType
from app.modules.audit.service import access_log
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
REPORT = "/audit/personal-data-access"


async def _switch_on(world: World, tenant: uuid.UUID) -> None:
    await world.sql(
        "INSERT INTO audit_settings (tenant_id, retention_days, read_window_minutes,"
        " refusal_threshold, refusal_window_minutes, read_categories, personal_data_log)"
        " VALUES ($1, 1095, 10, 10, 10, '[]'::jsonb, true)"
        " ON CONFLICT (tenant_id) DO UPDATE SET personal_data_log = true",
        tenant,
    )


async def _view(world: World, tenant: uuid.UUID, person: uuid.UUID, at: datetime) -> bool:
    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        return await access_log.record_access(
            session,
            accessor=access_log.Accessor(AuditActorType.PERSON, uuid.uuid4()),
            kind="view",
            purpose="person_profile",
            subject_person_id=person,
            fields=["email", "phone"],
            now=at,
        )


async def _count(world: World, tenant: uuid.UUID, person: uuid.UUID) -> int:
    rows = await world.sql(
        "SELECT count(*) AS n FROM personal_data_access WHERE tenant_id = $1"
        " AND subject_person_id = $2",
        tenant,
        person,
    )
    return int(rows[0]["n"])


async def test_off_by_default_and_one_view_per_15_minutes(world: World) -> None:
    person = uuid.uuid4()
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        assert not await access_log.log_enabled(session)  # never switched on
    await _switch_on(world, world.a.tenant)
    accessor = access_log.Accessor(AuditActorType.PERSON, world.a.admin)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        first = await access_log.record_access(
            session, accessor=accessor, kind="view", purpose="person_profile",
            subject_person_id=person, fields=["email"], now=NOW,
        )  # fmt: skip
        again = await access_log.record_access(
            session, accessor=accessor, kind="view", purpose="person_profile",
            subject_person_id=person, fields=["email"], now=NOW + timedelta(minutes=5),
        )  # fmt: skip
        later = await access_log.record_access(
            session, accessor=accessor, kind="view", purpose="person_profile",
            subject_person_id=person, fields=["email"], now=NOW + timedelta(minutes=20),
        )  # fmt: skip
        exported = await access_log.record_access(
            session, accessor=accessor, kind="export", purpose="people_export",
            subject_person_id=person, now=NOW + timedelta(minutes=21),
        )  # fmt: skip
    assert (first, again, later, exported) == (True, False, True, True)
    assert await _count(world, world.a.tenant, person) == 3


async def test_append_only_for_the_app_and_isolated_per_tenant(world: World) -> None:
    await _switch_on(world, world.a.tenant)
    mine = uuid.uuid4()
    assert await _view(world, world.a.tenant, mine, NOW)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        for statement in (
            "UPDATE personal_data_access SET purpose = 'x'",
            "DELETE FROM personal_data_access",
        ):
            with pytest.raises(DBAPIError):  # no UPDATE or DELETE right at all
                async with session.begin_nested():
                    await session.execute(text(statement))
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        seen = await session.scalar(
            text("SELECT count(*) FROM personal_data_access WHERE tenant_id = :a"),
            {"a": world.a.tenant},
        )
        assert seen == 0
        # B's purge never reaches A's rows: the tenant comes from the transaction.
        assert await session.scalar(text("SELECT audit_purge_access()")) == 0
    assert await _count(world, world.a.tenant, mine) == 1


async def test_the_purge_keeps_everything_younger_than_retention(world: World) -> None:
    """Lane B (#500): the app passes no cutoff; the function takes the tenant's retention (at
    least 365 days), so nothing younger than it can ever be purged."""
    await _switch_on(world, world.a.tenant)
    now = datetime.now(UTC)
    old, recent, young = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert await _view(world, world.a.tenant, old, now - timedelta(days=1200))  # past 1095
    assert await _view(world, world.a.tenant, recent, now - timedelta(days=400))
    assert await _view(world, world.a.tenant, young, now)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await access_log.purge(session) >= 1
        with pytest.raises(DBAPIError):  # no cutoff can be handed in
            async with session.begin_nested():
                await session.execute(
                    text("SELECT audit_purge_access(:b)"), {"b": now + timedelta(days=9999)}
                )
    assert await _count(world, world.a.tenant, old) == 0
    assert await _count(world, world.a.tenant, recent) == 1
    assert await _count(world, world.a.tenant, young) == 1
    # (audit_settings itself refuses a retention under 365 days: ck_audit_settings_retention_range.)


async def test_the_wrap_count_names_keys_and_counts_only(world: World) -> None:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        rows = (await session.execute(text("SELECT * FROM sx_kek_wraps()"))).mappings().all()
        assert all(set(row) == {"kek_id", "wraps"} for row in rows)
        # The function is the only way across tenants: the app still sees only its own keys.
        others = await session.scalar(
            text("SELECT count(*) FROM tenant_data_keys WHERE tenant_id <> :a"),
            {"a": world.a.tenant},
        )
        assert others == 0


async def test_a_removed_key_still_wrapping_data_keys_is_found(world: World) -> None:
    """The start-up check (ADR-050): a KEK missing from the ring that still wraps a data key."""
    from app.shared.fields.keycheck import RemovedKeysInUse, missing_keys  # noqa: PLC0415
    from app.shared.files.keyring import KeyRing  # noqa: PLC0415

    gone = "gone" + uuid.uuid4().hex[:8]
    await world.sql(
        "INSERT INTO tenant_data_keys (tenant_id, id, kek_id, wrapped) VALUES ($1, $2, $3, $4)",
        world.a.tenant,
        uuid.uuid4(),
        gone,
        b"\x00" * 60,
    )
    ring = KeyRing(keys={"kept": b"\x01" * 32}, active_id="kept")
    try:
        found = await missing_keys(world.app.state.db, ring)
        assert found.get(gone) == 1
        message = str(RemovedKeysInUse({gone: 1}))
        assert gone in message
        assert str(world.a.tenant) not in message  # key IDs and counts only, never a tenant
    finally:
        # The shared test database must not keep a key no ring has: later apps would not start.
        await world.sql("DELETE FROM tenant_data_keys WHERE kek_id = $1", gone)


async def test_a_profile_view_is_one_entry_and_the_report_is_itself_audited(world: World) -> None:
    """REQ-AUD-017 AC1 and AC2, through the API; lane B: the report needs its own right."""
    await _switch_on(world, world.a.tenant)
    seen = world.a.requester
    for _ in range(2):  # a refetch within 15 minutes is the same access
        opened = await world.call("GET", f"/users/{seen}", world.a, user=world.a.admin)
        assert opened.status_code == 200, opened.text
    report = await world.call(
        "GET",
        "/audit/personal-data-access",
        world.a,
        user=world.a.admin,
        params={"person": str(seen)},
    )
    assert report.status_code == 200, report.text
    items = [i for i in report.json()["items"] if i["purpose"] == "person_profile"]
    assert len(items) == 1
    (item,) = items
    assert (item["kind"], item["accessor_id"]) == ("view", str(world.a.admin))
    assert "email" in item["fields"]
    assert "value" not in item  # codes only
    audited = await world.sql(
        "SELECT object_id FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'audit.personal_data_access_viewed'",
        world.a.tenant,
    )
    assert str(seen) in {r["object_id"] for r in audited}
    # Without the right the log does not exist for you.
    refused = await world.call(
        "GET",
        "/audit/personal-data-access",
        world.a,
        user=world.a.tech_a,
        params={"person": str(seen)},
    )
    assert refused.status_code == 404
