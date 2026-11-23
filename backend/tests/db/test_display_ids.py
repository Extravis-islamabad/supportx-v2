import asyncio
import uuid

import pytest

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.shared.db.display_ids import format_display_id, next_display_id

pytestmark = pytest.mark.db


async def take(db: Database, tenant: uuid.UUID, prefix: str) -> str:
    async with db.tenant_session(TenantContext(tenant)) as session:
        return await next_display_id(session, prefix)


async def test_sequence_starts_at_one_and_is_per_tenant_and_prefix(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = tenant_pair
    assert [await take(app_db, a, "INC") for _ in range(3)] == ["INC-1", "INC-2", "INC-3"]
    assert await take(app_db, a, "SR") == "SR-1"
    assert await take(app_db, b, "INC") == "INC-1"


async def test_fifty_parallel_calls_get_fifty_unique_sequential_ids(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant, _ = tenant_pair
    ids = await asyncio.gather(*(take(app_db, tenant, "CHG") for _ in range(50)))
    assert len(set(ids)) == 50
    assert sorted(int(i.split("-")[1]) for i in ids) == list(range(1, 51))


async def test_rollback_returns_the_number(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant, _ = tenant_pair
    assert await take(app_db, tenant, "PRB") == "PRB-1"

    async def take_then_fail() -> None:
        async with app_db.tenant_session(TenantContext(tenant)) as session:
            assert await next_display_id(session, "PRB") == "PRB-2"
            msg = "record creation failed"
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="record creation failed"):
        await take_then_fail()
    assert await take(app_db, tenant, "PRB") == "PRB-2"


async def test_no_tenant_cannot_take_numbers(app_db: Database) -> None:
    async with app_db.platform_session() as session:
        with pytest.raises(TypeError, match="tenant session"):
            await next_display_id(session, "INC")


@pytest.mark.parametrize("prefix", ["", "I", "inc", "INC1", "TOOLONGX", "IN-C"])
async def test_prefix_is_validated(prefix: str) -> None:
    with pytest.raises(ValueError, match="2-6 capital letters"):
        await next_display_id(None, prefix)  # type: ignore[arg-type]  # rejected before use


def test_format() -> None:
    assert format_display_id("INC", 1042) == "INC-1042"


async def test_a_block_is_reserved_at_once_and_its_unused_rest_goes_back(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """One upsert for a block of numbers (an asset import's batch, WP-049b); handing back the
    unused rest leaves no gap, and a misuse (the counter moved on) changes nothing."""
    from app.shared.db.display_ids import (  # noqa: PLC0415 - the functions under test
        next_display_number,
        reserve_display_numbers,
        return_display_numbers,
    )

    tenant, other = tenant_pair
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        first = await reserve_display_numbers(session, "AT_BLOCK", 10)
        assert first == 1  # a new counter: 1..10
        await return_display_numbers(session, "AT_BLOCK", last_used=3, last_reserved=10)
        assert await next_display_number(session, "AT_BLOCK") == 4  # no gap
        again = await reserve_display_numbers(session, "AT_BLOCK", 5)
        assert again == 5  # 5..9
        await return_display_numbers(session, "AT_BLOCK", last_used=6, last_reserved=8)
        assert await next_display_number(session, "AT_BLOCK") == 10  # 9 was the last: unchanged
        await return_display_numbers(session, "AT_BLOCK", last_used=0, last_reserved=10)
        assert await next_display_number(session, "AT_BLOCK") == 11  # never back to 0
        with pytest.raises(ValueError, match="at least 1"):
            await reserve_display_numbers(session, "AT_BLOCK", 0)
    async with app_db.tenant_session(TenantContext(other)) as session:
        assert await reserve_display_numbers(session, "AT_BLOCK", 2) == 1  # per tenant
