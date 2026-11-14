"""Migration 0168: a published knowledge version's passage redacted, and nothing else (ADR-052).

`kb_redact_version` changes a frozen (published) version only for a redacted mention of an open
erasure, only the mention's own field, and only into the old text with the marker in place
(lane B's #511 review). The freeze still refuses the app role, even with the flag set, and the
migrator without it: the flag names one row and is cleared at once (the coordinator, lane B).
"""

import uuid
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import Org, World
from tests.db.test_person_erasure_api import _request

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the incidents fixture, re-used

MARKER = "erased_on_request"
CALL = text("SELECT kb_redact_version(:m, :v, CAST(:k AS varchar[]))")


async def _erasure(world: World, org: Org, person: uuid.UUID) -> uuid.UUID:
    """A requested erasure of `person` (one open erasure per person: each test its own)."""
    successor = org.lead if person != org.lead else org.tech_a
    asked = await _request(world, org, org.admin, person, successor_id=str(successor))
    assert asked.status_code == 201, asked.text
    return uuid.UUID(asked.json()["id"])


async def _published(
    world: World, org: Org, title: str, body: str, keywords: list[str]
) -> uuid.UUID:
    """A published version as the knowledge base keeps it (seeded as the admin)."""
    code, topic, article, version = (
        f"t{uuid.uuid4().hex[:8]}",
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    await world.sql(
        "INSERT INTO kb_types (tenant_id, code, review_months) VALUES ($1, $2, 12)",
        org.tenant,
        code,
    )
    await world.sql(
        "INSERT INTO kb_topics (id, tenant_id, depth, names, owner_id) VALUES ($1, $2, 1,"
        ' \'{"en": "T"}\', $3)',
        topic,
        org.tenant,
        org.admin,
    )
    await world.sql(
        "INSERT INTO kb_articles (id, tenant_id, display_id, topic_id, type_code, owner_id)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        article,
        org.tenant,
        f"KB-{code}",
        topic,
        code,
        org.admin,
    )
    await world.sql(
        "INSERT INTO kb_article_versions (id, tenant_id, article_id, language, number, title,"
        " body_html, keywords, status) VALUES ($1, $2, $3, 'en', 1, $4, $5, $6, 'published')",
        version,
        org.tenant,
        article,
        title,
        body,
        keywords,
    )
    return version


async def _mention(
    world: World,
    org: Org,
    erasure_id: uuid.UUID,
    version: uuid.UUID,
    field: str,
    *,
    redacted_by: uuid.UUID | None = None,
    kind: str = "name",
) -> uuid.UUID:
    """A redacted mention row (the app role could write one: it has INSERT and UPDATE)."""
    mention = uuid.uuid4()
    by = redacted_by if redacted_by is not None else org.admin
    await world.sql(
        "INSERT INTO person_erasure_mentions (tenant_id, id, erasure_id, module_key, record_type,"
        " record_id, field, match_kind, occurrences, state, redacted_by, redacted_at)"
        " VALUES ($1, $2, $3, 'knowledge', 'kb_article_version', $4, $5, $7, 1, 'redacted',"
        " $6, now())",
        org.tenant,
        mention,
        erasure_id,
        version,
        field,
        by,
        kind,
    )
    return mention


async def _call(
    world: World, org: Org, mention: uuid.UUID, value: str | None, keywords: list[str] | None = None
) -> Any:  # noqa: ANN401 - the function's boolean
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        return await session.scalar(CALL, {"m": mention, "v": value, "k": keywords})


async def _row(world: World, org: Org, version: uuid.UUID) -> asyncpg.Record:
    (row,) = await world.sql(
        "SELECT title, body_html, keywords FROM kb_article_versions"
        " WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        version,
    )
    return row


async def test_the_old_text_with_the_marker_in_place_passes_and_nothing_else(world: World) -> None:
    a = world.a
    erasure = await _erasure(world, a, a.tech_a)
    version = await _published(
        world, a, "Ask Sam Lee", "<p>Call Sam Lee today</p>", ["sam lee", "vpn"]
    )

    title = await _mention(world, a, erasure, version, "title")
    for bad in (
        "Something else entirely",  # arbitrary text
        f"Ask {MARKER}!",  # a character added outside the marker
        f"ask {MARKER}",  # a character changed outside the marker
        "Ask Sam",  # no marker: a deletion, not a redaction
    ):
        with pytest.raises(DBAPIError):
            await _call(world, a, title, bad)
    assert (await _row(world, a, version))["title"] == "Ask Sam Lee"
    assert await _call(world, a, title, f"Ask {MARKER}") is True
    assert (await _row(world, a, version))["title"] == f"Ask {MARKER}"
    assert await _call(world, a, title, f"Ask {MARKER}") is False  # nothing left to change

    body = await _mention(world, a, erasure, version, "body_html")
    assert await _call(world, a, body, f"<p>Call {MARKER} today</p>") is True
    keywords = await _mention(world, a, erasure, version, "keywords")
    with pytest.raises(DBAPIError):
        await _call(world, a, keywords, None, [MARKER])  # one value per keyword
    with pytest.raises(DBAPIError):
        await _call(world, a, keywords, None, [MARKER, "vpn2"])  # vpn changed
    assert await _call(world, a, keywords, None, [MARKER, "vpn"]) is True
    assert list((await _row(world, a, version))["keywords"]) == [MARKER, "vpn"]


async def test_the_function_is_bound_to_an_open_redacted_mention_of_its_own_field(
    world: World,
) -> None:
    a, b = world.a, world.b
    erasure = await _erasure(world, a, a.tech_b)
    version = await _published(world, a, "Ask Sam Lee", "<p>Sam Lee</p>", [])
    # A field the function never touches: nothing.
    note = await _mention(world, a, erasure, version, "change_note")
    assert await _call(world, a, note, f"Ask {MARKER}") is False
    # Not redacted by anyone: nothing.
    unsigned = await _mention(world, a, erasure, version, "title", kind="email")
    await world.sql(
        "UPDATE person_erasure_mentions SET redacted_by = NULL, redacted_at = NULL"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        unsigned,
    )
    assert await _call(world, a, unsigned, f"Ask {MARKER}") is False
    # Another tenant's session never reaches this tenant's mention.
    signed = await _mention(world, a, erasure, version, "title")
    assert await _call(world, b, signed, f"Ask {MARKER}") is False
    # A closed erasure: nothing, the row untouched.
    await world.sql(
        "UPDATE person_erasures SET state = 'rejected' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        erasure,
    )
    assert await _call(world, a, signed, f"Ask {MARKER}") is False
    assert (await _row(world, a, version))["title"] == "Ask Sam Lee"


async def test_the_freeze_still_refuses_the_app_and_the_migrator_without_the_function(
    world: World,
) -> None:
    a = world.a
    erasure = await _erasure(world, a, a.tech_c)
    version = await _published(world, a, "Ask Sam Lee", "<p>x</p>", [])
    # The app role, even with the flag naming the row.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await session.execute(
            text("SELECT set_config('supportx.kb_redaction', :v, true)"), {"v": str(version)}
        )
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE kb_article_versions SET title = 'changed' WHERE id = :v"),
                {"v": version},
            )
    # The migrator (every definer's owner): after the function, in the same transaction, the
    # flag is gone, so another definer, or the migrator itself, is refused on that version.
    mention = await _mention(world, a, erasure, version, "title")
    conn = await asyncpg.connect(world.db.migrator_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(a.tenant))
            assert await conn.fetchval(
                "SELECT kb_redact_version($1, $2, NULL)", mention, f"Ask {MARKER}"
            )
            assert await conn.fetchval("SELECT current_setting('supportx.kb_redaction', true)") in (
                "",
                None,
            )
            with pytest.raises(asyncpg.PostgresError):
                await conn.execute(
                    "UPDATE kb_article_versions SET title = 'changed' WHERE id = $1", version
                )
    finally:
        await conn.close()
    assert (await _row(world, a, version))["title"] == "Ask Sam Lee"  # the transaction rolled back
