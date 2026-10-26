"""Incident settings screens' API and templates (WP-020c). Test names cite parity file 01 / 11.

Same world as the incidents tests (two tenants, admins, technicians); everything is created in
the session's throwaway database.
"""

import uuid
from typing import Any

import httpx
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.test_incidents_api import (
    BASE,
    CONSOLE,
    Org,
    World,
    field_codes,
    problem,
    world,
)

__all__ = ["world"]  # the fixture, re-used

SETTINGS = f"{BASE}/settings"


async def catalogue(world: World, org: Org) -> dict[str, Any]:
    response = await world.call("GET", SETTINGS, org, org.admin)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def admin_write(
    world: World,
    org: Org,
    method: str,
    path: str,
    body: Any,  # noqa: ANN401 - JSON
    *,
    user: uuid.UUID | None = None,
    version: int | None = None,
) -> httpx.Response:
    if version is None:
        version = (await catalogue(world, org))["version"]
    return await world.call(
        method,
        path,
        org,
        user or org.admin,
        json=body,
        headers={"If-Match": f'"{version}"', **CONSOLE},
    )


async def audit_actions(world: World, org: Org, like: str) -> list[str]:
    rows = await world.sql(
        "SELECT action FROM audit_entries WHERE tenant_id = $1 AND action LIKE $2"
        " AND outcome = 'done' ORDER BY occurred_at",
        org.tenant,
        like,
    )
    return [r["action"] for r in rows]


# --- statuses, reasons per transition, scales, matrix ---------------------------------------------


