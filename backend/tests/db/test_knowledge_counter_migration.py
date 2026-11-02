"""Migration 0046: articles move to their own counter, keep their IDs, and the move reverses.

Before 0046, articles counted on the prefix counter ("KB"). After it, `KB_ARTICLE` starts at the
highest number already handed out, so the next article continues the numbering (D-120 (3)).
"""

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db


@pytest.fixture
def at_0041(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A throwaway database migrated to just before 0046."""
    database = db_testing.create(db_config, migrate_to="0041")
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


async def _tenant(conn: asyncpg.Connection, articles: int) -> uuid.UUID:
    """A tenant with `articles` articles KB-1..KB-n on the old prefix counter."""
    tenant = uuid.uuid4()
    await conn.execute(
        "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Kb', $2)", tenant, f"t-{tenant.hex[:12]}"
    )
    if articles == 0:
        return tenant
    owner = uuid.uuid4()
    await conn.execute(
        "INSERT INTO users (id, tenant_id, email, display_name, first_name, user_type)"
        " VALUES ($1, $2, $3, 'Owner', 'Owner', 'technician')",
        owner,
        tenant,
        f"o-{owner.hex[:8]}@example.test",
    )
    topic = uuid.uuid4()
    await conn.execute(
        "INSERT INTO kb_topics (id, tenant_id, names, depth) VALUES ($1, $2, $3::jsonb, 1)",
        topic,
        tenant,
        '{"en": "Email"}',
    )
    await conn.execute(
        "INSERT INTO kb_types (tenant_id, code, review_months, builtin)"
        " VALUES ($1, 'faq', 12, true)",
        tenant,
    )
    for number in range(1, articles + 1):
        await conn.execute(
            "INSERT INTO kb_articles (id, tenant_id, display_id, topic_id, type_code, owner_id)"
            " VALUES ($1, $2, $3, $4, 'faq', $5)",
            uuid.uuid4(),
            tenant,
            f"KB-{number}",
            topic,
            owner,
        )
    await conn.execute(
        "INSERT INTO display_id_sequences (tenant_id, prefix, last_value) VALUES ($1, 'KB', $2)",
        tenant,
        articles,
    )
    return tenant


async def _seed(url: str) -> tuple[uuid.UUID, uuid.UUID]:
    conn = await asyncpg.connect(url)
    try:
        return await _tenant(conn, 3), await _tenant(conn, 0)
    finally:
        await conn.close()


async def _state(url: str, tenant: uuid.UUID) -> tuple[dict[str, int], list[str]]:
    conn = await asyncpg.connect(url)
    try:
        counters = await conn.fetch(
            "SELECT prefix, last_value FROM display_id_sequences WHERE tenant_id = $1", tenant
        )
        ids = await conn.fetch(
            "SELECT display_id FROM kb_articles WHERE tenant_id = $1 ORDER BY display_id", tenant
        )
    finally:
        await conn.close()
    return {r["prefix"]: r["last_value"] for r in counters}, [r["display_id"] for r in ids]


def test_0046_articles_keep_their_ids_and_the_counter_continues(
    at_0041: db_testing.ThrowawayDatabase,
) -> None:
    with_articles, empty = asyncio.run(_seed(at_0041.admin_url))
    db_testing.migrate(at_0041.migrator_url, "0046")

    counters, ids = asyncio.run(_state(at_0041.admin_url, with_articles))
    assert ids == ["KB-1", "KB-2", "KB-3"]  # unchanged
    assert counters["KB_ARTICLE"] == 3  # the next article is number 4
    assert asyncio.run(_state(at_0041.admin_url, empty)) == ({}, [])  # nothing to carry over

    # Down again: the prefix counter takes over, so no number is ever handed out twice.
    db_testing.downgrade(at_0041.migrator_url, "0041")
    counters, ids = asyncio.run(_state(at_0041.admin_url, with_articles))
    assert counters == {"KB": 3}
    assert ids == ["KB-1", "KB-2", "KB-3"]


def test_0048_adds_record_links_and_copied_from_and_reverses(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0048")
    try:

        async def columns(table: str) -> set[str]:
            conn = await asyncpg.connect(database.admin_url)
            try:
                rows = await conn.fetch(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
                    table,
                )
            finally:
                await conn.close()
            return {r["column_name"] for r in rows}

        assert {"article_id", "record_type", "record_id", "source"} <= asyncio.run(
            columns("kb_record_links")
        )
        assert "copied_from" in asyncio.run(columns("files"))
        db_testing.downgrade(database.migrator_url, "0046")
        assert asyncio.run(columns("kb_record_links")) == set()
        assert "copied_from" not in asyncio.run(columns("files"))
    finally:
        db_testing.destroy(db_config, database)
