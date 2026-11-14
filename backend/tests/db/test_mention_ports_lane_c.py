"""Lane C's mentions ports on real Postgres (ADR-052 S2, D-171 a): knowledge and announcements.

Tech A is being erased. Their name appears in other people's knowledge text (a published
version's title, body, keywords and internal note; tech B's feedback; a withdrawal reason; a
topic's name) and in an announcement. The report lists every place (never the text); a
redaction turns the words into the marker:
- a published (frozen) version changes only through 0168's `kb_redact_version`;
- history names the field only (reason `erasure_redaction`) and the saved events are raised;
- search no longer finds the article by the name;
- a value that would no longer fit is refused and nothing changes.
The passage follows the article screen's rights: an internal note never for a reader; a trashed
article's version only for someone who may erase people.
"""

import json
import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, Org, World
from tests.db.test_person_erasure_api import _name, _request
from tests.db.test_person_erasure_mentions import _build, _get, _mentions

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the incidents fixture, re-used

MARKER = "erased_on_request"


async def _seed(world: World, org: Org, name: str) -> dict[str, uuid.UUID]:
    """Knowledge and an announcement that name `name` (as the admin wrote them)."""
    code = f"t{uuid.uuid4().hex[:8]}"
    ids = {
        k: uuid.uuid4()
        for k in (
            "topic",
            "article",
            "version",
            "long",
            "long_article",
            "vote",
            "note",
            "trashed_article",
            "trashed",
        )
    }
    await world.sql(
        "INSERT INTO kb_types (tenant_id, code, review_months) VALUES ($1, $2, 12)",
        org.tenant,
        code,
    )
    await world.sql(
        "INSERT INTO kb_topics (id, tenant_id, depth, names, owner_id, tech_all)"
        " VALUES ($1, $2, 1, $3::jsonb, $4, true)",
        ids["topic"],
        org.tenant,
        json.dumps({"en": f"{name} desk"}),
        org.admin,
    )
    for article in ("article", "long_article"):
        await world.sql(
            "INSERT INTO kb_articles (id, tenant_id, display_id, topic_id, type_code, owner_id,"
            " withdrawn_reason) VALUES ($1, $2, $3, $4, $5, $6, $7)",
            ids[article],
            org.tenant,
            f"KB-{code}-{article[:1]}",
            ids["topic"],
            code,
            org.admin,
            f"Asked by {name}" if article == "article" else None,
        )
    await world.sql(
        "INSERT INTO kb_article_versions (id, tenant_id, article_id, language, number, title,"
        " body_html, keywords, internal_note, status, published_at)"
        " VALUES ($1, $2, $3, 'en', 1, $4, $5, $6, $7, 'published', now())",
        ids["version"],
        org.tenant,
        ids["article"],
        f"VPN help from {name}",
        f"<p>Call <strong>{name}</strong> for the VPN.</p>",
        [name.lower(), "vpn"],
        f"Checked with {name}",
    )
    # A title that the marker would make longer than 250 characters (when the name is shorter).
    await world.sql(
        "INSERT INTO kb_article_versions (id, tenant_id, article_id, language, number, title,"
        " body_html, status, published_at) VALUES ($1, $2, $3, 'en', 1, $4, '<p>x</p>',"
        " 'published', now())",
        ids["long"],
        org.tenant,
        ids["long_article"],
        "x" * (250 - len(name) - 1) + " " + name,
    )
    # A trashed article whose published version names them (#514's trashed-row rule).
    await world.sql(
        "INSERT INTO kb_articles (id, tenant_id, display_id, topic_id, type_code, owner_id,"
        " deleted_at) VALUES ($1, $2, $3, $4, $5, $6, now())",
        ids["trashed_article"],
        org.tenant,
        f"KB-{code}-t",
        ids["topic"],
        code,
        org.admin,
    )
    await world.sql(
        "INSERT INTO kb_article_versions (id, tenant_id, article_id, language, number, title,"
        " body_html, status, published_at) VALUES ($1, $2, $3, 'en', 1, $4, '<p>x</p>',"
        " 'published', now())",
        ids["trashed"],
        org.tenant,
        ids["trashed_article"],
        f"Old notes by {name}",
    )
    await world.sql(
        "INSERT INTO kb_votes (id, tenant_id, article_id, version_id, person_id, helpful, comment)"
        " VALUES ($1, $2, $3, $4, $5, false, $6)",
        ids["vote"],
        org.tenant,
        ids["article"],
        ids["version"],
        org.tech_b,
        f"{name} gave other advice",
    )
    await world.sql(
        "INSERT INTO announcements (id, tenant_id, display_id, title, body, owner_id)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        ids["note"],
        org.tenant,
        f"ANN-{code}",
        f"{name} is away",
        f"Ask the desk while {name} is away.",
        org.admin,
    )
    return ids