async def test_req_inc_044_ac4_status_labels_and_colour(world: World) -> None:
    a = world.a
    before = await catalogue(world, a)
    changed = await admin_write(
        world,
        a,
        "PATCH",
        f"{SETTINGS}/statuses/in_progress",
        {"labels": {"en": "Working on it", "ar": "قيد العمل"}, "colour": "#0050B3"},
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    status = next(s for s in body["statuses"] if s["code"] == "in_progress")
    assert (status["labels"]["en"], status["colour"], status["category"]) == (
        "Working on it",
        "#0050b3",
        "open",
    )
    assert body["version"] == before["version"] + 1
    assert changed.headers["ETag"] == f'"{body["version"]}"'
    # A stale version is a conflict, not a silent overwrite.
    stale = await admin_write(
        world,
        a,
        "PATCH",
        f"{SETTINGS}/statuses/new",
        {"colour": "#000000"},
        version=before["version"],
    )
    assert problem(stale) == (409, "version_conflict")
    bad = await admin_write(world, a, "PATCH", f"{SETTINGS}/statuses/new", {"colour": "red"})
    assert field_codes(bad) == {"colour": "invalid_colour"}
    english = await admin_write(
        world, a, "PATCH", f"{SETTINGS}/statuses/new", {"labels": {"ar": "جديد"}}
    )
    assert field_codes(english) == {"labels": "english_label_required"}
    # Back to the shipped labels.
    reset = await admin_write(
        world, a, "PATCH", f"{SETTINGS}/statuses/in_progress", {"labels": None}
    )
    assert next(s for s in reset.json()["statuses"] if s["code"] == "in_progress")["labels"] is None
    # Tenant B is untouched; technicians may not change settings.
    other = await catalogue(world, world.b)
    assert next(s for s in other["statuses"] if s["code"] == "in_progress")["colour"] != "#0050b3"
    refused = await admin_write(
        world, a, "PATCH", f"{SETTINGS}/statuses/new", {"colour": "#000000"}, user=a.tech_a
    )
    assert refused.status_code == 403
    assert "incident.settings_changed" in await audit_actions(world, a, "incident.settings%")


async def test_req_inc_047_ac3_reason_prompt_per_transition(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, technician_id=str(a.tech_a), group_id=str(a.ga))
    # Default: pausing needs a reason.
    refused = await world.act(a, a.admin, item, "wait_requester")
    assert refused.status_code == 422
    off = await admin_write(
        world,
        a,
        "PATCH",
        f"{SETTINGS}/transitions/assigned/wait_requester",
        {"reason_mode": "none"},
    )
    assert off.status_code == 200, off.text
    moved = next(
        t
        for t in off.json()["transitions"]
        if (t["from_status"], t["action"]) == ("assigned", "wait_requester")
    )
    assert (moved["reason_mode"], moved["reason_list"]) == ("none", None)
    paused = await world.act(a, a.admin, await world.fresh(a, item), "wait_requester")
    assert paused.status_code == 200, paused.text
    # Turned back on as optional: it asks from the pause list again.
    optional = await admin_write(
        world,
        a,
        "PATCH",
        f"{SETTINGS}/transitions/assigned/wait_requester",
        {"reason_mode": "optional"},
    )
    moved = next(
        t
        for t in optional.json()["transitions"]
        if (t["from_status"], t["action"]) == ("assigned", "wait_requester")
    )
    assert (moved["reason_mode"], moved["reason_list"]) == ("optional", "pause")
    # System transitions are not editable.
    system = await admin_write(
        world, a, "PATCH", f"{SETTINGS}/transitions/new/assign", {"reason_mode": "required"}
    )
    assert system.status_code in {404, 422}


async def test_req_inc_009_ac4_matrix_editor_refuses_an_empty_cell(world: World) -> None:
    a = world.a
    cat = await catalogue(world, a)
    cells = [dict(c) for c in cat["matrix"]]
    for cell in cells:
        if (cell["impact"], cell["urgency"]) == ("one_person", "critical"):
            cell["priority"] = "p1"
    saved = await admin_write(world, a, "PUT", f"{SETTINGS}/matrix", {"cells": cells})
    assert saved.status_code == 200, saved.text
    item = await world.create(a, a.admin, impact="one_person", urgency="critical")
    assert item["priority"] == "p1"  # takes effect at once
    missing = await admin_write(world, a, "PUT", f"{SETTINGS}/matrix", {"cells": cells[:-1]})
    assert field_codes(missing) == {"cells": "matrix_incomplete"}
    history = await world.sql(
        "SELECT field FROM field_changes"
        " WHERE tenant_id = $1 AND record_type = 'work_item_settings'",
        a.tenant,
    )
    assert "matrix.one_person.critical" in {r["field"] for r in history}


async def test_req_adm_043_scale_value_labels_and_colour(world: World) -> None:
    a = world.a
    saved = await admin_write(
        world,
        a,
        "PATCH",
        f"{SETTINGS}/scales/priority/p1",
        {"labels": {"en": "P1 Critical", "ar": "حرج", "ur": "انتہائی"}, "colour": "#a8071a"},
    )
    assert saved.status_code == 200, saved.text
    p1 = next(v for v in saved.json()["scales"] if (v["scale"], v["code"]) == ("priority", "p1"))
    assert (p1["labels"]["ur"], p1["colour"]) == ("انتہائی", "#a8071a")
    unknown = await admin_write(world, a, "PATCH", f"{SETTINGS}/scales/impact/p1", {"colour": None})
    assert unknown.status_code == 404


# --- pick lists: reasons, levels, closure codes ---------------------------------------------------


async def test_req_inc_007_levels_seeded_added_retired_and_kept_on_old_records(
    world: World,
) -> None:
    a = world.a
    cat = await catalogue(world, a)
    assert [v["code"] for v in cat["levels"]] == ["tier_1", "tier_2", "tier_3", "tier_4"]
    assert [v["code"] for v in cat["closure_codes"]] == [
        "fixed",
        "workaround",
        "no_fault_found",
        "duplicate",
        "user_error",
    ]
    added = await admin_write(
        world,
        a,
        "POST",
        f"{SETTINGS}/lists/level/values",
        {"labels": {"en": "Vendor", "ar": "المورد"}, "colour": "#722ED1"},
    )
    assert added.status_code == 201, added.text
    vendor = next(v for v in added.json()["levels"] if v["labels"])
    assert vendor["code"].startswith("v_")
    assert vendor["sort_order"] == 4
    duplicate = await admin_write(
        world, a, "POST", f"{SETTINGS}/lists/level/values", {"labels": {"en": "vendor"}}
    )
    assert field_codes(duplicate) == {"labels": "duplicate_name"}
    item = await world.create(a, a.admin, level=vendor["code"], impact_details="Floor 3 printers")
    assert (item["level"], item["impact_details"]) == (vendor["code"], "Floor 3 printers")
    retired = await admin_write(
        world,
        a,
        "PATCH",
        f"{SETTINGS}/lists/level/values/{vendor['code']}",
        {"disabled": True},
    )
    assert next(v for v in retired.json()["levels"] if v["code"] == vendor["code"])["disabled"]
    # Not offered for new input ...
    refused = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"subject": "x", "requester_id": str(a.requester), "level": vendor["code"]},
        headers=CONSOLE,
    )
    assert field_codes(refused) == {"level": "invalid_choice"}
    # ... but the old record keeps it and can still be edited otherwise.
    fresh = await world.fresh(a, item)
    assert fresh["level"] == vendor["code"]
    edited = await world.patch(a, a.admin, fresh, subject="Printers down", level=vendor["code"])
    assert edited.status_code == 200, edited.text
    # Reorder: every value, once.
    codes = [v["code"] for v in retired.json()["levels"]]
    partial = await admin_write(
        world, a, "PUT", f"{SETTINGS}/lists/level/order", {"codes": codes[:2]}
    )
    assert field_codes(partial) == {"codes": "order_must_list_every_value"}
    reordered = await admin_write(
        world, a, "PUT", f"{SETTINGS}/lists/level/order", {"codes": list(reversed(codes))}
    )
    assert [v["code"] for v in reordered.json()["levels"]] == list(reversed(codes))


