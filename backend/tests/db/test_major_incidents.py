"""Major incidents (WP-046b S4; REQ-INC-141, D-043 Essentials).

Lane B's conditions: declaring and ending need `incidents.declare_major` and a reason, both
audited with the reason in the entry's personal part, never in field history values; the team is
told through the one engine (access checked, nothing granted); the event and realtime carry IDs
and the flag only; the settings need the admin right, If-Match, a live incident template, and an
audit entry with before and after.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, world  # noqa: F401 - fixture
from tests.db.test_notifications_api import MAIL, run_engine

REASON = "Payroll is down for the whole Riyadh office"


async def _declare(
    world: World,  # noqa: F811
    org: Org,
    user: uuid.UUID,
    item: dict[str, Any],
    reason: str = REASON,
    *,
    end: bool = False,
) -> Any:  # noqa: ANN401 - an httpx response
    fresh = await world.fresh(org, item)
    return await world.call(
        "POST",
        f"{BASE}/{item['id']}/major" + ("/end" if end else ""),
        org,
        user,
        json={"reason": reason},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )


async def _settings(world: World, org: Org, **values: Any) -> Any:  # noqa: F811, ANN401
    shown = await world.call("GET", f"{BASE}/settings/major", org, org.admin)
    assert shown.status_code == 200, shown.text
    return await world.call(
        "PUT",
        f"{BASE}/settings/major",
        org,
        org.admin,
        json=values,
        headers={"If-Match": f'"{shown.json()["settings_version"]}"', **CONSOLE},
    )


async def test_declaring_needs_the_right_and_a_reason_and_is_audited(world: World) -> None:  # noqa: F811
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    refused = await _declare(world, a, a.tech_a, item)  # a technician: not by default
    assert refused.status_code == 403, refused.text
    blank = await _declare(world, a, a.admin, item, reason="  ")
    assert blank.status_code == 422, blank.text
    done = await _declare(world, a, a.admin, item)
    assert done.status_code == 200, done.text
    assert done.json()["major"] is True
    shown = await world.fresh(a, item)
    assert shown["major"] is True
    assert shown["major_reason"] == REASON
    again = await _declare(world, a, a.admin, item)
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "already_major"
    # History names the fields, never the reason's text (lane B).
    entries = await world.history(a, item)
    major = [c for e in entries for c in e["changes"] if c["field"].startswith("major")]
    assert {c["field"] for c in major} >= {"major", "major_reason"}
    assert REASON not in str(entries)
    (audit,) = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'incident.major_declared' AND object_id = $2",
        a.tenant,
        item["id"],
    )
    assert REASON not in str(audit["details"])  # in the entry's personal part only
    # Ending it: the same right and a reason; the declaration stays in history.
    ended = await _declare(world, a, a.admin, item, "Payroll is back", end=True)
    assert ended.status_code == 200, ended.text
    assert ended.json()["major"] is False
    twice = await _declare(world, a, a.admin, item, "Again", end=True)
    assert twice.json()["code"] == "not_major"
    ends = await world.sql(
        "SELECT 1 FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'incident.major_ended' AND object_id = $2",
        a.tenant,
        item["id"],
    )
    assert len(ends) == 1
    # The event carries IDs and the flag only.
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'work_items.major.changed'",
        a.tenant,
    )
    assert len(events) == 2
    assert all(REASON not in str(e["envelope"]) for e in events)


async def test_the_team_is_told_through_the_engine_and_the_template_applies(world: World) -> None:  # noqa: F811
    a = world.a
    templates = await world.call("GET", f"{BASE}/templates", a, a.admin)
    template = templates.json()[0]["id"]
    unknown = await _settings(world, a, group_id=str(uuid.uuid4()))
    assert unknown.status_code == 422, unknown.text
    bad_template = await _settings(world, a, template_id=str(uuid.uuid4()))
    assert bad_template.status_code == 422, bad_template.text
    set_ = await _settings(
        world, a, group_id=str(a.ga), user_ids=[str(a.lead)], template_id=template
    )
    assert set_.status_code == 200, set_.text
    assert set_.json()["user_ids"] == [str(a.lead)]
    # The refused attempts are audited as refused; the saved one names the IDs, before and after.
    audits = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'incident.major_settings_changed'",
        a.tenant,
    )
    assert any(str(a.ga) in str(row["details"]) for row in audits)
    item = await world.create(a, a.admin, group_id=str(a.ga))
    done = await _declare(world, a, a.admin, item)
    assert done.status_code == 200, done.text
    assert done.json()["template_id"] == template
    await run_engine(world, a, settings=MAIL)
    told = await world.sql(
        "SELECT user_id, text_body FROM notification_deliveries WHERE tenant_id = $1"
        " AND record_id = $2 AND event_code = 'incident.major_declared'",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    people = {r["user_id"] for r in told}
    assert {a.tech_a, a.tech_c, a.lead} <= people  # GA's members and the named person
    assert a.tech_b not in people  # not on the team
    assert all(REASON not in (r["text_body"] or "") for r in told)
    # Declaring grants nobody anything: no follower rows were added.
    follows = await world.sql(
        "SELECT 1 FROM work_item_followers WHERE tenant_id = $1 AND work_item_id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    assert follows == []


async def test_the_marker_shows_in_lists_and_filters_them(world: World) -> None:  # noqa: F811
    a = world.a
    major = await world.create(a, a.admin, group_id=str(a.ga))
    other = await world.create(a, a.admin, group_id=str(a.ga))
    assert (await _declare(world, a, a.admin, major)).status_code == 200
    listed = await world.call(
        "GET", f"{BASE}?filter=" + '{"field":"major","op":"eq","value":true}', a, a.admin
    )
    assert listed.status_code == 200, listed.text
    ids = {i["id"] for i in listed.json()["items"]}
    assert major["id"] in ids
    assert other["id"] not in ids
    majors = await world.call("GET", f"{BASE}/majors", a, a.admin)
    assert [m["id"] for m in majors.json()] == [major["id"]]
    # Another tenant sees none of it.
    theirs = await world.call("GET", f"{BASE}/majors", world.b, world.b.admin)
    assert theirs.json() == []


async def test_similar_incidents_are_attached_as_children_with_a_result_each(
    world: World,  # noqa: F811
) -> None:
    """REQ-INC-141 AC2: one action attaches many; each is checked again as the person (lane B)."""
    from app.modules.work_items.service.bulk import run_bulk_jobs  # noqa: PLC0415

    a = world.a
    parent = await world.create(a, a.admin, group_id=str(a.ga))
    mine = [await world.create(a, a.admin, group_id=str(a.ga)) for _ in range(2)]
    theirs = await world.create(a, a.admin, group_id=str(a.gb))  # outside tech_a's scope
    not_major = await world.call(
        "POST",
        f"{BASE}/{parent['id']}/children/attach",
        a,
        a.tech_a,
        json={"child_ids": [mine[0]["id"]]},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert not_major.status_code == 409, not_major.text
    assert not_major.json()["code"] == "not_major"
    assert (await _declare(world, a, a.admin, parent)).status_code == 200
    missing = str(uuid.uuid4())  # no such incident
    started = await world.call(
        "POST",
        f"{BASE}/{parent['id']}/children/attach",
        a,
        a.tech_a,
        json={"child_ids": [m["id"] for m in mine] + [theirs["id"], missing]},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert started.status_code == 202, started.text
    await run_bulk_jobs(world.app.state.db, world.app.state.settings)
    job = await world.call("GET", f"{BASE}/bulk-jobs/{started.json()['id']}", a, a.tech_a)
    outcomes = {r["id"]: (r["outcome"], r.get("code")) for r in job.json()["results"]}
    assert all(outcomes[m["id"]] == ("done", None) for m in mine)
    assert outcomes[theirs["id"]][0] == "skipped"  # refused for this person, by code
    # One the person cannot see is refused exactly like one that does not exist (lane C).
    assert outcomes[theirs["id"]] == outcomes[missing]
    named = {r["id"]: r["display_id"] for r in job.json()["results"]}
    assert named[theirs["id"]] is None  # never named to someone who may not see it
    # Seen but not changeable (a report viewer sees every incident, edits only its group's):
    # refused for its right, by name, unlike one it cannot see (lane C).
    from conftest import assign_system_role  # noqa: PLC0415

    await assign_system_role(world.db.admin_url, a.tenant, a.tech_a, "report_viewer")
    again = await world.call(
        "POST",
        f"{BASE}/{parent['id']}/children/attach",
        a,
        a.tech_a,
        json={"child_ids": [theirs["id"]]},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert again.status_code == 202, again.text
    await run_bulk_jobs(world.app.state.db, world.app.state.settings)
    seen = await world.call("GET", f"{BASE}/bulk-jobs/{again.json()['id']}", a, a.tech_a)
    (result,) = seen.json()["results"]
    assert result["outcome"] == "skipped"
    assert result["display_id"] == theirs["display_id"]
    assert result["code"] != outcomes[missing][1]  # its right, not "not found"
    children = await world.sql(
        "SELECT source_id FROM work_item_links WHERE tenant_id = $1 AND target_id = $2"
        " AND kind = 'child_of' AND deleted_at IS NULL",
        a.tenant,
        uuid.UUID(parent["id"]),
    )
    assert {r["source_id"] for r in children} == {uuid.UUID(m["id"]) for m in mine}
