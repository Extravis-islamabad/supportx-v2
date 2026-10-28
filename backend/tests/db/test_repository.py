import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.database import Database
from app.core.errors import BadRequest, Conflict, NotFound
from app.core.tenancy import TenantContext
from app.shared.clock import FrozenClock
from app.shared.db.repository import decode_cursor, encode_cursor
from tests.db.probe import ProbeItem, ProbeRepository

pytestmark = pytest.mark.db

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


async def test_add_fills_managed_columns(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant, _ = tenant_pair
    user = uuid.uuid4()
    async with app_db.tenant_session(TenantContext(tenant, user)) as session:
        item = await ProbeRepository(session, clock=FrozenClock(T0)).add(ProbeItem(title="first"))
    assert item.id.version == 7
    assert item.tenant_id == tenant
    assert (item.created_at, item.updated_at) == (T0, T0)
    assert (item.created_by, item.updated_by) == (user, user)
    assert item.version == 1
    assert item.deleted_at is None


async def test_get_hides_deleted_and_other_tenants(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = tenant_pair
    async with app_db.tenant_session(TenantContext(a)) as session:
        item = await ProbeRepository(session).add(ProbeItem(title="mine"))
    async with app_db.tenant_session(TenantContext(b)) as session:
        with pytest.raises(NotFound):
            await ProbeRepository(session).get(item.id)
    async with app_db.tenant_session(TenantContext(a)) as session:
        repo = ProbeRepository(session)
        assert (await repo.get(item.id)).title == "mine"
        await repo.soft_delete(item.id, expected_version=1)
        with pytest.raises(NotFound):
            await repo.get(item.id)
        assert (await repo.get(item.id, include_deleted=True)).deleted_at is not None


async def test_update_bumps_version_and_audit_columns(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant, _ = tenant_pair
    editor = uuid.uuid4()
    clock = FrozenClock(T0)
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        item = await ProbeRepository(session, clock=clock).add(ProbeItem(title="v1"))
    clock.advance(timedelta(minutes=5))
    async with app_db.tenant_session(TenantContext(tenant, editor)) as session:
        updated = await ProbeRepository(session, clock=clock).update(
            item.id, expected_version=1, changes={"title": "v2"}
        )
    assert (updated.title, updated.version) == ("v2", 2)
    assert updated.updated_at == T0 + timedelta(minutes=5)
    assert updated.updated_by == editor
    assert updated.created_at == T0


async def test_stale_version_raises_conflict_with_current_version(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant, _ = tenant_pair
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        item = await ProbeRepository(session).add(ProbeItem(title="shared"))
    # Two technicians read version 1; the first save wins.
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        await ProbeRepository(session).update(
            item.id, expected_version=1, changes={"title": "first"}
        )
    with pytest.raises(Conflict) as raised:
        async with app_db.tenant_session(TenantContext(tenant)) as session:
            await ProbeRepository(session).update(
                item.id, expected_version=1, changes={"title": "second"}
            )
    assert raised.value.instance_code == "version_conflict"
    params = raised.value.params
    assert (params["expected_version"], params["current_version"]) == (1, 2)
    # Who saved it since, and when (QA WP-029 BUG-05).
    assert params["changed_at"] is not None
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        assert (await ProbeRepository(session).get(item.id)).title == "first"


async def test_update_of_missing_or_foreign_record_is_not_found(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = tenant_pair
    async with app_db.tenant_session(TenantContext(a)) as session:
        item = await ProbeRepository(session).add(ProbeItem(title="a"))
    async with app_db.tenant_session(TenantContext(b)) as session:
        repo = ProbeRepository(session)
        with pytest.raises(NotFound):
            await repo.update(item.id, expected_version=1, changes={"title": "b"})
        with pytest.raises(NotFound):
            await repo.update(uuid.uuid4(), expected_version=1, changes={"title": "b"})


async def test_managed_columns_cannot_be_changed(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant, other = tenant_pair
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        repo = ProbeRepository(session)
        item = await repo.add(ProbeItem(title="x"))
        with pytest.raises(ValueError, match="tenant_id"):
            await repo.update(item.id, expected_version=1, changes={"tenant_id": other})


async def test_list_pages_with_a_stable_cursor(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant, other = tenant_pair
    async with app_db.tenant_session(TenantContext(other)) as session:
        await ProbeRepository(session).add(ProbeItem(title="other tenant"))
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        repo = ProbeRepository(session)
        created = [await repo.add(ProbeItem(title=f"item {i}")) for i in range(5)]
        await repo.soft_delete(created[2].id, expected_version=1)
        first = await repo.list(limit=2)
        second = await repo.list(limit=2, cursor=first.next_cursor)
        everything = await repo.list(limit=500)
    assert [item.title for item in first.items] == ["item 0", "item 1"]
    assert first.next_cursor is not None
    # Deleted item 2 and the other tenant's row are skipped; the second page is the last.
    assert [item.title for item in second.items] == ["item 3", "item 4"]
    assert second.next_cursor is None
    assert len(everything.items) == 4  # limit is capped, not an error


def test_cursor_round_trip_and_rejects_garbage() -> None:
    value = uuid.uuid4()
    assert decode_cursor(encode_cursor(value)) == value
    with pytest.raises(BadRequest):
        decode_cursor("not-a-cursor!")


def test_repository_requires_a_tenant_session() -> None:
    class FakeSession:
        info: dict[str, object] = {}  # noqa: RUF012 - stand-in for AsyncSession.info

    with pytest.raises(TypeError, match="tenant session"):
        ProbeRepository(FakeSession())  # type: ignore[arg-type]  # deliberately wrong type