async def test_req_adm_043_reason_lists_keep_other_and_label_retired_reasons(world: World) -> None:
    a = world.a
    other = await admin_write(
        world, a, "PATCH", f"{SETTINGS}/lists/pause/values/other", {"disabled": True}
    )
    assert field_codes(other) == {"disabled": "value_required_by_system"}
    retired = await admin_write(
        world, a, "PATCH", f"{SETTINGS}/lists/pause/values/confirmation", {"disabled": True}
    )
    assert retired.status_code == 200, retired.text
    reasons = {(r["list"], r["code"]): r for r in retired.json()["reasons"]}
    assert reasons[("pause", "confirmation")]["disabled"] is True  # still there to label
    item = await world.create(a, a.admin, technician_id=str(a.tech_a), group_id=str(a.ga))
    refused = await world.act(a, a.admin, item, "wait_requester", reason_code="confirmation")
    assert field_codes(refused) == {"reason_code": "invalid_choice"}
    unknown = await admin_write(
        world, a, "POST", f"{SETTINGS}/lists/nonsense/values", {"labels": {"en": "x"}}
    )
    assert unknown.status_code == 422  # not a list (path validation)


# --- numbering (REQ-WI-002 AC4, REQ-ADM-045) ------------------------------------------------------


async def test_req_adm_045_next_number_never_reuses_an_id(world: World) -> None:
    a = world.a
    assert (await catalogue(world, a))["next_number"] == 1
    await world.create(a, a.admin)
    await world.create(a, a.admin)
    cat = await catalogue(world, a)
    assert cat["next_number"] == 3
    lower = await admin_write(world, a, "PUT", f"{SETTINGS}/numbering", {"next_number": 2})
    assert field_codes(lower) == {"next_number": "number_already_used"}
    assert lower.json()["errors"][0]["params"] == {"minimum": 3}
    raised = await admin_write(world, a, "PUT", f"{SETTINGS}/numbering", {"next_number": 1000})
    assert raised.status_code == 200, raised.text
    assert raised.json()["next_number"] == 1000
    item = await world.create(a, a.admin)
    assert item["display_id"] == "INC-1000"
    # Tenant B still starts at 1.
    assert (await world.create(world.b, world.b.admin))["display_id"] == "INC-1"
    # A fresh tenant may set its first number before anything was created.
    first = await admin_write(world, world.b, "PUT", f"{SETTINGS}/numbering", {"next_number": 500})
    assert first.status_code == 200, first.text


