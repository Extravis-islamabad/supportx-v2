"""Knowledge search, suggestions, votes and the portal's reads over HTTP (WP-034 s1, D-125).

Test names cite parity file 08 (REQ-KB-*). The incident world of test_incidents_api.py: tech_a
reads group GA's knowledge, tech_b group GB's; requester and requester2 read by requester
audience; org B for isolation.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db import test_incidents_api
from tests.db.test_incidents_api import Org, World, problem
from tests.db.test_knowledge_api import ARTICLES, _article, _match, _new, _publish, _topic
from tests.db.test_knowledge_review_api import SETTINGS, _approve, _published, _read, _submit, _url

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

SUGGEST = "/knowledge/suggestions"


async def _rows(world: World, org: Org, user: uuid.UUID, path: str, **params: Any) -> list[Any]:  # noqa: ANN401 - query values
    response = await world.call("GET", path, org, user, params=params)
    assert response.status_code == 200, response.text
    return list(response.json())


def _ids(rows: list[Any]) -> set[str]:
    return {r["id"] for r in rows}


async def _hidden(world: World, org: Org) -> dict[str, Any]:
    """A published article only group GB's technicians may read (tech_a may not)."""
    gb_only = await _topic(world, org, "Payroll desk", tech_all=False, tech_groups=[str(org.gb)])
    article = await _article(
        world,
        org,
        org.admin,
        gb_only,
        title="Printer spooler restart for payroll",
        body_html="<p>Restart the printer spooler service on the payroll server.</p>",
        keywords=["printer"],
    )
    await _publish(world, article)
    return article


# --- search (REQ-KB-053) -------------------------------------------------------------------------


async def test_req_kb_053_topic_names_typos_snippets_and_freshness(world: World) -> None:
    a = world.a
    printers = await _topic(world, a, "Printers")
    article = await _published(
        world,
        a,
        printers,
        title="Clear a paper jam",
        body_html="<p>Open tray two and pull the sheet out slowly. Never use force.</p>",
    )
    # AC3: found at once, in the same transaction that published it.
    assert article["id"] in _ids(await _rows(world, a, a.tech_a, ARTICLES, q="paper jam"))
    # AC2: a topic's name finds its articles ("printers" is not in the article's own text).
    assert article["id"] in _ids(await _rows(world, a, a.tech_a, ARTICLES, q="printers"))
    # AC1: a typo in the title still finds it (pg_trgm).
    assert article["id"] in _ids(await _rows(world, a, a.tech_a, ARTICLES, q="papr jam"))
    # AC4: the snippet marks the searched word as data, never as markup.
    rows = await _rows(world, a, a.tech_a, ARTICLES, q="tray")
    snippet = next(r for r in rows if r["id"] == article["id"])["snippet"]
    assert {"text": "tray", "mark": True} in [
        {"text": p["text"].lower(), "mark": p["mark"]} for p in snippet
    ]
    assert all("<" not in p["text"] for p in snippet)


async def test_req_kb_053_filters_audience_featured_and_dates(world: World) -> None:
    a = world.a
    open_topic = await _topic(world, a, "Open to all", requesters="all")
    staff_topic = await _topic(world, a, "Staff only", requesters="none")
    shared = await _published(world, a, open_topic, title="Join the Wi-Fi")
    internal = await _published(world, a, staff_topic, title="Rotate the Wi-Fi key")
    for_requesters = _ids(await _rows(world, a, a.admin, ARTICLES, audience="requesters"))
    assert shared["id"] in for_requesters
    assert internal["id"] not in for_requesters
    assert internal["id"] in _ids(await _rows(world, a, a.admin, ARTICLES, audience="staff_only"))

    current = (await _read(world, a, a.admin, shared)).json()
    featured = await world.call(
        "PATCH",
        _url(shared),
        a,
        a.admin,
        json={"featured": True},
        headers=_match(current["version"]),
    )
    assert featured.status_code == 200, featured.text
    assert _ids(await _rows(world, a, a.admin, ARTICLES, featured="true")) >= {shared["id"]}
    assert internal["id"] not in _ids(await _rows(world, a, a.admin, ARTICLES, featured="true"))
    assert _ids(await _rows(world, a, a.admin, ARTICLES, updated_to="2000-01-01")) == set()


# --- one visibility rule everywhere (coordinator, 2026-11-02) ------------------------------------


