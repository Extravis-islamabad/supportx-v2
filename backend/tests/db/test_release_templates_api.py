"""Release templates, stage rules, type defaults and copies over HTTP (WP-058a s2).

REQ-REL-003, -007, -009, -011..013; ADR-041. Real PostgreSQL with RLS. A template decides the
path (no separate workflow picker); its stage rules are checked on save and read-only fields are
refused while the release is in that stage, through the API as well; a release type may set a
default template and risk; a copy starts again in the first stage with no dates.
"""

import uuid
from typing import Any

import httpx

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, problem
from tests.db.test_releases_api import REL, a_release, details, move, moved, panel, rail

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def templates(world: World, org: Org) -> dict[str, dict[str, Any]]:
    response = await world.call("GET", f"{REL}/templates", org, org.admin)
    assert response.status_code == 200, response.text
    return {t["code"] or t["id"]: t for t in response.json()}


async def patch_template(
    world: World,
    org: Org,
    template: dict[str, Any],
    **body: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "PATCH",
        f"{REL}/templates/{template['id']}",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{template["version"]}"', **CONSOLE},
    )


async def release_from(world: World, org: Org, template: dict[str, Any]) -> dict[str, Any]:
    made = await world.call(
        "POST",
        REL,
        org,
        org.admin,
        json={
            "subject": "Hotfix 4.2.1",
            "requester_id": str(org.requester),
            "template_id": template["id"],
        },
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


def field_codes(response: httpx.Response) -> set[tuple[str, str]]:
    return {(e["field"].removeprefix("body."), e["code"]) for e in response.json()["errors"]}


async def test_req_rel_011_012_the_emergency_template_takes_the_short_path(world: World) -> None:
    a = world.a
    seeded = await templates(world, a)
    assert (seeded["standard"]["stage_path"], seeded["standard"]["is_default"]) == ("default", True)
    assert seeded["emergency"]["stage_path"] == "emergency"
    item = await release_from(world, a, seeded["emergency"])
    assert (item["stage"], item["stage_path"]) == ("submission", "emergency")
    shown = rail(await panel(world, a, item))
    assert "planning" not in shown  # REQ-REL-011 AC1
    assert "training" not in shown
    accepted = await moved(world, a, item, "submission_accepted")
    assert accepted["stage"] == "build"  # REQ-REL-012 AC1: straight to build
    listed = await world.call("GET", f"{REL}?limit=5", a, a.admin)
    row = next(r for r in listed.json()["items"] if r["id"] == item["id"])
    assert row["stage_path"] == "emergency"  # the flag lists show (REQ-REL-012 AC3)


async def test_req_rel_013_stage_rules_are_checked_on_save(world: World) -> None:
    a = world.a
    standard = (await templates(world, a))["standard"]
    bad = await patch_template(
        world,
        a,
        standard,
        stage_rules={
            "nowhere": {"impact": {"read_only": True}},
            "testing": {
                "made_up": {"shown": False},
                "build_ref": {"shown": False, "required": True},
            },
        },
    )
    assert bad.status_code == 422, bad.text
    assert field_codes(bad) == {
        ("stage_rules.nowhere", "unknown_stage"),
        ("stage_rules.testing.made_up", "not_a_field"),
        ("stage_rules.testing.build_ref", "hidden_cannot_be_required"),
    }
    off_path = await patch_template(world, a, standard, stage_path="no_such_path")
    assert field_codes(off_path) == {("stage_path", "invalid_choice")}
    # Incidents have no stages: a template of theirs takes neither setting.
    incident_templates = await world.call("GET", f"{BASE}/templates", a, a.admin)
    incident = incident_templates.json()[0]
    refused = await world.call(
        "PATCH",
        f"{BASE}/templates/{incident['id']}",
        a,
        a.admin,
        json={"stage_path": "default"},
        headers={"If-Match": f'"{incident["version"]}"', **CONSOLE},
    )
    assert field_codes(refused) == {("stage_path", "not_allowed")}


async def test_req_rel_013_ac1_read_only_in_a_stage_through_the_api_too(world: World) -> None:
    a = world.a
    standard = (await templates(world, a))["standard"]
    saved = await patch_template(
        world,
        a,
        standard,
        stage_rules={
            "submission": {"impact": {"read_only": True}, "release_version": {"read_only": True}}
        },
    )
    assert saved.status_code == 200, saved.text
    shown_rules = saved.json()["stage_rules"]["submission"]
    assert {n: r["read_only"] for n, r in shown_rules.items()} == {
        "impact": True,
        "release_version": True,
    }
    item = await a_release(world, a)
    locked = await world.call(
        "PATCH",
        f"{REL}/{item['id']}",
        a,
        a.admin,
        json={"impact": "organisation"},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert field_codes(locked) == {("impact", "read_only_in_stage")}
    no_version = await details(world, a, item, release_version="5.0.0")
    assert field_codes(no_version) == {("release_version", "read_only_in_stage")}
    allowed = await details(world, a, item, build_ref="b-1")  # not locked
    assert allowed.status_code == 200, allowed.text
    planning = await moved(
        world, a, {**item, "version": allowed.json()["version"]}, "submission_accepted"
    )
    unlocked = await details(world, a, planning, release_version="5.0.0")
    assert unlocked.status_code == 200, unlocked.text  # another stage: editable again


async def test_req_rel_003_a_type_sets_its_default_template_and_risk(world: World) -> None:
    a = world.a
    emergency = (await templates(world, a))["emergency"]
    settings = (await world.call("GET", f"{REL}/settings", a, a.admin)).json()
    assert [v["code"] for v in settings["own_lists"]["release_type"]] == [
        "major",
        "minor",
        "emergency",
        "maintenance",
    ]

    async def set_attributes(attributes: dict[str, Any], version: int) -> httpx.Response:
        return await world.call(
            "PATCH",
            f"{REL}/settings/lists/release_type/values/emergency",
            a,
            a.admin,
            json={"attributes": attributes},
            headers={"If-Match": f'"{version}"', **CONSOLE},
        )

    unknown = await set_attributes({"colourful": True}, settings["version"])
    assert field_codes(unknown) == {("attributes", "not_allowed")}
    saved = await set_attributes(
        {"default_template_id": emergency["id"], "default_risk": "high"},
        settings["version"],
    )
    assert saved.status_code == 200, saved.text
    value = next(v for v in saved.json()["own_lists"]["release_type"] if v["code"] == "emergency")
    assert value["attributes"] == {"default_template_id": emergency["id"], "default_risk": "high"}
    item = await a_release(world, a)
    typed = await details(world, a, item, release_type="emergency")
    assert typed.status_code == 200, typed.text  # no risk reason asked: the type set it
    assert typed.json()["risk"] == "high"


async def test_req_rel_009_a_copy_starts_again_without_dates(world: World) -> None:
    a = world.a
    item = await a_release(world, a)
    filled = await details(
        world,
        a,
        item,
        release_type="minor",
        release_version="4.3.0",
        scheduled_start="2026-11-10T08:00:00Z",
        scheduled_end="2026-11-10T09:00:00Z",
    )
    planning = await moved(
        world, a, {**item, "version": filled.json()["version"]}, "submission_accepted"
    )
    key = str(uuid.uuid4())

    async def copy() -> httpx.Response:
        return await world.call(
            "POST",
            f"{REL}/{planning['id']}/copy",
            a,
            a.admin,
            headers={"Idempotency-Key": key, **CONSOLE},
        )

    first = await copy()
    assert first.status_code == 201, first.text
    again = await copy()
    assert again.json()["id"] == first.json()["id"]  # one copy for one key
    made = first.json()
    assert made["id"] != item["id"]
    assert (made["stage"], made["status"]) == ("submission", "submission_requested")  # AC1
    copied = (await world.call("GET", f"{REL}/{made['id']}/details", a, a.admin)).json()
    assert (copied["release_type"], copied["release_version"]) == ("minor", "4.3.0")
    assert copied["scheduled_start"] is None
    assert copied["scheduled_end"] is None
    # A technician without releases.create may not copy.
    refused = await world.call(
        "POST",
        f"{REL}/{planning['id']}/copy",
        a,
        a.tech_a,
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert problem(refused)[0] == 403
    # Moves still need If-Match on the copy like any release.
    assert (await move(world, a, made, "submission_accepted")).status_code == 200