# --- templates (REQ-INC-035) ----------------------------------------------------------------------


async def templates(world: World, org: Org, user: uuid.UUID | None = None) -> list[dict[str, Any]]:
    response = await world.call("GET", f"{BASE}/templates", org, user or org.admin)
    assert response.status_code == 200, response.text
    return list(response.json())


async def new_template(world: World, org: Org, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call("POST", f"{BASE}/templates", org, org.admin, json=body, headers=CONSOLE)


async def patch_template(
    world: World,
    org: Org,
    template: dict[str, Any],
    **body: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "PATCH",
        f"{BASE}/templates/{template['id']}",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{template["version"]}"', **CONSOLE},
    )


async def test_req_inc_035_standard_template_is_seeded_as_default(world: World) -> None:
    a = world.a
    found = await templates(world, a, a.tech_a)  # technicians read them for the form
    assert len(found) == 1
    standard = found[0]
    assert (standard["code"], standard["is_default"], standard["disabled"]) == (
        "standard",
        True,
        False,
    )
    assert standard["fields"]["subject"]["required"] is True
    assert standard["fields"]["category_id"] == {
        "shown": True,
        "required": False,
        "requester_can_see": True,
        "requester_can_fill": False,
    }
    item = await world.create(a, a.admin)
    assert item["template_id"] == standard["id"]


async def test_req_inc_035_ac1_template_defaults_and_required_fields(world: World) -> None:
    a = world.a
    tree = (await world.call("GET", f"{BASE}/categories", a, a.admin)).json()
    network = next(n for n in tree if n["code"] == "network")
    created = await new_template(
        world,
        a,
        labels={"en": "Network outage", "ar": "انقطاع الشبكة"},
        group_name="Infrastructure",
        fields={
            "category_id": {"shown": True, "required": True},
            "impact_details": {"shown": True, "required": True},
            "on_behalf_of_id": {"shown": False},
        },
        defaults={"category_id": network["id"], "group_id": str(a.ga), "urgency": "high"},
    )
    assert created.status_code == 201, created.text
    template = created.json()
    assert template["defaults"]["category_id"] == network["id"]
    assert template["fields"]["on_behalf_of_id"]["shown"] is False
    # The server enforces the template's required fields (the form shows them first).
    missing = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={
            "subject": "VPN down",
            "requester_id": str(a.requester),
            "template_id": template["id"],
        },
        headers=CONSOLE,
    )
    assert field_codes(missing) == {"category_id": "required", "impact_details": "required"}
    item = await world.create(
        a,
        a.admin,
        template_id=template["id"],
        category_id=network["id"],
        impact_details="Whole second floor",
    )
    assert item["template_id"] == template["id"]
    assert "incident.template_created" in await audit_actions(world, a, "incident.template%")