async def test_a_hidden_article_never_appears_in_search_suggestions_or_popular(
    world: World,
) -> None:
    a = world.a
    hidden = await _hidden(world, a)
    # Popular needs points: a helpful vote by someone who may read it.
    version = (await _read(world, a, a.tech_b, hidden)).json()["published"]["en"]["id"]
    voted = await world.call(
        "PUT", _url(hidden, "/vote"), a, a.tech_b, json={"version_id": version, "helpful": True}
    )
    assert voted.status_code == 200, voted.text

    for user, sees in ((a.tech_b, True), (a.tech_a, False), (a.requester, False)):
        searched = _ids(await _rows(world, a, user, ARTICLES, q="printer spooler"))
        suggested = _ids(await _rows(world, a, user, SUGGEST, text="printer spooler broken"))
        popular = _ids(await _rows(world, a, user, ARTICLES, order="popular"))
        home = await world.call("GET", "/knowledge/portal/home", a, user)
        in_home = home.status_code == 200 and hidden["id"] in {
            r["id"] for part in ("recent", "popular", "featured") for r in home.json()[part]
        }
        assert (hidden["id"] in searched, hidden["id"] in suggested) == (sees, sees), user
        assert (hidden["id"] in popular) == sees, user
        assert in_home == sees, user


# --- suggestions (REQ-KB-062) ---------------------------------------------------------------------


async def test_req_kb_062_suggestions_published_only_any_word_same_rule(world: World) -> None:
    a = world.a
    topic = await _topic(world, a, "Accounts", requesters="all")
    answer = await _published(
        world, a, topic, title="Unlock your account", body_html="<p>Use the self-service page.</p>"
    )
    draft = await _article(world, a, a.tech_a, topic, title="Unlock a locked mailbox")
    # Any word matches, best first; a draft is never suggested (AC2).
    found = _ids(await _rows(world, a, a.tech_a, SUGGEST, text="my account is locked again"))
    assert answer["id"] in found
    assert draft["id"] not in found
    # AC1: the requester gets the same service under their own rule.
    assert answer["id"] in _ids(await _rows(world, a, a.requester, SUGGEST, text="unlock account"))
    # Too little typed: nothing yet.
    assert await _rows(world, a, a.tech_a, SUGGEST, text="ac") == []


# --- did this help? (REQ-KB-069) -----------------------------------------------------------------


async def _vote(
    world: World,
    org: Org,
    user: uuid.UUID,
    article: dict[str, Any],
    **body: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call("PUT", _url(article, "/vote"), org, user, json=body)


async def test_req_kb_069_vote_change_scores_and_a_new_version_starts_at_zero(
    world: World,
) -> None:
    a = world.a
    topic = await _topic(world, a, "Laptops", requesters="all")
    article = await _published(world, a, topic, title="Battery drains fast")
    v1 = (await _read(world, a, a.requester, article)).json()["published"]["en"]["id"]

    no = await _vote(
        world,
        a,
        a.requester,
        article,
        version_id=v1,
        helpful=False,
        reason="out_of_date",
        comment="The menu moved.",
    )
    assert no.status_code == 200, no.text
    assert (
        await _vote(world, a, a.tech_a, article, version_id=v1, helpful=True)
    ).status_code == 200
    # AC2: voting again changes the vote, never adds one.
    again = await _vote(world, a, a.tech_a, article, version_id=v1, helpful=False)
    assert again.json()["helpful"] is False
    assert (await _read(world, a, a.tech_a, article)).json()["my_vote"]["helpful"] is False

    scores = (await world.call("GET", _url(article, "/votes"), a, a.admin)).json()
    assert (scores["helpful"], scores["not_helpful"]) == (0, 2)
    assert scores["feedback"][0]["reason"] == "out_of_date"
    assert "person_id" not in scores["feedback"][0]  # what was said, never who
    # Requesters never see scores.
    assert problem(await world.call("GET", _url(article, "/votes"), a, a.requester))[0] == 403

    # Refusals: a reason with "yes", an unknown reason, a version readers do not see.
    yes_with_reason = await _vote(
        world, a, a.requester, article, version_id=v1, helpful=True, reason="other"
    )
    assert yes_with_reason.status_code == 422
    unknown = await _vote(world, a, a.requester, article, version_id=v1, helpful=False, reason="x")
    assert unknown.status_code == 422
    stray = await _vote(world, a, a.requester, article, version_id=str(uuid.uuid4()), helpful=True)
    assert problem(stray) == (404, "kb_version_not_published")

    # AC3: a new version starts at zero; the old one keeps its score.
    current = (await _read(world, a, a.tech_a, article)).json()
    redraft = await world.call(
        "POST", _url(article, "/drafts/en"), a, a.tech_a, headers=_match(current["version"])
    )
    assert redraft.status_code in (200, 201), redraft.text
    await _submit(world, a, a.tech_a, article)
    assert (await _approve(world, a, a.admin, article)).status_code == 200
    scores = (await world.call("GET", _url(article, "/votes"), a, a.admin)).json()
    assert (scores["helpful"], scores["not_helpful"]) == (0, 0)
    assert [(v["number"], v["not_helpful"]) for v in scores["versions"]] == [(1, 2)]


async def test_kb_votes_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    topic = await _topic(world, a, "Phones", requesters="all")
    article = await _published(world, a, topic, title="Voicemail PIN")
    version = (await _read(world, a, a.requester, article)).json()["published"]["en"]["id"]
    voted = await _vote(world, a, a.requester, article, version_id=version, helpful=True)
    assert voted.status_code == 200, voted.text
    # Tenant B cannot vote on tenant A's article, read its votes, or write one into tenant A.
    other = await _vote(world, b, b.requester, article, version_id=version, helpful=True)
    assert problem(other) == (404, "kb_article_not_found")
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await session.scalar(text("SELECT count(*) FROM kb_votes")) == 0
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO kb_votes (id, tenant_id, article_id, version_id, person_id,"
                    " helpful) VALUES (:id, :other, :article, :version, :who, true)"
                ),
                {
                    "id": uuid.uuid4(),
                    "other": a.tenant,
                    "article": uuid.UUID(article["id"]),
                    "version": uuid.UUID(version),
                    "who": b.requester,
                },
            )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await session.scalar(text("SELECT count(*) FROM kb_votes")) == 1


