"""Announcements over HTTP (WP-012, the walking skeleton): every platform rule on one entity.

Real PostgreSQL and Valkey; the session is faked by headers like the access tests. Each test
builds its own tenants in the session's throwaway database, so nothing here touches dev data.

Who is who in org A (`Ann`):
    admin       tenant admin (everything, all scopes)
    comms       custom role "Comms": view / manage / publish, all scopes (the second publisher)
    site_tech   custom role "Site announcer": view + manage at *site* scope; member of site S1
    tech        built-in technician: view all, manage own
    requester   built-in requester, member of site S1 (the audience)
    outsider    built-in requester, member of nothing
"""

import json
import statistics
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import time as day_start
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import Database
from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from app.modules.announcements.service.realtime import ROUTES
from app.shared.events import EventEnvelope
from conftest import assign_system_role, create_tenant, make_settings
from tests.db.test_access_api import fake_session
from tests.db.test_entitlements import set_term
from tests.db.test_rate_limit import valkey_url
from tests.db.test_users_api import seed_users
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]

BASE = "/announcements"
KARACHI = ZoneInfo("Asia/Karachi")
HONOLULU = ZoneInfo("Pacific/Honolulu")
CONSOLE = {"X-SupportX-Client": "console"}


@dataclass
class Ann:
    """One tenant with the cast described in the module docstring."""

    tenant: uuid.UUID
    admin: uuid.UUID
    comms: uuid.UUID
    site_tech: uuid.UUID
    tech: uuid.UUID
    requester: uuid.UUID
    outsider: uuid.UUID
    s1: uuid.UUID = field(default_factory=uuid.uuid4)
    s2: uuid.UUID = field(default_factory=uuid.uuid4)
    g1: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class World:
    client: AsyncClient
    db: ThrowawayDatabase
    app: FastAPI
    a: Ann
    b: Ann

    async def call(
        self,
        method: str,
        path: str,
        org: Ann,
        user: uuid.UUID,
        **kw: Any,  # noqa: ANN401 - httpx request options
    ) -> httpx.Response:
        headers = {"X-Test-Tenant": str(org.tenant), "X-Test-User": str(user)}
        headers.update(kw.pop("headers", {}))
        return await self.client.request(method, f"/api/v1{path}", headers=headers, **kw)

    async def create(self, org: Ann, user: uuid.UUID, **values: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
        body = {"title": "Mail outage", "body": "Mail is down.\nWe are on it.", **values}
        response = await self.call("POST", BASE, org, user, json=body)
        assert response.status_code == 201, response.text
        return dict(response.json())

    async def act(
        self,
        org: Ann,
        user: uuid.UUID,
        item: dict[str, Any],
        action: str,
        reason: str | None = None,
        **kw: Any,  # noqa: ANN401 - httpx request options
    ) -> httpx.Response:
        return await self.call(
            "POST",
            f"{BASE}/{item['id']}/{action}",
            org,
            user,
            headers={"If-Match": f'"{item["version"]}"', **kw.pop("headers", {})},
            json=None if reason is None else {"reason": reason},
            **kw,
        )

    async def published(self, org: Ann, **values: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
        """Created by the admin and published right away (four-eyes is off by default)."""
        item = await self.create(org, org.admin, **values)
        response = await self.act(org, org.admin, item, "publish")
        assert response.status_code == 200, response.text
        return dict(response.json())

    async def sql(self, statement: str, *args: Any) -> None:  # noqa: ANN401 - asyncpg args
        """Change a row of this test's own throwaway tenant directly (time travel)."""
        conn = await asyncpg.connect(self.db.admin_url)
        try:
            await conn.execute(statement, *args)
        finally:
            await conn.close()


async def role(world: World, org: Ann, name: str, grants: list[tuple[str, str]]) -> uuid.UUID:
    created = await world.call(
        "POST",
        "/roles",
        org,
        org.admin,
        json={"name": name, "permissions": [{"permission": p, "scope": s} for p, s in grants]},
    )
    assert created.status_code == 201, created.text
    return uuid.UUID(created.json()["id"])


async def unit(world: World, org: Ann, kind: str, name: str, members: list[uuid.UUID]) -> uuid.UUID:
    created = await world.call("POST", f"/organization/{kind}", org, org.admin, json={"name": name})
    assert created.status_code == 201, created.text
    unit_id = uuid.UUID(created.json()["id"])
    for member in members:
        added = await world.call(
            "PUT", f"/organization/{kind}/{unit_id}/members/{member}", org, org.admin
        )
        assert added.status_code in {200, 204}, added.text
    return unit_id


async def make_ann(world: World, name: str) -> Ann:
    tenant = await create_tenant(world.db.migrator_url, name)
    users = await seed_users(
        world.db,
        tenant,
        [
            {"user_type": "technician", "display_name": f"{name} Admin"},
            {"user_type": "technician", "display_name": f"{name} Comms"},
            {"user_type": "technician", "display_name": f"{name} Site Tech"},
            {"user_type": "technician", "display_name": f"{name} Tech"},
            {"user_type": "requester", "display_name": f"{name} Requester"},
            {"user_type": "requester", "display_name": f"{name} Outsider"},
        ],
    )
    admin, comms, site_tech, tech, requester, outsider = users
    await assign_system_role(world.db.admin_url, tenant, admin, "tenant_admin")
    await assign_system_role(world.db.admin_url, tenant, tech, "technician")
    for user in (comms, site_tech, requester, outsider):
        await assign_system_role(world.db.admin_url, tenant, user, "requester")
    org = Ann(tenant, admin, comms, site_tech, tech, requester, outsider)
    comms_role = await role(
        world,
        org,
        "Comms",
        [
            ("announcements.view", "all"),
            ("announcements.manage", "all"),
            ("announcements.publish", "all"),
        ],
    )
    site_role = await role(
        world,
        org,
        "Site announcer",
        [("announcements.view", "site"), ("announcements.manage", "site")],
    )
    for user, role_id in ((comms, comms_role), (site_tech, site_role)):
        assigned = await world.call("PUT", f"/users/{user}/roles/{role_id}", org, admin)
        assert assigned.status_code == 204, assigned.text
    org.s1 = await unit(world, org, "sites", f"{name} S1", [site_tech, requester])
    org.s2 = await unit(world, org, "sites", f"{name} S2", [])
    org.g1 = await unit(world, org, "groups", f"{name} G1", [tech])
    return org


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    url = valkey_url()
    if url is None:
        pytest.skip("Valkey is not configured")
    app: FastAPI = create_app(
        make_settings(
            database_url=migrated_db.app_url,
            valkey_url=url,
            centrifugo_token_secret="announcements-test-secret-" + "x" * 16,
        )
    )
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            w = World(client, migrated_db, app, a=None, b=None)  # type: ignore[arg-type]  # set below
            w.a = await make_ann(w, "Alpha")
            w.b = await make_ann(w, "Beta")
            yield w
            cache = app.state.policy.cache
            prefix = app.state.settings.valkey_key_prefix
            keys = [k async for k in cache.client.scan_iter(match=f"{prefix}*")]
            if keys:
                await cache.client.delete(*keys)


def problem(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


def actions(item: dict[str, Any]) -> dict[str, str | None]:
    """action -> None when allowed, else the reason code."""
    return {a["action"]: None if a["allowed"] else a["reason"] for a in item["actions"]}


async def ids(world: World, org: Ann, user: uuid.UUID, query: str = "") -> set[str]:
    response = await world.call("GET", f"{BASE}{query}", org, user)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


# --- create, read, concurrency, idempotency -------------------------------------------------------


async def test_create_read_and_etag(world: World) -> None:
    a = world.a
    response = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"title": "  Mail outage  ", "body": "Line one\r\nLine two", "severity": "warning"},
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert response.headers["Location"] == f"/api/v1{BASE}/{item['id']}"
    assert response.headers["ETag"] == '"1"'
    assert item["display_id"].startswith("ANN-")
    assert (item["title"], item["body"]) == ("Mail outage", "Line one\nLine two")
    assert (item["status"], item["visibility"], item["owner_id"]) == (
        "draft",
        "hidden",
        str(a.admin),
    )
    assert item["kind"] == "staff"
    # Every action, always in the same order; the ones not possible now say why.
    assert [x["action"] for x in item["actions"]] == ["publish", "unpublish", "archive", "reopen"]
    assert actions(item) == {
        "publish": None,
        "unpublish": "not_from_status",
        "archive": None,
        "reopen": "not_from_status",
    }
    fetched = await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)
    assert fetched.headers["ETag"] == '"1"'
    assert fetched.json()["history_count"] == 1


async def test_edits_need_if_match_and_a_stale_one_says_who_changed_what(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    path = f"{BASE}/{item['id']}"
    missing = await world.call("PATCH", path, a, a.comms, json={"title": "x"})
    assert problem(missing) == (428, "precondition_required")

    first = await world.call(
        "PATCH",
        path,
        a,
        a.comms,
        headers={"If-Match": '"1"'},
        json={"title": "Mail outage (update)", "severity": "critical"},
    )
    assert first.status_code == 200, first.text
    assert (first.json()["version"], first.headers["ETag"]) == (2, '"2"')

    stale = await world.call(
        "PATCH", path, a, a.admin, headers={"If-Match": '"1"'}, json={"body": "mine"}
    )
    assert problem(stale) == (409, "version_conflict")
    params = stale.json()["params"]
    assert (params["expected_version"], params["current_version"]) == (1, 2)
    assert params["changed_by"] == "Alpha Comms"
    assert set(params["changed_fields"].split(",")) == {"title", "severity"}
    assert params["changed_at"]

    # Sending the same values again changes nothing: no new version, no event.
    same = await world.call(
        "PATCH",
        path,
        a,
        a.admin,
        headers={"If-Match": '"2"'},
        json={"title": "Mail outage (update)"},
    )
    assert same.status_code == 200
    assert same.json()["version"] == 2


async def test_create_is_idempotent_with_a_key(world: World) -> None:
    a = world.a
    key = {"Idempotency-Key": str(uuid.uuid4())}
    body = {"title": "Once", "body": "Only once"}
    first = await world.call("POST", BASE, a, a.admin, json=body, headers=key)
    again = await world.call("POST", BASE, a, a.admin, json=body, headers=key)
    assert (first.status_code, again.status_code) == (201, 201)
    assert first.json()["id"] == again.json()["id"]
    assert again.headers["Idempotent-Replayed"] == "true"
    other = await world.call("POST", BASE, a, a.admin, json={**body, "title": "Twice"}, headers=key)
    assert problem(other) == (422, "idempotency_key_reused")
    titles = await world.call("GET", f"{BASE}?title=Once", a, a.admin)
    assert len(titles.json()["items"]) == 1


async def test_owner_candidates_are_people_who_may_manage(world: World) -> None:
    a = world.a
    response = await world.call("GET", f"{BASE}/owner-candidates", a, a.tech)
    assert response.status_code == 200, response.text
    # Admin (all), Comms and Site Tech (custom roles), Tech (built-in, own); never requesters
    # or anyone from tenant B. Sorted by name.
    assert [row["display_name"] for row in response.json()] == [
        "Alpha Admin",
        "Alpha Comms",
        "Alpha Site Tech",
        "Alpha Tech",
    ]
    assert set(response.json()[0]) == {"id", "display_name"}
    found = await world.call("GET", f"{BASE}/owner-candidates?search=site", a, a.tech)
    assert [row["id"] for row in found.json()] == [str(a.site_tech)]
    # LIKE wildcards are literal.
    wild = await world.call("GET", f"{BASE}/owner-candidates?search=%25", a, a.tech)
    assert wild.json() == []
    limited = await world.call("GET", f"{BASE}/owner-candidates?limit=2", a, a.tech)
    assert len(limited.json()) == 2
    # The current owner is always named, first, even outside the search.
    named = await world.call(
        "GET", f"{BASE}/owner-candidates?search=site&include={a.requester}", a, a.tech
    )
    assert [row["display_name"] for row in named.json()] == ["Alpha Requester", "Alpha Site Tech"]
    foreign = await world.call(
        "GET", f"{BASE}/owner-candidates?search=site&include={world.b.admin}", a, a.tech
    )
    assert [row["id"] for row in foreign.json()] == [str(a.site_tech)]
    denied = await world.call("GET", f"{BASE}/owner-candidates", a, a.requester)
    assert problem(denied) == (403, "permission_denied")


async def test_owner_must_be_allowed_to_manage(world: World) -> None:
    a = world.a
    refused = await world.call(
        "POST", BASE, a, a.admin, json={"title": "t", "body": "b", "owner_id": str(a.requester)}
    )
    assert problem(refused) == (422, "validation_failed")
    assert [(e["field"], e["code"]) for e in refused.json()["errors"]] == [
        ("body.owner_id", "owner_not_allowed")
    ]
    item = await world.create(a, a.admin, owner_id=str(a.comms))
    assert item["owner_id"] == str(a.comms)
    path = f"{BASE}/{item['id']}"
    moved = await world.call(
        "PATCH",
        path,
        a,
        a.admin,
        headers={"If-Match": '"1"'},
        json={"owner_id": str(world.b.admin)},
    )
    # Another tenant's user does not exist here at all.
    assert [(e["field"], e["code"]) for e in moved.json()["errors"]] == [
        ("body.owner_id", "unknown_value")
    ]
    edited = await world.call(
        "PATCH", path, a, a.admin, headers={"If-Match": '"1"'}, json={"owner_id": str(a.tech)}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["owner_id"] == str(a.tech)


RANDOM = "random"
VALIDATION_CASES: list[tuple[dict[str, Any], str, str]] = [
    ({"title": "   "}, "body.title", "required"),
    ({"audience": "everyone", "site_ids": ["s1"]}, "body.audience", "not_allowed"),
    (
        {"audience": "sites", "site_ids": ["s1"], "group_ids": ["g1"]},
        "body.group_ids",
        "not_allowed",
    ),
    ({"audience": "sites", "site_ids": [RANDOM]}, "body.site_ids", "unknown_value"),
    ({"audience": "groups", "group_ids": ["b_g1"]}, "body.group_ids", "unknown_value"),
    ({"owner_id": RANDOM}, "body.owner_id", "unknown_value"),
    ({"owner_id": "b_admin"}, "body.owner_id", "unknown_value"),
    ({"audience": "sites", "site_ids": [RANDOM] * 51}, "body.site_ids", "too_many"),
    (
        {"publish_from": "2030-01-02T00:00:00Z", "publish_until": "2030-01-01T00:00:00Z"},
        "body.publish_until",
        "window_end_before_start",
    ),
]


@pytest.mark.parametrize(("values", "field_name", "code"), VALIDATION_CASES)
async def test_validation(world: World, values: dict[str, Any], field_name: str, code: str) -> None:
    a, b = world.a, world.b
    names = {"s1": a.s1, "g1": a.g1, "b_g1": b.g1, "b_admin": b.admin}

    def ref(name: str) -> str:
        return str(uuid.uuid4() if name == RANDOM else names[name])

    body: dict[str, Any] = {"title": "T", "body": "B", **values}
    for key in ("site_ids", "group_ids"):
        if key in body:
            body[key] = [ref(v) for v in body[key]]
    if "owner_id" in body:
        body["owner_id"] = ref(body["owner_id"])
    response = await world.call("POST", BASE, a, a.admin, json=body)
    assert problem(response) == (422, "validation_failed")
    assert (field_name, code) in {(e["field"], e["code"]) for e in response.json()["errors"]}


# --- status actions, reasons, history -------------------------------------------------------------


async def test_transitions_with_reasons_and_history(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    published = await world.act(a, a.admin, item, "publish", headers=CONSOLE)
    assert published.status_code == 200, published.text
    item = published.json()
    assert (item["status"], item["visibility"], item["published_by"]) == (
        "published",
        "live",
        str(a.admin),
    )

    again = await world.act(a, a.admin, item, "publish")
    assert problem(again) == (409, "invalid_transition")
    assert again.json()["params"] == {"from": "published", "action": "publish"}
    reopen = await world.act(a, a.admin, item, "reopen")
    assert problem(reopen) == (409, "invalid_transition")

    too_long = await world.act(a, a.admin, item, "unpublish", reason="x" * 501)
    assert problem(too_long) == (422, "validation_failed")
    unpublished = await world.act(a, a.admin, item, "unpublish", reason="  Wrong date  ")
    assert unpublished.status_code == 200, unpublished.text
    item = unpublished.json()
    archived = await world.act(a, a.admin, item, "archive", reason="Not needed any more")
    item = archived.json()
    assert (item["status"], actions(item)["reopen"]) == ("archived", None)
    item = (await world.act(a, a.admin, item, "reopen")).json()
    assert item["status"] == "draft"

    stale = await world.act(a, a.admin, {**item, "version": 2}, "publish")
    assert problem(stale) == (409, "version_conflict")
    assert stale.json()["params"]["changed_by"] == "Alpha Admin"

    history = await world.call("GET", f"{BASE}/{item['id']}/history?limit=3", a, a.admin)
    page = history.json()
    assert [e["version"] for e in page["items"]] == [5, 4, 3]
    newest, archive, unpublish = page["items"]
    assert (newest["kind"], newest["changes"]) == (
        "status",
        [{"field": "status", "old": "archived", "new": "draft"}],
    )
    assert (archive["reason"], unpublish["reason"]) == ("Not needed any more", "Wrong date")
    assert unpublish["actor_name"] == "Alpha Admin"
    assert unpublish["source"] == "api"
    rest = await world.call(
        "GET", f"{BASE}/{item['id']}/history?cursor={page['next_cursor']}", a, a.admin
    )
    older = rest.json()["items"]
    assert [e["version"] for e in older] == [2, 1]
    assert older[0]["source"] == "ui"  # published from the console
    assert older[1]["kind"] == "created"
    assert {c["field"] for c in older[1]["changes"]} >= {"title", "body", "audience"}
    assert rest.json()["next_cursor"] is None


async def test_publish_rules_are_explained(world: World) -> None:
    a = world.a
    empty = await world.create(a, a.admin, audience="sites")
    assert actions(empty)["publish"] == "audience_empty"
    refused = await world.act(a, a.admin, empty, "publish")
    assert problem(refused) == (409, "cannot_publish")
    assert refused.json()["params"] == {"reason": "audience_empty"}

    soon = datetime.now(UTC) + timedelta(hours=1)
    item = await world.create(a, a.admin, publish_until=soon.isoformat())
    await world.sql(
        "UPDATE announcements SET publish_until = now() - interval '1 minute' WHERE id = $1",
        uuid.UUID(item["id"]),
    )
    ended = await world.act(a, a.admin, item, "publish")
    assert ended.json()["params"] == {"reason": "window_already_ended"}


async def test_four_eyes_off_by_default_and_on_when_set(world: World) -> None:
    a = world.a
    settings = await world.call("GET", f"{BASE}/settings", a, a.admin)
    assert settings.json() == {"require_second_publisher": False, "version": 0}

    # Off: the admin publishes their own announcement.
    own = await world.create(a, a.admin)
    assert actions(own)["publish"] is None
    assert (await world.act(a, a.admin, own, "publish")).status_code == 200

    denied = await world.call(
        "PUT",
        f"{BASE}/settings",
        a,
        a.comms,
        headers={"If-Match": '"0"'},
        json={"require_second_publisher": True},
    )
    assert problem(denied) == (403, "permission_denied")
    turned_on = await world.call(
        "PUT",
        f"{BASE}/settings",
        a,
        a.admin,
        headers={"If-Match": '"0"'},
        json={"require_second_publisher": True},
    )
    assert turned_on.json() == {"require_second_publisher": True, "version": 1}
    stale = await world.call(
        "PUT",
        f"{BASE}/settings",
        a,
        a.admin,
        headers={"If-Match": '"0"'},
        json={"require_second_publisher": False},
    )
    assert problem(stale) == (409, "version_conflict")

    # On: the author may not publish it; someone else with the permission may.
    mine = await world.create(a, a.admin)
    assert actions(mine)["publish"] == "four_eyes"
    refused = await world.act(a, a.admin, mine, "publish")
    assert problem(refused) == (403, "permission_denied")
    assert refused.json()["params"]["reason"] == "four_eyes"
    assert (await world.act(a, a.comms, mine, "publish")).status_code == 200
    # Owning it counts too, not only having written it.
    owned = await world.create(a, a.admin, owner_id=str(a.comms))
    assert problem(await world.act(a, a.comms, owned, "publish")) == (403, "permission_denied")

    off = await world.call(
        "PUT",
        f"{BASE}/settings",
        a,
        a.admin,
        headers={"If-Match": '"1"'},
        json={"require_second_publisher": False},
    )
    assert off.json()["version"] == 2
    again = await world.create(a, a.admin)
    assert (await world.act(a, a.admin, again, "publish")).status_code == 200
    # The other tenant is not affected by any of this.
    other = await world.call("GET", f"{BASE}/settings", world.b, world.b.admin)
    assert other.json() == {"require_second_publisher": False, "version": 0}


async def test_trash_and_restore(world: World) -> None:
    a = world.a
    item = await world.published(a)
    path = f"{BASE}/{item['id']}"
    deleted = await world.call(
        "DELETE", path, a, a.admin, headers={"If-Match": f'"{item["version"]}"'}
    )
    assert deleted.status_code == 204
    assert problem(await world.call("GET", path, a, a.admin)) == (404, "announcement_not_found")
    assert item["id"] not in await ids(world, a, a.admin)
    trash = (await world.call("GET", f"{BASE}/trash", a, a.admin)).json()["items"]
    row = next(r for r in trash if r["id"] == item["id"])
    assert row["deleted_at"]
    assert item["id"] not in {
        i["id"] for i in (await world.call("GET", f"{BASE}/feed", a, a.requester)).json()["items"]
    }
    restored = await world.call(
        "POST", f"{path}/restore", a, a.admin, headers={"If-Match": f'"{row["version"]}"'}
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "published"


# --- who sees what --------------------------------------------------------------------------------


async def test_requesters_see_only_what_is_live_for_them(world: World) -> None:
    a = world.a
    hour = datetime.now(UTC) + timedelta(hours=1)
    live_everyone = await world.published(a, title="Live for all", show_as_banner=True)
    live_s1 = await world.published(a, title="Live for S1", audience="sites", site_ids=[str(a.s1)])
    hidden = {
        "draft": await world.create(a, a.admin, title="Draft"),
        "archived": (
            await world.act(a, a.admin, await world.published(a, title="Old"), "archive")
        ).json(),
        "other_site": await world.published(
            a, title="For S2", audience="sites", site_ids=[str(a.s2)]
        ),
        "other_group": await world.published(
            a, title="For G1", audience="groups", group_ids=[str(a.g1)]
        ),
        "scheduled": await world.published(a, title="Later", publish_from=hour.isoformat()),
        "ended": await world.published(a, title="Ended", publish_until=hour.isoformat()),
        "deleted": await world.published(a, title="Deleted"),
    }
    await world.sql(
        "UPDATE announcements SET publish_until = now() - interval '1 second' WHERE id = $1",
        uuid.UUID(hidden["ended"]["id"]),
    )
    gone = await world.call(
        "DELETE",
        f"{BASE}/{hidden['deleted']['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{hidden["deleted"]["version"]}"'},
    )
    assert gone.status_code == 204

    feed = (await world.call("GET", f"{BASE}/feed", a, a.requester)).json()
    assert {i["id"] for i in feed["items"]} == {live_everyone["id"], live_s1["id"]}
    assert set(feed["items"][0]) == {
        "kind",
        "id",
        "display_id",
        "title",
        "body",
        "severity",
        "show_as_banner",
        "published_at",
        "publish_until",
        "visibility",
        "next_change_in_seconds",
    }
    # The scheduled one is for everyone: its start is when the requester's feed changes next.
    assert 3500 < feed["next_change_in_seconds"] <= 3600

    for name, item in hidden.items():
        response = await world.call("GET", f"{BASE}/{item['id']}", a, a.requester)
        assert problem(response) == (404, "announcement_not_found"), name
    visible = await world.call("GET", f"{BASE}/{live_s1['id']}", a, a.requester)
    assert visible.json()["kind"] == "public"
    assert "owner_id" not in visible.json()

    # Staff lists, history and settings are not for requesters at all.
    assert problem(await world.call("GET", BASE, a, a.requester)) == (403, "permission_denied")
    history = await world.call("GET", f"{BASE}/{live_s1['id']}/history", a, a.requester)
    assert problem(history) == (403, "permission_denied")

    # The outsider (no site) sees only the one for everyone.
    outsider = (await world.call("GET", f"{BASE}/feed", a, a.outsider)).json()
    assert {i["id"] for i in outsider["items"]} == {live_everyone["id"]}
    assert problem(await world.call("GET", f"{BASE}/{live_s1['id']}", a, a.outsider)) == (
        404,
        "announcement_not_found",
    )

    # Realtime: the record channel follows the same rule; the list channels are staff-only.
    async def channel(user: uuid.UUID, item: dict[str, Any]) -> int:
        token = await world.call(
            "POST",
            "/realtime/subscription-token",
            a,
            user,
            json={"channel": f"t:{a.tenant}:announcement:{item['id']}"},
        )
        return token.status_code

    assert await channel(a.requester, live_s1) == 200
    for item in hidden.values():
        assert await channel(a.requester, item) == 403
    assert await channel(a.outsider, live_s1) == 403
    lists = await world.call("GET", "/realtime/lists/announcements", a, a.requester)
    assert lists.json() == {"channels": []}


async def test_site_scoped_technician_sees_and_writes_only_their_sites(world: World) -> None:
    a = world.a
    for_s1 = await world.published(a, title="S1 only", audience="sites", site_ids=[str(a.s1)])
    for_s2 = await world.published(a, title="S2 only", audience="sites", site_ids=[str(a.s2)])
    for_all = await world.create(a, a.admin, title="Everyone draft")

    seen = await ids(world, a, a.site_tech)
    assert for_s1["id"] in seen
    assert {for_s2["id"], for_all["id"]}.isdisjoint(seen)
    assert problem(await world.call("GET", f"{BASE}/{for_s2['id']}", a, a.site_tech)) == (
        404,
        "announcement_not_found",
    )
    staff = await world.call("GET", f"{BASE}/{for_s1['id']}", a, a.site_tech)
    assert staff.json()["kind"] == "staff"
    # No publish permission: the button is there, disabled, with the reason.
    assert actions(staff.json())["unpublish"] is None
    assert actions(staff.json())["archive"] is None

    own = await world.create(a, a.site_tech, audience="sites", site_ids=[str(a.s1)])
    assert own["id"] in await ids(world, a, a.site_tech)
    for values in ({"audience": "everyone"}, {"audience": "sites", "site_ids": [str(a.s2)]}):
        response = await world.call(
            "POST", BASE, a, a.site_tech, json={"title": "T", "body": "B", **values}
        )
        assert problem(response) == (403, "permission_denied"), values
    moved = await world.call(
        "PATCH",
        f"{BASE}/{own['id']}",
        a,
        a.site_tech,
        headers={"If-Match": '"1"'},
        json={"site_ids": [str(a.s2)]},
    )
    assert problem(moved) == (403, "permission_denied")
    unchanged = await world.call("GET", f"{BASE}/{own['id']}", a, a.admin)
    assert unchanged.json()["site_ids"] == [str(a.s1)]
    assert unchanged.json()["version"] == 1  # the refused write was rolled back

    lists = await world.call("GET", "/realtime/lists/announcements", a, a.site_tech)
    assert lists.json() == {"channels": [f"t:{a.tenant}:queue:announcements.site.{a.s1}"]}


async def test_built_in_technician_reads_all_and_writes_own(world: World) -> None:
    a = world.a
    theirs = await world.create(a, a.admin)
    assert theirs["id"] in await ids(world, a, a.tech)
    mine = await world.create(a, a.tech)
    assert actions(mine)["publish"] == "no_permission"
    assert mine["can_manage"] is True
    seen = await world.call("GET", f"{BASE}/{theirs['id']}", a, a.tech)
    assert seen.json()["can_manage"] is False
    assert set(actions(seen.json()).values()) <= {"no_permission", "not_from_status"}
    edit = await world.call(
        "PATCH",
        f"{BASE}/{theirs['id']}",
        a,
        a.tech,
        headers={"If-Match": '"1"'},
        json={"title": "x"},
    )
    assert problem(edit) == (403, "permission_denied")
    assert problem(await world.act(a, a.tech, mine, "publish")) == (403, "permission_denied")


async def test_other_tenants_never_see_anything(world: World) -> None:
    a, b = world.a, world.b
    item = await world.published(a, title="Alpha only")
    assert problem(await world.call("GET", f"{BASE}/{item['id']}", b, b.admin)) == (
        404,
        "announcement_not_found",
    )
    assert item["id"] not in await ids(world, b, b.admin)
    feed = (await world.call("GET", f"{BASE}/feed", b, b.requester)).json()
    assert item["id"] not in {i["id"] for i in feed["items"]}
    edit = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        b,
        b.admin,
        headers={"If-Match": f'"{item["version"]}"'},
        json={"title": "hijack"},
    )
    assert problem(edit) == (404, "announcement_not_found")


async def test_licence_gates_the_whole_module(world: World) -> None:
    no_plan = await create_tenant(world.db.migrator_url, "No plan", edition=None)
    (admin,) = await seed_users(world.db, no_plan, [{"user_type": "technician"}])
    await assign_system_role(world.db.admin_url, no_plan, admin, "tenant_admin")
    org = Ann(no_plan, admin, admin, admin, admin, admin, admin)
    for method, path in (("GET", BASE), ("GET", f"{BASE}/feed"), ("POST", BASE)):
        response = await world.call(method, path, org, admin, json={"title": "T", "body": "B"})
        assert problem(response) == (403, "entitlement_required"), path

    # Lapsed beyond its grace period before its first request (entitlements are cached).
    lapsed = await create_tenant(world.db.migrator_url, "Lapsed")
    (admin,) = await seed_users(world.db, lapsed, [{"user_type": "technician"}])
    await assign_system_role(world.db.admin_url, lapsed, admin, "tenant_admin")
    await set_term(
        world.db, lapsed, expires_at=datetime.now(UTC) - timedelta(days=60), grace_days=14
    )
    org = Ann(lapsed, admin, admin, admin, admin, admin, admin)
    assert (await world.call("GET", BASE, org, admin)).status_code == 200
    assert (await world.call("GET", f"{BASE}/feed", org, admin)).status_code == 200
    write = await world.call("POST", BASE, org, admin, json={"title": "T", "body": "B"})
    assert problem(write) == (403, "read_only_mode")


# --- lists ----------------------------------------------------------------------------------------


async def test_list_filters_sort_and_next_change(world: World) -> None:
    a = world.a
    soon = datetime.now(UTC) + timedelta(minutes=10)
    crit = await world.published(a, title="ZZ critical", severity="critical")
    later = await world.published(a, title="AA later", publish_from=soon.isoformat())
    await world.create(a, a.admin, title="MM draft", severity="critical")

    simple = await world.call("GET", f"{BASE}?status=published&severity=critical", a, a.admin)
    assert {r["id"] for r in simple.json()["items"]} >= {crit["id"]}
    assert all(
        (r["status"], r["severity"]) == ("published", "critical") for r in simple.json()["items"]
    )
    dsl = {"and": [{"field": "title", "op": "contains", "value": "later"}]}
    found = await world.call("GET", BASE, a, a.admin, params={"filter": json.dumps(dsl)})
    rows = found.json()["items"]
    assert [r["id"] for r in rows] == [later["id"]]
    assert rows[0]["visibility"] == "scheduled"
    assert 590 < found.json()["next_change_in_seconds"] <= 600
    by_title = await world.call("GET", f"{BASE}?sort=title&limit=2", a, a.admin)
    titles = [r["title"] for r in by_title.json()["items"]]
    assert titles == sorted(titles)
    bad = await world.call("GET", f"{BASE}?status=nonsense", a, a.admin)
    assert problem(bad) == (422, "invalid_filter")


async def test_today_follows_the_users_time_zone(world: World) -> None:
    """ "Created today" is the user's today (X-Time-Zone), not the server's (follow-up c)."""
    a = world.a
    item = await world.create(a, a.admin, title="Zone check")
    # An instant inside today in Karachi (+05:00) but not inside today in Honolulu (-10:00). When
    # both are on the same date that is just after Karachi's midnight (Honolulu's day starts 15
    # hours later); once Karachi is a date ahead, it is just after Honolulu's day ends.
    now = datetime.now(UTC)
    karachi_day = datetime.combine(now.astimezone(KARACHI).date(), day_start(), KARACHI)
    honolulu_day = datetime.combine(now.astimezone(HONOLULU).date(), day_start(), HONOLULU)
    minute = timedelta(minutes=1)
    at = (
        karachi_day + minute
        if karachi_day < honolulu_day
        else honolulu_day + timedelta(days=1) + minute
    )
    await world.sql(
        "UPDATE announcements SET created_at = $2 WHERE id = $1", uuid.UUID(item["id"]), at
    )
    dsl = json.dumps({"field": "created_at", "op": "today"})
    karachi = await world.call(
        "GET", BASE, a, a.admin, params={"filter": dsl}, headers={"X-Time-Zone": "Asia/Karachi"}
    )
    assert item["id"] in {r["id"] for r in karachi.json()["items"]}
    honolulu = await world.call(
        "GET", BASE, a, a.admin, params={"filter": dsl}, headers={"X-Time-Zone": "Pacific/Honolulu"}
    )
    assert item["id"] not in {r["id"] for r in honolulu.json()["items"]}
    unknown = await world.call(
        "GET", BASE, a, a.admin, params={"filter": dsl}, headers={"X-Time-Zone": "Mars/Base"}
    )
    assert unknown.status_code == 200  # an unknown zone falls back to UTC


# --- realtime routing -----------------------------------------------------------------------------


async def envelopes(world: World, item_id: str) -> list[EventEnvelope]:
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        rows = await conn.fetch(
            "SELECT envelope FROM outbox_events WHERE aggregate_id = $1 ORDER BY id", item_id
        )
    finally:
        await conn.close()
    return [EventEnvelope.model_validate(json.loads(r["envelope"])) for r in rows]


async def test_fan_out_reaches_staff_lists_and_hints_banners_without_ids(
    world: World, app_db: Database
) -> None:
    a = world.a
    item = await world.create(a, a.admin, audience="sites", site_ids=[str(a.s1)])
    edited = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        headers={"If-Match": '"1"'},
        json={"title": "Draft edit"},
    )
    await world.act(a, a.admin, edited.json(), "publish")
    created, draft_edit, publish = await envelopes(world, item["id"])
    assert [e.event_type for e in (created, draft_edit, publish)] == [
        "announcements.announcement.created",
        "announcements.announcement.updated",
        "announcements.announcement.status_changed",
    ]
    assert "title" not in json.dumps(draft_edit.payload | {"changed_fields": []})

    async def route(envelope: EventEnvelope) -> dict[str, list[dict[str, Any]]]:
        found: dict[str, list[dict[str, Any]]] = {}
        async with app_db.tenant_session(TenantContext(a.tenant)) as session:
            for spec in ROUTES:
                if envelope.event_type in spec.event_types:
                    effects = await spec.route(envelope, session)
                    for p in effects.publications:
                        found.setdefault(p.channel.name, []).append(p.data())
        return found

    broadcast = f"t:{a.tenant}:broadcast"
    edit_channels = await route(draft_edit)
    # Staff hear about the draft edit (record, list, the S1 list, the owner); requesters do not.
    assert {
        f"t:{a.tenant}:announcement:{item['id']}",
        f"t:{a.tenant}:queue:announcements",
        f"t:{a.tenant}:queue:announcements.site.{a.s1}",
        f"t:{a.tenant}:user:{a.admin}",
    } <= set(edit_channels)
    assert broadcast not in edit_channels
    assert edit_channels[f"t:{a.tenant}:announcement:{item['id']}"][0]["fields"] == ["title"]

    publish_channels = await route(publish)
    assert publish_channels[broadcast] == [{"type": "announcements.feed_changed", "ids": []}]
    assert publish_channels[f"t:{a.tenant}:announcement:{item['id']}"][0]["fields"] == ["status"]


# --- performance ----------------------------------------------------------------------------------

ROWS = 10_000
RUNS = 40
SEED = """
INSERT INTO announcements (id, tenant_id, display_id, title, body, severity, status, audience,
                           owner_id, created_by, updated_by, show_as_banner, published_at,
                           created_at, updated_at)
SELECT gen_random_uuid(), $1, 'ANN-' || n, 'Announcement ' || lpad(n::text, 5, '0'),
       'Body of announcement ' || n,
       (ARRAY['info', 'warning', 'critical'])[1 + (n / 3) % 3],
       (ARRAY['draft', 'published', 'archived'])[1 + n % 3],
       CASE WHEN n % 5 = 0 THEN 'sites' ELSE 'everyone' END,
       $2, $2, $2, n % 2 = 0,
       CASE WHEN n % 3 = 1 THEN now() - (n || ' minutes')::interval END,
       now() - (n || ' minutes')::interval, now() - (n || ' minutes')::interval
FROM generate_series(1, $3) AS n
"""
SEED_SITES = """
INSERT INTO announcement_sites (tenant_id, announcement_id, site_id)
SELECT tenant_id, id, $2 FROM announcements WHERE tenant_id = $1 AND audience = 'sites'
"""


async def test_ten_thousand_announcements_list_fast(world: World) -> None:
    """Filtered list p95 < 100 ms on 10,000 rows (all-scope admin and site-scoped technician)."""
    org = await make_ann(world, "Perf")
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        await conn.execute(SEED, org.tenant, org.admin, ROWS)
        await conn.execute(SEED_SITES, org.tenant, org.s1)
        await conn.execute("ANALYZE announcements; ANALYZE announcement_sites")
    finally:
        await conn.close()

    queries = {
        "admin_published_critical": (org.admin, "?status=published&severity=critical&limit=50"),
        "admin_title_contains": (
            org.admin,
            "?"
            + str(
                httpx.QueryParams(
                    {"filter": json.dumps({"field": "title", "op": "contains", "value": "0042"})}
                )
            ),
        ),
        "admin_sorted_by_title": (org.admin, "?sort=title&limit=50"),
        "site_tech_scoped_published": (org.site_tech, "?status=published&limit=50"),
        "requester_feed": (org.requester, "/feed"),
    }
    report: dict[str, dict[str, float]] = {}
    for name, (user, suffix) in queries.items():
        path = f"{BASE}{suffix}"
        timings = []
        for _ in range(RUNS):
            started = time.perf_counter()
            response = await world.call("GET", path, org, user)
            timings.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200, response.text
        timings.sort()
        p95 = timings[int(len(timings) * 0.95) - 1]
        report[name] = {
            "p50_ms": round(statistics.median(timings), 1),
            "p95_ms": round(p95, 1),
            "max_ms": round(timings[-1], 1),
            "items": len(response.json()["items"]),
        }
        print(f"\n[perf] announcements_10k {name}: rows={ROWS}, {report[name]}")  # noqa: T201
    assert all(r["items"] > 0 for r in report.values()), report  # real pages, not empty ones
    assert all(r["p95_ms"] < 100 for r in report.values()), report