async def test_req_wi_009_ac4_template_that_can_never_work_is_refused(world: World) -> None:
    a = world.a
    hidden_required = await new_template(
        world,
        a,
        labels={"en": "Broken"},
        fields={"category_id": {"shown": False, "required": True}},
    )
    assert field_codes(hidden_required) == {"fields.category_id": "hidden_required_needs_default"}
    subject_optional = await new_template(
        world, a, labels={"en": "Broken 2"}, fields={"subject": {"shown": True, "required": False}}
    )
    assert field_codes(subject_optional) == {"fields.subject": "field_always_required"}
    bad_default = await new_template(
        world, a, labels={"en": "Broken 3"}, defaults={"category_id": str(uuid.uuid4())}
    )
    assert field_codes(bad_default) == {"defaults.category_id": "category_not_found"}
    people_default = await new_template(
        world, a, labels={"en": "Broken 4"}, defaults={"technician_id": str(a.tech_a)}
    )
    assert field_codes(people_default) == {"defaults.technician_id": "no_default_allowed"}
    fill = await new_template(
        world,
        a,
        labels={"en": "Broken 5"},
        fields={"tags": {"requester_can_see": False, "requester_can_fill": True}},
    )
    assert field_codes(fill) == {"fields.tags": "fill_needs_see"}
    # A hidden required field with a default is fine (the default fills it).
    ok = await new_template(
        world,
        a,
        labels={"en": "Hidden urgency"},
        fields={"urgency": {"shown": False, "required": True}},
        defaults={"urgency": "low"},
    )
    assert ok.status_code == 201, ok.text


async def test_req_inc_035_ac2_disabled_template_not_offered_but_still_named(world: World) -> None:
    a = world.a
    template = (await new_template(world, a, labels={"en": "Printer"})).json()
    item = await world.create(a, a.admin, template_id=template["id"])
    disabled = await patch_template(world, a, template, disabled=True)
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["disabled"] is True
    refused = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"subject": "x", "requester_id": str(a.requester), "template_id": template["id"]},
        headers=CONSOLE,
    )
    assert field_codes(refused) == {"template_id": "template_disabled"}
    # Still listed (marked) so old records can name it; the record keeps its template.
    listed = {t["id"]: t for t in await templates(world, a)}
    assert listed[template["id"]]["disabled"] is True
    assert (await world.fresh(a, item))["template_id"] == template["id"]


async def test_req_inc_035_ac3_copy_is_independent_and_marked(world: World) -> None:
    a = world.a
    original = (
        await new_template(
            world, a, labels={"en": "Laptop"}, fields={"category_id": {"required": True}}
        )
    ).json()
    copied = await world.call(
        "POST",
        f"{BASE}/templates/{original['id']}/copy",
        a,
        a.admin,
        json={"labels": {"en": "Laptop (copy)"}},
    )
    assert copied.status_code == 201, copied.text
    copy = copied.json()
    assert copy["copied_from_id"] == original["id"]
    assert copy["fields"]["category_id"]["required"] is True
    assert copy["is_default"] is False
    changed = await patch_template(world, a, copy, fields={"category_id": {"required": False}})
    assert changed.status_code == 200, changed.text
    again = {t["id"]: t for t in await templates(world, a)}
    assert again[original["id"]]["fields"]["category_id"]["required"] is True
    same_name = await world.call(
        "POST",
        f"{BASE}/templates/{original['id']}/copy",
        a,
        a.admin,
        json={"labels": {"en": "laptop"}},
    )
    assert field_codes(same_name) == {"labels": "duplicate_name"}


async def test_req_inc_035_default_moves_and_cannot_be_disabled(world: World) -> None:
    a = world.a
    standard = (await templates(world, a))[0]
    no_disable = await patch_template(world, a, standard, disabled=True)
    assert field_codes(no_disable) == {"disabled": "default_cannot_be_disabled"}
    no_unset = await patch_template(world, a, standard, is_default=False)
    assert field_codes(no_unset) == {"is_default": "default_required"}
    other = (await new_template(world, a, labels={"en": "Walk-up"})).json()
    made = await patch_template(world, a, other, is_default=True)
    assert made.status_code == 200, made.text
    listed = await templates(world, a)
    assert [t["id"] for t in listed if t["is_default"]] == [other["id"]]
    assert listed[0]["id"] == other["id"]  # the default comes first
    item = await world.create(a, a.admin)
    assert item["template_id"] == other["id"]
    demoted = await world.sql(
        "SELECT field, old_value, new_value FROM field_changes"
        " WHERE tenant_id = $1 AND record_type = 'work_item_template' AND record_id = $2",
        a.tenant,
        uuid.UUID(standard["id"]),
    )
    assert [r["field"] for r in demoted] == ["is_default"]  # the old default's own history
    # The previous default can now be disabled.
    old = next(t for t in listed if t["id"] == standard["id"])
    assert (await patch_template(world, a, old, disabled=True)).status_code == 200
    # Stale version.
    stale = await patch_template(world, a, other, description="x")
    assert problem(stale) == (409, "version_conflict")


