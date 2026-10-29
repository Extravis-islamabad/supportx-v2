"""Knowledge over HTTP, session 2 (WP-033, D-108): review, publishing, withdrawal, requesters.

Test names cite parity file 08 (REQ-KB-*). The incident world of test_incidents_api.py: org A
has an admin (every permission), technicians tech_a (group GA, site S1), tech_b (GB, S2),
tech_c (GA and GB, S1), requester (S1) and requester2 (S2); org B for isolation. Technicians
hold the built-in defaults (D-108 (7)): read their groups' knowledge, write, edit their own and
submit; approving, withdrawing and the trash are the admin's.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.errors import NotFound
from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.knowledge.domain.knowledge import add_months
from app.modules.knowledge.service.file_access import FILE_ACCESS
from app.modules.knowledge.service.notifications import remind_due_reviews
from app.modules.knowledge.service.owners import hand_over
from app.modules.knowledge.service.realtime import ROUTES
from app.shared.events import EventEnvelope
from app.shared.files.ports import Action, OwnerType
from tests.db import test_incidents_api
from tests.db.test_incidents_api import Org, World, field_codes, problem, unit
from tests.db.test_knowledge_api import ARTICLES, _article, _match, _topic
from tests.db.test_notifications_api import run_engine

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

SETTINGS = "/knowledge/settings"


def _url(article: dict[str, Any], tail: str = "") -> str:
    return f"{ARTICLES}/{article['id']}{tail}"


async def _read(world: World, org: Org, user: uuid.UUID, article: dict[str, Any]) -> Any:  # noqa: ANN401 - httpx response
    return await world.call("GET", _url(article), org, user)


async def _submit(
    world: World, org: Org, user: uuid.UUID, article: dict[str, Any], language: str = "en"
) -> dict[str, Any]:
    """Send the open draft to review; the version in review."""
    current = (await _read(world, org, user, article)).json()["drafts"][language]
    response = await world.call(
        "POST",
        _url(article, f"/drafts/{language}/submit"),
        org,
        user,
        json={"note": "Ready"},
        headers=_match(current["version"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "in_review"
    return dict(response.json())


async def _approve(
    world: World, org: Org, user: uuid.UUID, article: dict[str, Any], language: str = "en"
) -> Any:  # noqa: ANN401 - httpx response
    current = (await _read(world, org, user, article)).json()["drafts"][language]
    return await world.call(
        "POST",
        _url(article, f"/drafts/{language}/approve"),
        org,
        user,
        headers=_match(current["version"]),
    )


async def _published(
    world: World,
    org: Org,
    topic: dict[str, Any],
    **extra: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    """An article tech_a wrote and the admin approved."""
    article = await _article(world, org, org.tech_a, topic, **extra)
    await _submit(world, org, org.tech_a, article)
    approved = await _approve(world, org, org.admin, article)
    assert approved.status_code == 200, approved.text
    return dict(approved.json())


def _ids(response: Any) -> set[str]:  # noqa: ANN401 - httpx response
    assert response.status_code == 200, response.text
    return {r["id"] for r in response.json()}


async def _list(world: World, org: Org, user: uuid.UUID, **params: str) -> set[str]:
    return _ids(await world.call("GET", ARTICLES, org, user, params=params))


# --- submit, approve, reject (REQ-KB-027) --------------------------------------------------------


async def test_req_kb_027_submit_then_approve_publishes_to_the_audience(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _article(world, a, a.tech_a, topic)
    await _submit(world, a, a.tech_a, article)

    # D-108 (1) / the D-074 default: in review is hidden from other technicians.
    assert problem(await _read(world, a, a.tech_c, article)) == (404, "kb_article_not_found")
    assert article["id"] not in await _list(world, a, a.tech_c, view="in_review")
    assert article["id"] not in await _list(world, a, a.tech_c, q="vpn")
    # The approver sees it at once: the inbox and its count (REQ-KB-077, 086).
    assert article["id"] in await _list(world, a, a.admin, view="awaiting_approval")
    count = await world.call("GET", "/knowledge/approvals/count", a, a.admin)
    assert count.json()["count"] >= 1
    assert (await world.call("GET", "/knowledge/approvals/count", a, a.tech_c)).json() == {
        "count": 0
    }
    # A technician without approve rights cannot decide.
    refused = await _approve(world, a, a.tech_a, article)
    assert problem(refused) == (403, "kb_cannot_approve")
    assert (await _read(world, a, a.admin, article)).json()["can_approve"] is True

    approved = await _approve(world, a, a.admin, article)
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["published"]["en"]["number"] == 1
    assert body["drafts"] == {}
    read = (await _read(world, a, a.tech_c, article)).json()
    assert read["published"]["en"]["title"] == "Reset your VPN token"
    assert article["id"] in await _list(world, a, a.tech_c, q="vpn")
    # Approving again: nothing is in review any more.
    assert (
        problem(
            await world.call(
                "POST", _url(article, "/drafts/en/approve"), a, a.admin, headers=_match(1)
            )
        )[0]
        == 404
    )

    steps = await world.sql(
        "SELECT envelope->'payload'->>'step' AS step FROM outbox_events"
        " WHERE tenant_id = $1 AND event_type = 'knowledge.article.workflow'"
        " AND aggregate_id = $2 ORDER BY id",
        a.tenant,
        article["id"],
    )
    assert [s["step"] for s in steps] == ["submitted", "approved"]
    audit = await world.sql(
        "SELECT action FROM audit_entries WHERE tenant_id = $1 AND object_id = $2",
        a.tenant,
        article["id"],
    )
    assert "knowledge.article_approved" in {r["action"] for r in audit}


async def test_req_kb_027_reject_needs_a_reason_the_author_sees(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _article(world, a, a.tech_a, topic)
    in_review = await _submit(world, a, a.tech_a, article)
    url = _url(article, "/drafts/en/reject")
    blank = await world.call(
        "POST", url, a, a.admin, json={"reason": "  "}, headers=_match(in_review["version"])
    )
    assert field_codes(blank) == {"reason": "reason_required"}
    rejected = await world.call(
        "POST",
        url,
        a,
        a.admin,
        json={"reason": "Add the screenshots"},
        headers=_match(in_review["version"]),
    )
    assert rejected.status_code == 200, rejected.text
    assert (rejected.json()["status"], rejected.json()["reject_reason"]) == (
        "draft",
        "Add the screenshots",
    )
    mine = (await _read(world, a, a.tech_a, article)).json()
    assert mine["drafts"]["en"]["reject_reason"] == "Add the screenshots"
    # Submitting it again clears the old reason.
    again = await _submit(world, a, a.tech_a, article)
    assert again["reject_reason"] is None
    history = await world.sql(
        "SELECT field FROM field_changes WHERE record_id = $1", uuid.UUID(article["id"])
    )
    assert "version.en.status" in {h["field"] for h in history}


async def test_req_kb_028_self_approval_follows_the_setting(world: World) -> None:
    a = world.a
    settings = await world.call("GET", SETTINGS, a, a.admin)
    assert settings.status_code == 200, settings.text
    assert settings.json()["self_approval"] is True
    # REQ-KB-090: If-Match, and only settings managers.
    tech = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.tech_a,
        json={"self_approval": False},
        headers=_match(settings.json()["version"]),
    )
    assert problem(tech)[0] == 403
    changed = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"self_approval": False},
        headers=_match(settings.json()["version"]),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["self_approval"] is False
    stale = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"self_approval": True},
        headers=_match(settings.json()["version"]),
    )
    assert problem(stale) == (409, "version_conflict")

    topic = await _topic(world, a)
    own = await _article(world, a, a.admin, topic)
    await _submit(world, a, a.admin, own)
    assert problem(await _approve(world, a, a.admin, own)) == (403, "kb_self_approval_off")

    back = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"self_approval": True},
        headers=_match(changed.json()["version"]),
    )
    assert back.status_code == 200, back.text
    assert (await _approve(world, a, a.admin, own)).status_code == 200
    flag = await world.sql(
        "SELECT self_approved FROM kb_article_versions WHERE article_id = $1",
        uuid.UUID(own["id"]),
    )
    assert flag[0]["self_approved"] is True  # history says "approved by the author"


# --- versions (REQ-KB-020, 021) ------------------------------------------------------------------


async def test_req_kb_021_readers_keep_version_n_until_n_plus_1_is_approved(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _published(world, a, topic)
    started = await world.call("POST", _url(article, "/drafts/en"), a, a.tech_a)
    assert started.status_code == 201, started.text
    saved = await world.call(
        "PATCH",
        _url(article, "/drafts/en"),
        a,
        a.tech_a,
        json={"title": "Renew a hardware token"},
        headers=_match(started.json()["version"]),
    )
    assert saved.status_code == 200, saved.text
    await _submit(world, a, a.tech_a, article)

    read = (await _read(world, a, a.tech_c, article)).json()
    assert (read["published"]["en"]["number"], read["published"]["en"]["title"]) == (
        1,
        "Reset your VPN token",
    )
    assert article["id"] not in await _list(world, a, a.tech_c, q="hardware")

    approved = await _approve(world, a, a.admin, article)
    assert approved.status_code == 200, approved.text
    read = (await _read(world, a, a.tech_c, article)).json()
    assert (read["published"]["en"]["number"], read["published"]["en"]["title"]) == (
        2,
        "Renew a hardware token",
    )
    versions = await world.call("GET", _url(article, "/versions"), a, a.tech_c)
    assert [(v["number"], v["status"]) for v in versions.json()] == [
        (2, "published"),
        (1, "superseded"),
    ]


# --- withdraw (REQ-KB-031) -----------------------------------------------------------------------


async def test_req_kb_031_withdraw_leaves_every_reader_path(world: World) -> None:
    a = world.a
    topic = await _topic(world, a, requesters="all")
    article = await _published(world, a, topic)
    assert (await _read(world, a, a.requester, article)).status_code == 200
    url = _url(article, "/withdraw")

    tech = await world.call(
        "POST", url, a, a.tech_c, json={"reason": "Old"}, headers=_match(article["version"])
    )
    assert problem(tech) == (403, "kb_cannot_withdraw")
    blank = await world.call(
        "POST", url, a, a.admin, json={"reason": ""}, headers=_match(article["version"])
    )
    assert field_codes(blank) == {"reason": "reason_required"}
    withdrawn = await world.call(
        "POST",
        url,
        a,
        a.admin,
        json={"reason": "The VPN changed"},
        headers=_match(article["version"]),
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["withdrawn"] is True

    # Readers on an old link: "no longer available"; the requester never learns it existed.
    assert problem(await _read(world, a, a.tech_c, article)) == (404, "kb_article_withdrawn")
    assert problem(await _read(world, a, a.requester, article)) == (404, "kb_article_not_found")
    for user in (a.tech_c, a.requester):
        assert article["id"] not in await _list(world, a, user)
        assert article["id"] not in await _list(world, a, user, q="vpn")
    # Its owner and the withdrawer still see it, with the reason.
    mine = (await _read(world, a, a.tech_a, article)).json()
    assert (mine["withdrawn"], mine["withdrawn_reason"]) == (True, "The VPN changed")
    # Its files follow the article (REQ-KB-048).
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        reader = await subject_for(session, a.tenant, a.tech_c)
        with pytest.raises(NotFound):
            await FILE_ACCESS.check(
                session, reader, OwnerType.KB_ARTICLE, uuid.UUID(article["id"]), Action.VIEW
            )
        owner = await subject_for(session, a.tenant, a.tech_a)
        found = await FILE_ACCESS.check(
            session, owner, OwnerType.KB_ARTICLE, uuid.UUID(article["id"]), Action.ATTACH
        )
        assert found.record_type == "kb_article"

    # Republishing goes through approval: a new version, approved, brings it back.
    assert (await world.call("POST", _url(article, "/drafts/en"), a, a.tech_a)).status_code == 201
    await _submit(world, a, a.tech_a, article)
    back = await _approve(world, a, a.admin, article)
    assert back.status_code == 200, back.text
    assert back.json()["withdrawn"] is False
    assert (await _read(world, a, a.requester, article)).status_code == 200


# --- requesters (REQ-KB-035, 045, 048, 090) -------------------------------------------------------


async def test_req_kb_045_requesters_read_by_group_site_and_department(world: World) -> None:
    a = world.a
    by_site = await _topic(world, a, "S1 only", requesters="selected", req_sites=[str(a.s1)])
    on_site = await _published(world, a, by_site, title="Site printer guide")
    assert article_visible(await _read(world, a, a.requester, on_site))
    assert not article_visible(await _read(world, a, a.requester2, on_site))

    department = await unit(world, a, "departments", "Finance dept", [])
    await world.sql("UPDATE users SET department_id = $1 WHERE id = $2", department, a.requester2)
    open_topic = await _topic(world, a, "Open", requesters="all")
    by_dept = await _published(
        world,
        a,
        open_topic,
        title="Expense claims guide",
        own_audience=True,
        tech_all=True,
        requesters="selected",
        req_departments=[str(department)],
    )
    assert article_visible(await _read(world, a, a.requester2, by_dept))
    assert not article_visible(await _read(world, a, a.requester, by_dept))
    assert by_dept["id"] in await _list(world, a, a.requester2, view="published")
    assert by_dept["id"] not in await _list(world, a, a.requester, q="expense")
    # Requesters have the published view only; never drafts or in-review versions.
    assert await _list(world, a, a.requester2, view="my_drafts") == set()
    draft_only = await _article(world, a, a.tech_a, open_topic, title="Unfinished guide")
    assert not article_visible(await _read(world, a, a.requester, draft_only))

    # REQ-KB-035: expired articles leave requester paths, technicians still see them, marked.
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    await world.sql(
        "UPDATE kb_articles SET review_on = NULL, expires_on = $1 WHERE id = $2",
        datetime.fromisoformat(yesterday).date(),
        uuid.UUID(on_site["id"]),
    )
    assert not article_visible(await _read(world, a, a.requester, on_site))
    assert (await _read(world, a, a.tech_a, on_site)).json()["expired"] is True
    assert on_site["id"] in await _list(world, a, a.tech_a, view="expired")

    # REQ-KB-090: requesters switched off: nothing for any requester.
    settings = (await world.call("GET", SETTINGS, a, a.admin)).json()
    off = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"requesters_enabled": False},
        headers=_match(settings["version"]),
    )
    assert off.status_code == 200, off.text
    assert await _list(world, a, a.requester2) == set()
    assert not article_visible(await _read(world, a, a.requester2, by_dept))


def article_visible(response: Any) -> bool:  # noqa: ANN401 - httpx response
    if response.status_code == 200:
        return True
    assert problem(response) == (404, "kb_article_not_found"), response.text
    return False


# --- still correct, review due (REQ-KB-034, 086) -------------------------------------------------


async def test_req_kb_034_still_correct_moves_the_date_without_a_new_version(
    world: World,
) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _published(world, a, topic)
    today = datetime.now(UTC).date()
    await world.sql(
        "UPDATE kb_articles SET review_on = $1 WHERE id = $2", today, uuid.UUID(article["id"])
    )
    article = (await _read(world, a, a.tech_a, article)).json()
    assert article["review_due"] is True
    assert article["id"] in await _list(world, a, a.tech_a, view="review_due")

    # The owner hears it once per date (the hourly sweep).
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await remind_due_reviews(session) >= 1
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await remind_due_reviews(session) == 0
    reminded = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE aggregate_id = $1"
        " AND envelope->'payload'->>'step' = 'review_due'",
        article["id"],
    )
    assert reminded[0]["n"] == 1

    checked = await world.call(
        "POST", _url(article, "/still-correct"), a, a.tech_a, headers=_match(article["version"])
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["review_on"] == add_months(today, 12).isoformat()
    assert checked.json()["published"]["en"]["number"] == 1  # no new version
    reviews = await world.sql(
        "SELECT reviewed_by FROM kb_reviews WHERE article_id = $1", uuid.UUID(article["id"])
    )
    assert [r["reviewed_by"] for r in reviews] == [a.tech_a]
    other = await world.call(
        "POST",
        _url(article, "/still-correct"),
        a,
        a.tech_c,
        headers=_match(checked.json()["version"]),
    )
    assert problem(other) == (403, "kb_article_not_editable")


# --- trash (REQ-KB-079) ---------------------------------------------------------------------------


async def test_req_kb_079_trash_and_restore(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _published(world, a, topic)
    tech = await world.call(
        "DELETE", _url(article), a, a.tech_a, headers=_match(article["version"])
    )
    assert problem(tech)[0] == 403
    gone = await world.call("DELETE", _url(article), a, a.admin, headers=_match(article["version"]))
    assert gone.status_code == 204, gone.text
    assert problem(await _read(world, a, a.tech_c, article)) == (404, "kb_article_not_found")
    assert article["id"] not in await _list(world, a, a.tech_c)
    assert article["id"] in await _list(world, a, a.admin, view="trash")
    assert await _list(world, a, a.tech_c, view="trash") == set()
    rows = await world.sql(
        "SELECT deleted_at, version FROM kb_articles WHERE id = $1", uuid.UUID(article["id"])
    )
    assert rows[0]["deleted_at"] is not None  # soft delete only (CLAUDE.md §6)

    # Its topic in the trash: restore says so, until the topic is back.
    await world.sql("UPDATE kb_topics SET deleted_at = now() WHERE id = $1", uuid.UUID(topic["id"]))
    blocked = await world.call(
        "POST", _url(article, "/restore"), a, a.admin, headers=_match(rows[0]["version"])
    )
    assert problem(blocked) == (409, "kb_topic_in_trash")
    await world.sql("UPDATE kb_topics SET deleted_at = NULL WHERE id = $1", uuid.UUID(topic["id"]))
    restored = await world.call(
        "POST", _url(article, "/restore"), a, a.admin, headers=_match(rows[0]["version"])
    )
    assert restored.status_code == 200, restored.text
    assert (await _read(world, a, a.tech_c, article)).status_code == 200


# --- notifications (REQ-KB-086) ------------------------------------------------------------------


async def _deliveries(world: World, org: Org, article: dict[str, Any]) -> set[tuple[str, Any, str]]:
    rows = await world.sql(
        "SELECT event_code, user_id, channel FROM notification_deliveries"
        " WHERE tenant_id = $1 AND record_id = $2 AND state <> 'suppressed'",
        org.tenant,
        uuid.UUID(article["id"]),
    )
    return {(r["event_code"], r["user_id"], r["channel"]) for r in rows}


async def test_req_kb_086_review_steps_notify_the_right_people(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _article(world, a, a.tech_a, topic)
    await run_engine(world, a)
    in_review = await _submit(world, a, a.tech_a, article)
    await run_engine(world, a)
    sent = await _deliveries(world, a, article)
    assert ("kb_article.submitted", a.admin, "in_app") in sent
    assert all(user != a.tech_a for _, user, _ in sent)  # never the person who acted
    assert all(user not in {a.tech_b, a.tech_c} for _, user, _ in sent)  # not approvers

    rejected = await world.call(
        "POST",
        _url(article, "/drafts/en/reject"),
        a,
        a.admin,
        json={"reason": "Add the screenshots"},
        headers=_match(in_review["version"]),
    )
    assert rejected.status_code == 200, rejected.text
    await run_engine(world, a)
    assert ("kb_article.rejected", a.tech_a, "in_app") in await _deliveries(world, a, article)
    centre = await world.call("GET", "/notifications", a, a.tech_a)
    titles = [item["title"] for item in centre.json()["items"]]
    assert any("Add the screenshots" in title for title in titles), titles

    await _submit(world, a, a.tech_a, article)
    assert (await _approve(world, a, a.admin, article)).status_code == 200
    await run_engine(world, a)
    assert ("kb_article.approved", a.tech_a, "in_app") in await _deliveries(world, a, article)

    # A requester is never told of review steps, even of an article they may read.
    rows = await world.sql(
        "SELECT user_id FROM notification_deliveries WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        uuid.UUID(article["id"]),
    )
    assert a.requester not in {r["user_id"] for r in rows}


# --- RLS: the new table ---------------------------------------------------------------------------


async def test_kb_reviews_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    topic = await _topic(world, a)
    article = await _published(world, a, topic)
    checked = await world.call(
        "POST", _url(article, "/still-correct"), a, a.tech_a, headers=_match(article["version"])
    )
    assert checked.status_code == 200, checked.text
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await session.scalar(text("SELECT count(*) FROM kb_reviews")) == 0
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO kb_reviews (id, tenant_id, article_id, reviewed_by,"
                    " next_review_on) VALUES (:id, :other, :article, :who, now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "other": a.tenant,
                    "article": uuid.UUID(article["id"]),
                    "who": a.tech_a,
                },
            )
    other = await world.call(
        "POST", _url(article, "/still-correct"), b, b.admin, headers=_match(article["version"])
    )
    assert problem(other) == (404, "kb_article_not_found")


# --- realtime: IDs only to the audience (REQ-KB-048 AC3, rule c) ----------------------------------


async def test_req_kb_048_ac3_live_updates_carry_ids_only_to_the_audience(world: World) -> None:
    a = world.a
    finance = await _topic(world, a, "Finance", tech_all=False, tech_groups=[str(a.gb)])
    article = await _article(world, a, a.admin, finance, title="Expense claims")
    await _submit(world, a, a.admin, article)
    assert (await _approve(world, a, a.admin, article)).status_code == 200
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND aggregate_id = $2"
        " AND event_type = 'knowledge.article.workflow' ORDER BY id",
        a.tenant,
        article["id"],
    )
    route = next(r for r in ROUTES if "knowledge.article.workflow" in r.event_types)
    approved = EventEnvelope.model_validate(json.loads(rows[-1]["envelope"]))
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(approved, session)
    with_ids = [str(p.channel) for p in effects.publications if p.ids]
    assert with_ids, effects.publications
    assert any(str(a.gb) in channel for channel in with_ids)
    assert not any(str(a.ga) in channel or "broadcast" in channel for channel in with_ids)
    # Readers' screens refetch on a broadcast that names nothing.
    assert [p.ids for p in effects.publications if "broadcast" in str(p.channel)] == [()]


# --- session 3a: the article channel, more views, owner hand-over ------------------------------


async def test_req_kb_048_the_article_channel_follows_the_reader_rule(world: World) -> None:
    a = world.a
    network = await _topic(world, a, "Network", tech_all=False, tech_groups=[str(a.ga)])
    article = await _published(world, a, network)

    async def channel(user: uuid.UUID) -> int:
        token = await world.call(
            "POST",
            "/realtime/subscription-token",
            a,
            user,
            json={"channel": f"t:{a.tenant}:kb:{article['id']}"},
        )
        return token.status_code

    assert await channel(a.tech_c) == 200  # in GA
    assert await channel(a.tech_b) == 403  # GB only
    assert await channel(a.requester) == 403
    withdrawn = await world.call(
        "POST",
        _url(article, "/withdraw"),
        a,
        a.admin,
        json={"reason": "Replaced"},
        headers=_match(article["version"]),
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert await channel(a.tech_c) == 403  # a reader loses the page with the article
    assert await channel(a.tech_a) == 200  # its author keeps it

    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND aggregate_id = $2"
        " AND event_type = 'knowledge.article.workflow' ORDER BY id DESC LIMIT 1",
        a.tenant,
        article["id"],
    )
    route = next(r for r in ROUTES if "knowledge.article.workflow" in r.event_types)
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(envelope, session)
    page = [p for p in effects.publications if p.channel.kind == "kb"]
    assert [(p.ids, p.fields) for p in page] == [((article["id"],), ("withdrawn",))]


async def test_req_kb_077_views_and_filters(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    due = await _published(world, a, topic, title="Due today")
    late = await _published(world, a, topic, title="Overdue", type_code="faq")
    gone = await _published(world, a, topic, title="Withdrawn one")
    today = datetime.now(UTC).date()
    await world.sql(
        "UPDATE kb_articles SET review_on = $1 WHERE id = $2", today, uuid.UUID(due["id"])
    )
    await world.sql(
        "UPDATE kb_articles SET review_on = $1 WHERE id = $2",
        today - timedelta(days=3),
        uuid.UUID(late["id"]),
    )
    pulled = await world.call(
        "POST",
        _url(gone, "/withdraw"),
        a,
        a.admin,
        json={"reason": "Old"},
        headers=_match(gone["version"]),
    )
    assert pulled.status_code == 200, pulled.text

    assert due["id"] in await _list(world, a, a.admin, view="due_today")
    assert late["id"] not in await _list(world, a, a.admin, view="due_today")
    assert late["id"] in await _list(world, a, a.admin, view="overdue")
    assert due["id"] not in await _list(world, a, a.admin, view="overdue")
    assert await _list(world, a, a.admin, view="withdrawn") >= {gone["id"]}
    assert gone["id"] not in await _list(world, a, a.tech_c, view="withdrawn")  # a reader
    assert gone["id"] in await _list(world, a, a.tech_a, view="withdrawn")  # its author
    assert await _list(world, a, a.admin, type_code="faq") & {due["id"], late["id"]} == {late["id"]}
    assert due["id"] in await _list(world, a, a.admin, owner_id=str(a.tech_a))
    assert await _list(world, a, a.admin, owner_id=str(a.tech_b)) & {due["id"]} == set()
    assert await _list(world, a, a.admin, only_language="ar") & {due["id"]} == set()
    rows = await world.call("GET", ARTICLES, a, a.admin, params={"view": "overdue"})
    row = next(r for r in rows.json() if r["id"] == late["id"])
    assert (row["review_due"], row["withdrawn"], row["owner_id"]) == (True, False, str(a.tech_a))


async def test_req_kb_033_ac2_a_deactivated_owner_hands_over_to_the_topic_owner(
    world: World,
) -> None:
    a = world.a
    owned = await _topic(world, a, "Owned", owner_id=str(a.tech_c))
    orphan = await _topic(world, a, "No owner")
    moved = await _published(world, a, owned)
    kept = await _published(world, a, orphan)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await hand_over(session, a.tech_a) == 1
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await hand_over(session, a.tech_a) == 0  # idempotent
    assert (await _read(world, a, a.admin, moved)).json()["owner_id"] == str(a.tech_c)
    assert (await _read(world, a, a.admin, kept)).json()["owner_id"] == str(a.tech_a)
    history = await world.sql(
        "SELECT field, source FROM field_changes WHERE record_id = $1 AND field = 'owner_id'",
        uuid.UUID(moved["id"]),
    )
    assert [(h["field"], h["source"]) for h in history] == [("owner_id", "system")]


async def test_req_kb_080_history_for_those_who_work_on_the_article(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    article = await _published(world, a, topic)
    url = _url(article, "/history")
    mine = await world.call("GET", url, a, a.tech_a)
    assert mine.status_code == 200, mine.text
    fields = {c["field"] for e in mine.json()["items"] for c in e["changes"]}
    assert {"version.en.status", "version.en.published"} <= fields
    assert (await world.call("GET", url, a, a.admin)).status_code == 200
    reader = await world.call("GET", url, a, a.tech_c)  # reads it, may not work on it
    assert problem(reader) == (404, "kb_article_not_found")
