"""The one-off showcase dates repair (QA 2026-11-09, INC-62): certain repairs only, audited once."""

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import asyncpg
import pytest

from app.shared.ids import id_created_at
from conftest import make_settings
from tests.db.test_showcase_seed import FakeKeycloak, _audit_chain, _by_hand, _run
from tooling import db_testing
from tooling import repair_showcase_dates as repair
from tooling import showcase_seed as seed

pytestmark = pytest.mark.db


async def _sql(url: str, query: str, *args: Any) -> list[asyncpg.Record]:  # noqa: ANN401 - binds
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            return list(await conn.fetch(query, *args))
    finally:
        await conn.close()


async def _times(url: str, record_id: str) -> dict[str, Any]:
    record = uuid.UUID(record_id)
    (row,) = await _sql(url, "SELECT created_at, updated_at FROM work_items WHERE id = $1", record)
    history = await _sql(
        url,
        "SELECT id, change_id, occurred_at FROM field_changes"
        " WHERE record_type = 'work_item' AND record_id = $1",
        record,
    )
    return {"row": row, "history": history, "born": id_created_at(record)}


async def _repairs(url: str) -> int:
    rows = await _sql(
        url, "SELECT count(*) AS n FROM audit_entries WHERE action = $1", repair.ACTION
    )
    return int(rows[0]["n"])


def test_puts_back_what_the_old_step_moved_and_only_what_is_certain(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config)
    try:
        keycloak = FakeKeycloak()
        asyncio.run(_run(database, keycloak))
        url = database.migrator_url
        moved = asyncio.run(_by_hand(database))  # INC-62's case
        odd = asyncio.run(_by_hand(database))  # moved, then changed some other way
        # The old step 5, on records it never made (what #288 stops): the same SQL, these ids.
        assert asyncio.run(seed.backdate(url, [uuid.UUID(moved), uuid.UUID(odd)])) == 2
        asyncio.run(
            _sql(
                url,
                "UPDATE work_items SET created_at = created_at + interval '1 hour' WHERE id = $1",
                uuid.UUID(odd),
            )
        )
        before = asyncio.run(_times(url, moved))
        assert before["row"]["created_at"] < before["born"] - timedelta(days=1)

        settings = make_settings(database_url=database.app_url, migration_database_url=url)
        plans = {p.record_id: p for p in asyncio.run(repair.run(settings, write=False))}
        # Only the two hand-made ones: the seed's own (backdated on purpose) are never listed.
        assert set(plans) == {uuid.UUID(moved), uuid.UUID(odd)}
        assert plans[uuid.UUID(moved)].skip is None
        assert "not where the old step put records" in (plans[uuid.UUID(odd)].skip or "")
        assert asyncio.run(_times(url, moved)) == before  # the dry run writes nothing
        assert asyncio.run(_repairs(url)) == 0

        done = {p.record_id: p for p in asyncio.run(repair.run(settings, write=True))}
        assert done[uuid.UUID(odd)].skip is not None  # left as it is, listed for Haider
        after = asyncio.run(_times(url, moved))
        assert after["row"]["created_at"] == after["born"]
        assert abs(after["row"]["updated_at"] - after["born"]) < timedelta(seconds=5)
        assert after["history"], "the edit wrote history"
        for row in after["history"]:
            assert abs(row["occurred_at"] - id_created_at(row["id"])) <= repair.TOLERANCE
            assert abs(row["occurred_at"] - id_created_at(row["change_id"])) <= repair.TOLERANCE
        assert asyncio.run(_repairs(url)) == 1  # one sealed entry for the one repair
        (entry,) = asyncio.run(
            _sql(
                url,
                "SELECT object_id, details FROM audit_entries WHERE action = $1",
                repair.ACTION,
            )
        )
        assert entry["object_id"] == moved
        assert asyncio.run(_audit_chain(database.app_url)) == "passed"

        again = asyncio.run(repair.run(settings, write=True))
        assert [p.record_id for p in again] == [uuid.UUID(odd)]  # still listed, still skipped
        assert asyncio.run(_repairs(url)) == 1  # nothing more written
        assert asyncio.run(_times(url, moved)) == after
    finally:
        db_testing.destroy(db_config, database)


def test_refuses_every_tenant_but_showcase() -> None:
    settings = make_settings()
    for slug in ("demo", "other", "showcase2", ""):
        assert repair.refuse(slug, settings) is not None
    assert repair.refuse("showcase", settings) is None
