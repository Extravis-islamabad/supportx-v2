"""Knowledge over HTTP, session 1 (WP-033, D-108). Test names cite parity file 08 (REQ-KB-*).

The incident world of test_incidents_api.py: org A has an admin (every permission), technicians
tech_a (group GA), tech_b (GB), tech_c (GA and GB), requesters, and org B for isolation. Session 1
has no approval flow yet, so a version is published here with direct SQL as a stand-in for the
session 2 approval.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.knowledge.domain.knowledge import add_months
from tests.db import test_incidents_api
from tests.db.test_incidents_api import CONSOLE, Org, World, field_codes, problem

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

TOPICS = "/knowledge/topics"
ARTICLES = "/knowledge/articles"
TABLES = ("kb_settings", "kb_types", "kb_topics", "kb_articles", "kb_article_versions")


def _new() -> dict[str, str]:
    return {**CONSOLE, "Idempotency-Key": str(uuid.uuid4())}


def _match(version: int) -> dict[str, str]:
    return {**CONSOLE, "If-Match": f'"{version}"'}


async def _topic(
    world: World,
    org: Org,
    name: str = "Email",
    **extra: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    body = {"names": {"en": name}, **extra}
    response = await world.call("POST", TOPICS, org, org.admin, json=body, headers=_new())
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _write(
    world: World,
    org: Org,
    user: uuid.UUID,
    topic: dict[str, Any],
    **extra: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - httpx response
    body = {
        "topic_id": topic["id"],
        "type_code": "how_to",
        "title": "Reset your VPN token",
        "body_html": "<p>Open the portal.</p>",
        **extra,
    }
    return await world.call("POST", ARTICLES, org, user, json=body, headers=_new())


async def _article(
    world: World,
    org: Org,
    user: uuid.UUID,
    topic: dict[str, Any],
    **extra: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    response = await _write(world, org, user, topic, **extra)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _publish(world: World, article: dict[str, Any], language: str = "en") -> None:
    """Stand-in for the session 2 approval: the open draft becomes the published version."""
    await world.sql(
        "UPDATE kb_article_versions SET status = 'published', published_at = now()"
        " WHERE article_id = $1 AND language = $2 AND status = 'draft'",
        uuid.UUID(article["id"]),
        language,
    )


# --- topics (REQ-KB-040, 041, 044) ---------------------------------------------------------------


async def test_req_kb_040_topics_nest_six_levels_and_never_under_themselves(world: World) -> None:
    a = world.a
    chain = [await _topic(world, a, "Level 1")]
    for level in range(2, 7):
        chain.append(await _topic(world, a, f"Level {level}", parent_id=chain[-1]["id"]))
    assert [t["depth"] for t in chain] == [1, 2, 3, 4, 5, 6]
    seventh = await world.call(
        "POST",
        TOPICS,
        a,
        a.admin,
        json={"names": {"en": "Level 7"}, "parent_id": chain[-1]["id"]},
        headers=_new(),
    )
    assert field_codes(seventh) == {"parent_id": "topic_too_deep"}

    # Moving level 2 (with its four levels below) under a new top topic would make seven.
    other = await _topic(world, a, "Other")
    side = await _topic(world, a, "Side", parent_id=other["id"])
    deep = await world.call(
        "PATCH",
        f"{TOPICS}/{chain[1]['id']}",
        a,
        a.admin,
        json={"parent_id": side["id"]},
        headers=_match(chain[1]["version"]),
    )
    assert field_codes(deep) == {"parent_id": "topic_too_deep"}
    loop = await world.call(
        "PATCH",
        f"{TOPICS}/{chain[0]['id']}",
        a,
        a.admin,
        json={"parent_id": chain[3]["id"]},
        headers=_match(chain[0]["version"]),
    )
    assert field_codes(loop) == {"parent_id": "topic_under_itself"}

    # A shallow subtree moves with its subtopics, depths following.
    moved = await world.call(
        "PATCH",
        f"{TOPICS}/{chain[4]['id']}",
        a,
        a.admin,
        json={"parent_id": other["id"]},
        headers=_match(chain[4]["version"]),
    )
    assert moved.status_code == 200, moved.text
    tree = {t["id"]: t for t in (await world.call("GET", TOPICS, a, a.admin)).json()}
    assert tree[chain[4]["id"]]["depth"] == 2
    assert tree[chain[5]["id"]]["depth"] == 3


async def test_req_kb_040_topic_names_and_permission(world: World) -> None:
    a = world.a
    blank = await world.call(
        "POST", TOPICS, a, a.admin, json={"names": {"en": "  "}}, headers=_new()
    )
    assert field_codes(blank) == {"names": "name_required"}
    long = await world.call(
        "POST", TOPICS, a, a.admin, json={"names": {"en": "x" * 201}}, headers=_new()
    )
    assert field_codes(long) == {"names": "value_too_long_max"}
    tech = await world.call(
        "POST", TOPICS, a, a.tech_a, json={"names": {"en": "Mine"}}, headers=_new()
    )
    assert problem(tech) == (403, "permission_denied")


async def test_req_kb_044_topic_audience_limits_who_sees_it(world: World) -> None:
    a = world.a
    gb_only = await _topic(world, a, "Finance", tech_all=False, tech_groups=[str(a.gb)])
    open_topic = await _topic(world, a, "General")
    seen = {t["id"] for t in (await world.call("GET", TOPICS, a, a.tech_a)).json()}
    assert open_topic["id"] in seen
    assert gb_only["id"] not in seen  # tech_a is in GA only
    seen_c = {t["id"] for t in (await world.call("GET", TOPICS, a, a.tech_c)).json()}
    assert gb_only["id"] in seen_c

    nobody = await world.call(
        "POST",
        TOPICS,
        a,
        a.admin,
        json={"names": {"en": "Empty"}, "tech_all": False},
        headers=_new(),
    )
    assert "technician_audience_empty" in field_codes(nobody).values()
    selected = await world.call(
        "POST",
        TOPICS,
        a,
        a.admin,
        json={"names": {"en": "Some"}, "requesters": "selected"},
        headers=_new(),
    )
    assert "requester_audience_empty" in field_codes(selected).values()

    # Writing in a topic you cannot see is the same as a topic that does not exist.
    hidden = await _write(world, a, a.tech_a, gb_only)
    assert problem(hidden) == (404, "kb_topic_not_found")


async def test_req_kb_041_deleting_a_topic_moves_its_articles_first(world: World) -> None:
    a = world.a
    old = await _topic(world, a, "Old")
    child = await _topic(world, a, "Old child", parent_id=old["id"])
    new = await _topic(world, a, "New")
    article = await _article(world, a, a.tech_a, child)

    refused = await world.call(
        "DELETE", f"{TOPICS}/{old['id']}", a, a.admin, headers=_match(old["version"])
    )
    assert field_codes(refused) == {"move_to": "move_articles_first"}
    assert refused.json()["errors"][0]["params"] == {"count": 1}
    into_itself = await world.call(
        "DELETE",
        f"{TOPICS}/{old['id']}",
        a,
        a.admin,
        params={"move_to": child["id"]},
        headers=_match(old["version"]),
    )
    assert field_codes(into_itself) == {"move_to": "topic_under_itself"}

    deleted = await world.call(
        "DELETE",
        f"{TOPICS}/{old['id']}",
        a,
        a.admin,
        params={"move_to": new["id"]},
        headers=_match(old["version"]),
    )
    assert deleted.status_code == 204, deleted.text
    seen = {t["id"] for t in (await world.call("GET", TOPICS, a, a.admin)).json()}
    assert old["id"] not in seen
    assert child["id"] not in seen  # with its subtopics
    moved = await world.call("GET", f"{ARTICLES}/{article['id']}", a, a.admin)
    assert moved.json()["topic_id"] == new["id"]


# --- articles and drafts (REQ-KB-001, 005, 012, 013, 033, 034) -----------------------------------


async def test_req_kb_001_writing_an_article_makes_its_first_draft(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _article(
        world,
        a,
        a.tech_a,
        topic,
        keywords=["vpn, remote access", "token"],
        body_html='<p>Hi<script>alert(1)</script></p><div data-callout="tip">Tip</div>',
    )
    assert article["display_id"].startswith("KB-")
    assert article["owner_id"] == str(a.tech_a)  # REQ-KB-033: the author owns it
    assert article["published"] == {}
    draft = article["drafts"]["en"]
    assert (draft["number"], draft["status"]) == (1, "draft")
    assert draft["keywords"] == ["vpn", "remote access", "token"]  # REQ-KB-005 AC2
    assert "script" not in draft["body_html"]
    assert 'data-callout="tip"' in draft["body_html"]  # D-108 callouts survive sanitising
    # REQ-KB-034 AC1: the review date comes from the type (how-to: 12 months).
    assert article["review_on"] == add_months(datetime.now(UTC).date(), 12).isoformat()
    assert article["can_edit"] is True

    events = await world.sql(
        "SELECT event_type FROM outbox_events WHERE tenant_id = $1 AND aggregate_id = $2",
        a.tenant,
        article["id"],
    )
    assert [e["event_type"] for e in events] == ["knowledge.article.saved"]


async def test_req_kb_001_article_validation(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    assert field_codes(await _write(world, a, a.tech_a, topic, title=" ")) == {
        "title": "title_required"
    }
    assert field_codes(await _write(world, a, a.tech_a, topic, type_code="nope")) == {
        "type_code": "unknown_article_type"
    }
    # Workarounds and known issues arrive with problem management (REQ-KB-008); not offered yet.
    for kind in ("workaround", "known_issue"):
        assert field_codes(await _write(world, a, a.tech_a, topic, type_code=kind)) == {
            "type_code": "unknown_article_type"
        }
    past = await _write(world, a, a.tech_a, topic, review_on="2020-01-01")
    assert field_codes(past) == {"review_on": "review_date_past"}
    backwards = await _write(
        world, a, a.tech_a, topic, review_on="2099-06-01", expires_on="2099-01-01"
    )
    assert field_codes(backwards) == {"expires_on": "expiry_before_review"}
    types = (await world.call("GET", "/knowledge/types", a, a.tech_a)).json()
    assert [t["code"] for t in types] == [
        "how_to",
        "troubleshooting",
        "faq",
        "reference",
        "policy",
    ]
    requester = await _write(world, a, a.requester, topic)
    assert problem(requester) == (403, "permission_denied")


async def test_req_kb_044_ac3_an_article_only_narrows_its_topic(world: World) -> None:
    a = world.a
    ga_only = await _topic(world, a, "Ops", tech_all=False, tech_groups=[str(a.ga)])
    wider = await _write(world, a, a.tech_a, ga_only, own_audience=True, tech_all=True)
    assert "wider_than_topic" in field_codes(wider).values()
    other_group = await _write(
        world, a, a.tech_a, ga_only, own_audience=True, tech_all=False, tech_groups=[str(a.gb)]
    )
    assert "wider_than_topic" in field_codes(other_group).values()
    to_requesters = await _write(
        world, a, a.tech_a, ga_only, own_audience=True, tech_all=False,
        tech_groups=[str(a.ga)], requesters="all",
    )  # fmt: skip
    assert "wider_than_topic" in field_codes(to_requesters).values()


async def test_req_kb_013_autosave_with_if_match_and_one_draft_per_language(
    world: World,
) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _article(world, a, a.tech_a, topic)
    draft = article["drafts"]["en"]
    url = f"{ARTICLES}/{article['id']}/drafts/en"
    saved = await world.call(
        "PATCH",
        url,
        a,
        a.tech_a,
        json={"title": "Reset a VPN token"},
        headers=_match(draft["version"]),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "Reset a VPN token"
    stale = await world.call(
        "PATCH", url, a, a.tech_a, json={"title": "Old tab"}, headers=_match(draft["version"])
    )
    assert problem(stale) == (409, "version_conflict")

    again = await world.call("POST", url, a, a.tech_a)
    assert problem(again) == (409, "kb_draft_exists")
    missing = await world.call(
        "PATCH",
        f"{ARTICLES}/{article['id']}/drafts/ar",
        a,
        a.tech_a,
        json={"title": "x"},
        headers=_match(1),
    )
    assert problem(missing) == (404, "kb_draft_not_found")
    translation = await world.call("POST", f"{ARTICLES}/{article['id']}/drafts/ar", a, a.tech_a)
    assert translation.status_code == 201, translation.text
    assert translation.json()["language"] == "ar"

    # A version in review is locked for edits (REQ-KB-013, the review flow is session 2).
    await world.sql(
        "UPDATE kb_article_versions SET status = 'in_review' WHERE article_id = $1"
        " AND language = 'en'",
        uuid.UUID(article["id"]),
    )
    locked = await world.call(
        "PATCH", url, a, a.tech_a, json={"title": "y"}, headers=_match(saved.json()["version"])
    )
    assert problem(locked) == (409, "kb_draft_in_review")


async def test_req_kb_020_a_new_version_starts_from_the_published_one(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _article(world, a, a.tech_a, topic)
    await _publish(world, article)
    started = await world.call("POST", f"{ARTICLES}/{article['id']}/drafts/en", a, a.tech_a)
    assert started.status_code == 201, started.text
    assert (started.json()["number"], started.json()["title"]) == (2, "Reset your VPN token")
    read = (await world.call("GET", f"{ARTICLES}/{article['id']}", a, a.tech_a)).json()
    assert read["published"]["en"]["number"] == 1
    assert read["drafts"]["en"]["number"] == 2


async def test_req_kb_020_ac2_published_versions_never_change(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _article(world, a, a.tech_a, topic)
    await _publish(world, article)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        with pytest.raises(Exception, match="cannot change") as caught:
            await session.execute(
                text("UPDATE kb_article_versions SET title = 'Changed' WHERE article_id = :id"),
                {"id": uuid.UUID(article["id"])},
            )
        assert (
            getattr(getattr(caught.value, "orig", None), "sqlstate", None) == "55000"
        )  # object_not_in_prerequisite_state
    # Its status may still move on (published → superseded), which the approval flow needs.
    await world.sql(
        "UPDATE kb_article_versions SET status = 'superseded' WHERE article_id = $1",
        uuid.UUID(article["id"]),
    )
    with pytest.raises(asyncpg.exceptions.ObjectNotInPrerequisiteStateError):
        await world.sql(
            "UPDATE kb_article_versions SET status = 'published' WHERE article_id = $1",
            uuid.UUID(article["id"]),
        )


# --- who reads what (D-108 (1), (4); REQ-KB-043, 048) --------------------------------------------


async def test_d108_drafts_only_for_author_owners_and_approvers(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _article(world, a, a.tech_a, topic)
    url = f"{ARTICLES}/{article['id']}"
    assert problem(await world.call("GET", url, a, a.tech_c)) == (404, "kb_article_not_found")
    assert (await world.call("GET", url, a, a.admin)).json()["drafts"]["en"]["number"] == 1
    mine = (await world.call("GET", ARTICLES, a, a.tech_a, params={"view": "my_drafts"})).json()
    assert [r["id"] for r in mine] == [article["id"]]
    theirs = await world.call("GET", ARTICLES, a, a.tech_c, params={"view": "my_drafts"})
    assert theirs.json() == []

    await _publish(world, article)
    read = (await world.call("GET", url, a, a.tech_c)).json()
    assert read["published"]["en"]["title"] == "Reset your VPN token"
    assert read["drafts"] == {}
    assert read["can_edit"] is False
    assert read["published"]["en"]["internal_note"] is None
    edit = await world.call(
        "PATCH", url, a, a.tech_c, json={"review_on": "2099-01-01"}, headers=_match(read["version"])
    )
    assert problem(edit) == (403, "kb_article_not_editable")


async def test_req_kb_048_lists_and_search_use_the_same_audience(world: World) -> None:
    a = world.a
    finance = await _topic(world, a, "Finance", tech_all=False, tech_groups=[str(a.gb)])
    general = await _topic(world, a, "General")
    hidden = await _article(world, a, a.admin, finance, title="Expense claims and VPN")
    shown = await _article(world, a, a.admin, general, title="Printer VPN setup")
    for article in (hidden, shown):
        await _publish(world, article)

    def ids(response: Any) -> set[str]:  # noqa: ANN401 - httpx response
        assert response.status_code == 200, response.text
        return {r["id"] for r in response.json()}

    listed = ids(await world.call("GET", ARTICLES, a, a.tech_a))
    assert shown["id"] in listed
    assert hidden["id"] not in listed
    found = ids(await world.call("GET", ARTICLES, a, a.tech_a, params={"q": "vpn"}))
    assert found == {shown["id"]}
    assert ids(await world.call("GET", ARTICLES, a, a.tech_b, params={"q": "expense"})) == {
        hidden["id"]
    }
    url = f"{ARTICLES}/{hidden['id']}"
    assert problem(await world.call("GET", url, a, a.tech_a)) == (404, "kb_article_not_found")


async def test_d108_requesters_read_published_never_drafts(world: World) -> None:
    """Requesters read published articles addressed to them (session 2); never drafts."""
    a = world.a
    topic = await _topic(world, a, requesters="all")
    article = await _article(world, a, a.admin, topic)
    url = f"{ARTICLES}/{article['id']}"
    assert (await world.call("GET", ARTICLES, a, a.requester)).json() == []
    assert problem(await world.call("GET", url, a, a.requester)) == (404, "kb_article_not_found")
    await _publish(world, article)
    read = (await world.call("GET", url, a, a.requester)).json()
    assert read["published"]["en"]["internal_note"] is None
    assert (read["drafts"], read["can_edit"]) == ({}, False)
    listed = await world.call("GET", ARTICLES, a, a.requester, params={"view": "my_drafts"})
    assert listed.json() == []


async def test_article_update_checks_version_and_dates(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    other = await _topic(world, a, "Other")
    article = await _article(world, a, a.tech_a, topic)
    url = f"{ARTICLES}/{article['id']}"
    moved = await world.call(
        "PATCH",
        url,
        a,
        a.tech_a,
        json={"topic_id": other["id"], "review_on": "2099-01-01"},
        headers=_match(article["version"]),
    )
    assert moved.status_code == 200, moved.text
    assert (moved.json()["topic_id"], moved.json()["review_on"]) == (other["id"], "2099-01-01")
    stale = await world.call(
        "PATCH", url, a, a.tech_a, json={"type_code": "faq"}, headers=_match(article["version"])
    )
    assert problem(stale) == (409, "version_conflict")
    bad = await world.call(
        "PATCH",
        url,
        a,
        a.tech_a,
        json={"expires_on": "2098-01-01"},
        headers=_match(moved.json()["version"]),
    )
    assert field_codes(bad) == {"expires_on": "expiry_before_review"}
    history = await world.sql(
        "SELECT field FROM field_changes WHERE record_id = $1",
        uuid.UUID(article["id"]),
    )
    assert {"topic_id", "review_on"} <= {h["field"] for h in history}


# --- RLS: every new table -------------------------------------------------------------------------


async def test_knowledge_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    topic = await _topic(world, a)
    article = await _article(world, a, a.tech_a, topic)
    assert (await world.call("GET", "/knowledge/types", a, a.admin)).status_code == 200
    rows = await world.sql(
        "SELECT (SELECT count(*) FROM kb_settings WHERE tenant_id = $1) AS settings,"
        " (SELECT count(*) FROM kb_types WHERE tenant_id = $1) AS types",
        a.tenant,
    )
    assert rows[0]["settings"] == 1
    assert rows[0]["types"] > 0
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in TABLES:
            count = await session.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608 - fixed names
            assert count == 0, table
        for statement in (
            "UPDATE kb_topics SET sort_order = 9",
            "UPDATE kb_articles SET type_code = 'faq'",
            "UPDATE kb_article_versions SET title = 'x'",
            "UPDATE kb_types SET review_months = 1",
            "UPDATE kb_settings SET prefix = 'X'",
        ):
            assert (await session.execute(text(statement))).rowcount == 0, statement
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO kb_topics (id, tenant_id, depth, sort_order, names)"
                    " VALUES (:id, :other, 1, 0, '{}')"
                ),
                {"id": uuid.uuid4(), "other": a.tenant},
            )
    assert problem(await world.call("GET", f"{ARTICLES}/{article['id']}", b, b.admin)) == (
        404,
        "kb_article_not_found",
    )
    assert (await world.call("GET", TOPICS, b, b.admin)).json() == []
