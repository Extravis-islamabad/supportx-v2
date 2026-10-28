"""A stale save says who saved it last, when, and which fields (QA WP-029 BUG-05).

Every editor shows the same conflict dialog (CLAUDE.md rule g): the 409 `version_conflict` names
the person and time of the save the user missed (`changed_by`, `changed_at`), plus the fields
(`changed_fields`) where the record keeps field history. Real PostgreSQL, the incidents test world.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio

from tests.db.test_automation_api import add_rule, set_
from tests.db.test_incidents_api import Org, World, incidents_world
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    async with incidents_world(migrated_db) as built:
        yield built


async def saved_twice(
    world: World,
    org: Org,
    verb: str,
    path: str,
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    version: int,
) -> dict[str, Any]:
    """Save at `version`, then save again at that same (now stale) version."""
    ok = await world.call(
        verb, path, org, org.admin, json=first, headers={"If-Match": f'"{version}"'}
    )
    assert ok.status_code == 200, ok.text
    stale = await world.call(
        verb, path, org, org.admin, json=second, headers={"If-Match": f'"{version}"'}
    )
    assert stale.status_code == 409, stale.text
    body: dict[str, Any] = stale.json()
    assert body["code"] == "version_conflict"
    return dict(body["params"])


def assert_who_and_when(params: dict[str, Any]) -> None:
    assert params["changed_by"] == "Alpha Admin"
    assert datetime.fromisoformat(params["changed_at"]).tzinfo is not None
    assert isinstance(params["expected_version"], int)
    assert params["current_version"] == params["expected_version"] + 1


async def test_bug_05_a_stale_business_rule_names_who_and_when(world: World) -> None:
    org = world.a
    rule = await add_rule(world, org, name="Email is P2", actions=[set_("tags", ["x"])])
    params = await saved_twice(
        world,
        org,
        "PATCH",
        f"/automation/rules/{rule['id']}",
        {"name": "One"},
        {"name": "Two"},
        version=rule["version"],
    )
    assert_who_and_when(params)


async def test_bug_05_stale_routing_settings_name_who_and_when(world: World) -> None:
    org = world.a
    path = "/automation/routing-settings?record_type=incident"
    read = await world.call("GET", path, org, org.admin)
    params = await saved_twice(
        world,
        org,
        "PUT",
        path,
        {"fallback_group_id": str(org.ga), "use_category_group": True},
        {"fallback_group_id": None, "use_category_group": False},
        version=int(read.headers["ETag"].strip('"')),
    )
    assert_who_and_when(params)


async def test_bug_05_stale_transition_settings_name_who_and_when(world: World) -> None:
    org = world.a
    path = "/automation/transitions/close?record_type=incident"
    params = await saved_twice(
        world, org, "PUT", path, {"roles": ["tenant_admin"]}, {"roles": ["technician"]}, version=0
    )
    assert_who_and_when(params)


async def test_bug_05_a_record_with_field_history_also_names_the_fields(world: World) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    path = f"/incidents/{item['id']}"
    params = await saved_twice(
        world,
        org,
        "PATCH",
        path,
        {"subject": "Mail down"},
        {"tags": ["x"]},
        version=item["version"],
    )
    assert_who_and_when(params)
    assert params["changed_fields"] == "subject"


async def test_bug_05_shared_repository_conflicts_name_who_and_when(world: World) -> None:
    """Records saved through the shared repository (here a routing rule) get it without code."""
    org = world.a
    created = await world.call(
        "POST",
        "/automation/routing",
        org,
        org.admin,
        json={"record_type": "incident", "name": "Net", "group_id": str(org.ga)},
    )
    assert created.status_code == 201, created.text
    path = f"/automation/routing/{created.json()['id']}"
    params = await saved_twice(
        world,
        org,
        "PATCH",
        path,
        {"name": "One"},
        {"name": "Two"},
        version=created.json()["version"],
    )
    assert_who_and_when(params)
