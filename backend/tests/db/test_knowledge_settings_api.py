"""Knowledge settings page over HTTP (WP-033 session 3b, D-120; REQ-KB-090).

Prefix and next number on the article counter, custom article types, and their live and audit
trail. The incident world of test_incidents_api.py: org A has an admin (every permission) and
technicians; org B is there for isolation.
"""

import uuid
from typing import Any

import pytest

from tests.db import test_incidents_api
from tests.db.test_incidents_api import Org, World, field_codes, problem
from tests.db.test_knowledge_api import _article, _match, _new, _topic

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

SETTINGS = "/knowledge/settings"
TYPES = "/knowledge/types"


async def _settings(world: World, org: Org) -> dict[str, Any]:
    response = await world.call("GET", SETTINGS, org, org.admin)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _patch(world: World, org: Org, user: uuid.UUID, **values: Any) -> Any:  # noqa: ANN401 - JSON and httpx response
    current = await _settings(world, org)
    return await world.call(
        "PATCH", SETTINGS, org, user, json=values, headers=_match(current["version"])
    )


async def test_d120_a_new_prefix_continues_the_numbering(world: World) -> None:
    a = world.a
    topic = await _topic(world, a)
    first = await _article(world, a, a.admin, topic)
    second = await _article(world, a, a.admin, topic)
    assert first["display_id"] == "KB-1"
    assert second["display_id"] == "KB-2"
    assert (await _settings(world, a))["next_number"] == 3

    changed = await _patch(world, a, a.admin, prefix="art")
    assert changed.status_code == 200, changed.text
    assert changed.json()["prefix"] == "ART"  # stored in capitals
    third = await _article(world, a, a.admin, topic)
    assert third["display_id"] == "ART-3"  # continues, never restarts at 1

    # Existing articles keep their IDs.
    kept = await world.call("GET", f"/knowledge/articles/{first['id']}", a, a.admin)
    assert kept.json()["display_id"] == "KB-1"

    back = await _patch(world, a, a.admin, prefix="KB")
    assert back.status_code == 200, back.text
    assert (await _article(world, a, a.admin, topic))["display_id"] == "KB-4"  # no clash

    # The other tenant's numbering is its own.
    other = await _article(world, world.b, world.b.admin, await _topic(world, world.b))
    assert other["display_id"] == "KB-1"


async def test_d120_next_number_goes_forward_only_and_problems_name_their_field(
    world: World,
) -> None:
    a = world.a
    topic = await _topic(world, a)
    await _article(world, a, a.admin, topic)
    bad = await _patch(world, a, a.admin, prefix="k1", next_number=1)
    assert bad.status_code == 422, bad.text
    assert field_codes(bad) == {"prefix": "invalid_prefix", "next_number": "number_already_used"}
    assert (await _settings(world, a))["prefix"] == "KB"  # all or nothing

    jumped = await _patch(world, a, a.admin, next_number=1000)
    assert jumped.status_code == 200, jumped.text
    assert jumped.json()["next_number"] == 1000
    assert (await _article(world, a, a.admin, topic))["display_id"] == "KB-1000"
    assert problem(await _patch(world, a, a.admin, next_number=500))[0] == 422

    # Only settings managers; each change is in the history and the audit log.
    assert problem(await _patch(world, a, a.tech_a, next_number=2000))[0] == 403
    history = await world.sql(
        "SELECT field FROM field_changes WHERE record_type = 'kb_settings' AND tenant_id = $1",
        a.tenant,
    )
    assert "next_number" in {r["field"] for r in history}
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE action = 'knowledge.settings_changed'"
        " AND tenant_id = $1",
        a.tenant,
    )
    assert audit[0]["n"] >= 1


async def _types(world: World, org: Org) -> dict[str, dict[str, Any]]:
    response = await world.call("GET", TYPES, org, org.admin)
    assert response.status_code == 200, response.text
    return {t["code"]: t for t in response.json()}


async def test_d120_custom_types_retire_and_keep_their_articles(world: World) -> None:
    a = world.a
    missing = await world.call(
        "POST",
        TYPES,
        a,
        a.admin,
        json={"names": {"en": "Runbook"}, "review_months": 6},
        headers=_new(),
    )
    assert missing.status_code == 422, missing.text
    assert field_codes(missing) == {"names.ar": "required"}
    assert (
        problem(
            await world.call(
                "POST",
                TYPES,
                a,
                a.tech_a,
                json={"names": {"en": "R", "ar": "د"}, "review_months": 6},
                headers=_new(),
            )
        )[0]
        == 403
    )

    created = await world.call(
        "POST",
        TYPES,
        a,
        a.admin,
        json={"names": {"en": " Runbook ", "ar": "دليل التشغيل"}, "review_months": 6},
        headers=_new(),
    )
    assert created.status_code == 201, created.text
    runbook = created.json()
    assert runbook["names"] == {"en": "Runbook", "ar": "دليل التشغيل"}
    assert runbook["builtin"] is False
    assert runbook["code"].startswith("custom_")

    topic = await _topic(world, a)
    article = await _article(world, a, a.admin, topic, type_code=runbook["code"])
    retired = await world.call(
        "PATCH",
        f"{TYPES}/{runbook['code']}",
        a,
        a.admin,
        json={"retired": True},
        headers=_match(runbook["version"]),
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["retired"] is True
    stale = await world.call(
        "PATCH",
        f"{TYPES}/{runbook['code']}",
        a,
        a.admin,
        json={"review_months": 3},
        headers=_match(runbook["version"]),
    )
    assert problem(stale) == (409, "version_conflict")
    # A retired type is not offered for a new article; the article that has it keeps it.
    refused = await world.call(
        "POST",
        "/knowledge/articles",
        a,
        a.admin,
        json={"topic_id": topic["id"], "type_code": runbook["code"], "title": "New"},
        headers=_new(),
    )
    assert refused.status_code in (404, 422), refused.text
    kept = await world.call("GET", f"/knowledge/articles/{article['id']}", a, a.admin)
    assert kept.json()["type_code"] == runbook["code"]

    # Org B never sees org A's type.
    assert runbook["code"] not in await _types(world, world.b)


async def test_d120_a_builtin_type_keeps_its_names(world: World) -> None:
    a = world.a
    how_to = (await _types(world, a))["how_to"]
    renamed = await world.call(
        "PATCH",
        f"{TYPES}/how_to",
        a,
        a.admin,
        json={"names": {"en": "Guide", "ar": "دليل"}},
        headers=_match(how_to["version"]),
    )
    assert field_codes(renamed) == {"names": "builtin_type_names"}
    longer = await world.call(
        "PATCH",
        f"{TYPES}/how_to",
        a,
        a.admin,
        json={"review_months": 24},
        headers=_match(how_to["version"]),
    )
    assert longer.status_code == 200, longer.text
    assert longer.json()["review_months"] == 24
    assert longer.json()["version"] == how_to["version"] + 1
    audit = await world.sql(
        "SELECT outcome FROM audit_entries WHERE action = 'knowledge.type_changed'"
        " AND tenant_id = $1",
        a.tenant,
    )
    # The refused rename is in the audit log too, as a failure.
    assert sorted(r["outcome"] for r in audit) == ["done", "failed"]
    events = await world.sql(
        "SELECT id FROM outbox_events WHERE event_type = 'knowledge.type.saved' AND tenant_id = $1",
        a.tenant,
    )
    assert len(events) == 1