async def test_req_inc_006_ac3_disabled_category_kept_on_old_records(world: World) -> None:
    a = world.a
    tree = (await world.call("GET", f"{BASE}/categories", a, a.admin)).json()
    vpn = next(n for n in tree if n["code"] == "vpn")
    item = await world.create(a, a.admin, category_id=vpn["id"])
    disabled = await world.call(
        "PATCH",
        f"{BASE}/categories/{vpn['id']}",
        a,
        a.admin,
        json={"disabled": True},
        headers={"If-Match": f'"{vpn["version"]}"'},
    )
    assert disabled.status_code == 200, disabled.text
    fresh = await world.fresh(a, item)
    assert fresh["category_id"] == vpn["id"]
    # Editing something else on the old record keeps the disabled category.
    edited = await world.patch(a, a.admin, fresh, subject="VPN slow", category_id=vpn["id"])
    assert edited.status_code == 200, edited.text
    # A template cannot start new records in it.
    refused = await new_template(
        world, a, labels={"en": "VPN"}, defaults={"category_id": vpn["id"]}
    )
    assert field_codes(refused) == {"defaults.category_id": "category_disabled"}


async def test_settings_changes_reach_open_screens_live(world: World) -> None:
    a = world.a
    await admin_write(world, a, "PATCH", f"{SETTINGS}/statuses/new", {"colour": "#123456"})
    await new_template(world, a, labels={"en": "Live"})
    rows = await world.sql(
        "SELECT event_type, envelope AS payload FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'work_items.settings.changed' ORDER BY created_at",
        a.tenant,
    )
    changed = [r["payload"] for r in rows]
    assert any('"statuses"' in str(p) for p in changed)
    assert any('"templates"' in str(p) for p in changed)


async def test_templates_table_is_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    template = (await new_template(world, a, labels={"en": "Only A"})).json()
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        rows = (
            await session.execute(
                text("SELECT id FROM work_item_templates WHERE id = :id"),
                {"id": uuid.UUID(template["id"])},
            )
        ).all()
        assert rows == []
        updated = await session.execute(
            text("UPDATE work_item_templates SET is_default = false WHERE id = :id"),
            {"id": uuid.UUID(template["id"])},
        )
        assert updated.rowcount == 0
    other = await world.call(
        "POST",
        BASE,
        b,
        b.admin,
        json={"subject": "x", "requester_id": str(b.requester), "template_id": template["id"]},
        headers=CONSOLE,
    )
    assert field_codes(other) == {"template_id": "template_not_found"}
    assert template["id"] not in {t["id"] for t in await templates(world, b)}


async def test_tenants_seeded_before_wp020c_are_topped_up_once(world: World) -> None:
    a = world.a
    await catalogue(world, a)  # seeds version 2
    # Simulate a tenant seeded by WP-020: no levels, closure codes or templates, seed_version 1.
    await world.sql(
        "UPDATE work_item_type_settings SET seed_version = 1 WHERE tenant_id = $1", a.tenant
    )
    await world.sql(
        "DELETE FROM work_item_reasons WHERE tenant_id = $1 AND list IN ('level', 'closure_code')",
        a.tenant,
    )
    await world.sql(
        "UPDATE work_item_templates SET is_default = false, deleted_at = now()"
        " WHERE tenant_id = $1",
        a.tenant,
    )
    cat = await catalogue(world, a)
    assert len(cat["levels"]) == 4
    assert len(cat["closure_codes"]) == 5
    again = await catalogue(world, a)
    assert len(again["levels"]) == 4  # not twice
    assert [t["code"] for t in await templates(world, a)] == ["standard"]