# --- the portal's reads (REQ-KB-081) -------------------------------------------------------------


async def test_req_kb_081_portal_topics_and_home_follow_the_reader_rule(world: World) -> None:
    a = world.a
    open_topic = await _topic(world, a, "Getting started", requesters="all")
    staff_topic = await _topic(world, a, "Internal runbooks", requesters="none")
    empty_topic = await _topic(world, a, "Nothing yet", requesters="all")
    welcome = await _published(world, a, open_topic, title="Welcome to the service desk")
    await _published(world, a, staff_topic, title="Failover runbook")

    topics = await _rows(world, a, a.requester, "/knowledge/portal/topics")
    names = {t["names"]["en"]: t["articles"] for t in topics}
    # AC1: only topics with something this requester may open.
    assert names.get("Getting started") == 1
    assert "Internal runbooks" not in names
    assert empty_topic["names"]["en"] not in names
    home = (await world.call("GET", "/knowledge/portal/home", a, a.requester)).json()
    assert welcome["id"] in {r["id"] for r in home["recent"]}

    # AC2: requester knowledge off answers 404 to requesters, never an empty page.
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
    for path in ("/knowledge/portal/topics", "/knowledge/portal/home"):
        assert problem(await world.call("GET", path, a, a.requester)) == (404, "kb_requesters_off")
    assert (await world.call("GET", "/knowledge/portal/topics", a, a.tech_a)).status_code == 200


async def test_req_kb_062_ac3_the_setting_and_a_link_chosen_from_suggestions(world: World) -> None:
    a = world.a
    settings = (await world.call("GET", SETTINGS, a, a.admin)).json()
    assert settings["suggest_on_technician_form"] is True  # on by default
    off = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"suggest_on_technician_form": False},
        headers=_match(settings["version"]),
    )
    assert off.status_code == 200, off.text
    assert off.json()["suggest_on_technician_form"] is False
    # REQ-INC-021: an article picked from the suggestions is linked as such after the create.
    topic = await _topic(world, a, "Mail")
    article = await _published(world, a, topic, title="Mailbox full")
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    made = await world.call(
        "POST",
        _url(article, "/links"),
        a,
        a.tech_a,
        json={"record_type": "incident", "record_id": item["id"], "how": "suggestion"},
        headers=_new(),
    )
    assert made.status_code == 201, made.text
    assert made.json()["source"] == "suggestion"