def _ours(page: dict[str, Any], records: set[str]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """The name mentions of the seeded records (not the long title's: that one is refused)."""
    return {
        (m["module_key"], m["record_type"], m["field"]): m
        for m in page["items"]
        if m["record_id"] in records and m["match_kind"] == "name"
    }


async def _redact(world: World, org: Org, erasure: dict[str, Any], ids: list[str]) -> Any:  # noqa: ANN401 - httpx response
    current = await _get(world, org, erasure)
    return await world.call(
        "POST",
        f"/erasures/{erasure['id']}/mentions/redact",
        org,
        org.admin,
        json={"mention_ids": ids},
        headers={"If-Match": f'"{current["version"]}"'},
    )


async def _trashed_version(
    world: World, a: Org, erasure: dict[str, Any], version: uuid.UUID, name: str
) -> None:
    """A trashed article's version: found, read and redacted by someone who may erase people
    (the admin), never shown to a technician without that right (lane B's #516 review)."""
    base = f"/erasures/{erasure['id']}/mentions"
    trashed = next(
        m
        for m in (await _mentions(world, a, erasure))["items"]
        if m["record_id"] == str(version) and m["field"] == "title"
    )
    by_admin = await world.call("GET", f"{base}/{trashed['id']}/passage", a, a.admin)
    assert by_admin.status_code == 200, by_admin.text
    assert name in by_admin.text
    by_tech = await world.call("GET", f"{base}/{trashed['id']}/passage", a, a.tech_c)
    assert by_tech.status_code in (403, 404), by_tech.text
    assert name not in by_tech.text
    trashed_done = await _redact(world, a, erasure, [trashed["id"]])
    assert trashed_done.status_code == 200, trashed_done.text
    (gone,) = await world.sql(
        "SELECT title FROM kb_article_versions WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        version,
    )
    assert gone["title"] == f"Old notes by {MARKER}"


async def test_knowledge_and_announcements_are_found_redacted_and_searched_no_more(
    world: World,
) -> None:
    a = world.a
    name = await _name(world, a, a.tech_a)
    ids = await _seed(world, a, name)
    asked = await _request(world, a, a.admin, a.tech_a, successor_id=str(a.lead))
    assert asked.status_code == 201, asked.text
    erasure = dict(asked.json())
    await _build(world, a)
    seeded = {str(ids[k]) for k in ("version", "vote", "article", "topic", "note")}
    places = _ours(await _mentions(world, a, erasure), seeded)
    expected = {
        ("knowledge", "kb_article_version", field)
        for field in ("title", "body_html", "keywords", "internal_note")
    } | {
        ("knowledge", "kb_vote", "comment"),
        ("knowledge", "kb_article", "withdrawn_reason"),
        ("knowledge", "kb_topic", "names"),
        ("announcements", "announcement", "title"),
        ("announcements", "announcement", "body"),
    }
    assert expected <= set(places)
    assert name not in json.dumps(await _mentions(world, a, erasure))  # places, never text

    # The internal note's passage: the admin (an editor) reads it; a reader never does.
    note = places[("knowledge", "kb_article_version", "internal_note")]
    base = f"/erasures/{erasure['id']}/mentions"
    shown = await world.call("GET", f"{base}/{note['id']}/passage", a, a.admin)
    assert shown.status_code == 200, shown.text
    assert name in shown.text

    # Too long: the marker would overflow the 250-character title. Refused, nothing changes.
    long_title = next(
        m
        for m in (await _mentions(world, a, erasure))["items"]
        if m["record_type"] == "kb_article_version"
        and m["record_id"] == str(ids["long"])
        and m["field"] == "title"
        and m["match_kind"] == "name"
    )
    if len(name) < len(MARKER):
        refused = await _redact(world, a, erasure, [long_title["id"]])
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "erasure_redaction_too_long"

    await _trashed_version(world, a, erasure, ids["trashed"], name)

    before_events = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1"
        " AND event_type IN ('knowledge.article.saved', 'knowledge.topic.saved',"
        " 'announcements.announcement.updated')",
        a.tenant,
    )
    done = await _redact(world, a, erasure, [m["id"] for m in places.values()])
    assert done.status_code == 200, done.text

    (version,) = await world.sql(
        "SELECT title, body_html, keywords, internal_note, status FROM kb_article_versions"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        ids["version"],
    )
    assert version["status"] == "published"  # still the published version, redacted in place
    assert version["title"] == f"VPN help from {MARKER}"
    assert version["body_html"] == f"<p>Call <strong>{MARKER}</strong> for the VPN.</p>"
    assert list(version["keywords"]) == [MARKER, "vpn"]
    assert version["internal_note"] == f"Checked with {MARKER}"
    others = await world.sql(
        "SELECT (SELECT comment FROM kb_votes WHERE tenant_id = $1 AND id = $2) AS comment,"
        " (SELECT withdrawn_reason FROM kb_articles WHERE tenant_id = $1 AND id = $3) AS reason,"
        " (SELECT names->>'en' FROM kb_topics WHERE tenant_id = $1 AND id = $4) AS topic,"
        " (SELECT title || ' / ' || body FROM announcements WHERE tenant_id = $1 AND id = $5)"
        " AS announcement",
        a.tenant,
        ids["vote"],
        ids["article"],
        ids["topic"],
        ids["note"],
    )
    assert name not in json.dumps(dict(others[0]))
    assert MARKER in others[0]["announcement"]
    # History names the field only, with the reason; the saved events let screens follow.
    history = await world.sql(
        "SELECT field, old_value, new_value FROM field_changes WHERE tenant_id = $1"
        " AND record_id = $2 AND reason = 'erasure_redaction'",
        a.tenant,
        ids["article"],
    )
    assert {r["field"] for r in history} >= {"title", "body_html", "keywords", "withdrawn_reason"}
    # No value either way: JSON null as written, or SQL NULL where history_redact_field also
    # blanked it (a mention whose record is the article itself).
    assert all(
        r["old_value"] in (None, "null") and r["new_value"] in (None, "null") for r in history
    )
    after_events = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1"
        " AND event_type IN ('knowledge.article.saved', 'knowledge.topic.saved',"
        " 'announcements.announcement.updated')",
        a.tenant,
    )
    assert after_events[0]["n"] > before_events[0]["n"]
    # Search reads the computed column: the name finds the article no more (the coordinator).
    found = await world.call(
        "GET", "/knowledge/articles", a, a.admin, params={"q": name.split()[0]}, headers=CONSOLE
    )
    assert found.status_code == 200, found.text
    assert str(ids["article"]) not in found.text
    # Twice is the same: already redacted, nothing more changes.
    again = await _redact(world, a, erasure, [m["id"] for m in places.values()])
    assert again.status_code == 200, again.text
    (same,) = await world.sql(
        "SELECT title FROM kb_article_versions WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        ids["version"],
    )
    assert same["title"] == f"VPN help from {MARKER}"
