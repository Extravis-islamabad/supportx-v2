"""Reply and resolution templates over HTTP (WP-046a S5a; REQ-INC-041, REQ-INC-042).

Who may read and write them (the coordinator, lane B reviews): a personal template is its owner's
only, administrators included; a shared one needs the type's settings right to write and may be
limited to groups. Filling one for a record puts the record's values in its variables, in the
requester's language, and an empty one reads "not set" (041 AC1-AC3). A resolution template of
the record's category comes first (042 AC2). Real PostgreSQL; the cast is test_incidents_api's.
"""

import uuid
from typing import Any

import httpx

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, field_codes, problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

PATH = f"{BASE}/reply-templates"


async def make(
    world: World,
    org: Org,
    user: uuid.UUID,
    **values: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    body = {"name": f"T {uuid.uuid4().hex[:8]}", "bodies": {"en": "<p>Hello</p>"}, **values}
    return await world.call(
        "POST", PATH, org, user, json=body, headers={"Idempotency-Key": str(uuid.uuid4())}
    )


async def names(world: World, org: Org, user: uuid.UUID, query: str = "") -> list[str]:
    found = await world.call("GET", f"{PATH}{query}", org, user)
    assert found.status_code == 200, found.text
    return [t["name"] for t in found.json()]


async def managed(world: World, org: Org, user: uuid.UUID, kind: str = "reply") -> list[str]:
    found = await world.call("GET", f"{PATH}/manage?kind={kind}", org, user)
    assert found.status_code == 200, found.text
    return [t["name"] for t in found.json()]


async def fill(
    world: World,
    org: Org,
    user: uuid.UUID,
    item: dict[str, Any],
    template: dict[str, Any],
    language: str | None = None,
) -> httpx.Response:
    return await world.call(
        "POST",
        f"{BASE}/{item['id']}/reply-templates/{template['id']}/fill",
        org,
        user,
        json={"language": language},
    )


async def test_personal_templates_are_their_owner_s_only(world: World) -> None:
    a = world.a
    mine = await make(world, a, a.tech_a, name="My thanks", visibility="personal")
    assert mine.status_code == 201, mine.text
    template = mine.json()
    assert (template["visibility"], template["mine"], template["may_edit"]) == (
        "personal",
        True,
        True,
    )
    assert "My thanks" in await names(world, a, a.tech_a)
    assert "My thanks" in await managed(world, a, a.tech_a)
    # Nobody else lists, reads, fills, changes or removes it: administrators included.
    for other in (a.admin, a.tech_c):
        assert "My thanks" not in await names(world, a, other)
        assert "My thanks" not in await managed(world, a, other)
    item = await world.create(a, a.admin, group_id=str(a.ga))
    assert problem(await fill(world, a, a.admin, item, template)) == (
        404,
        "reply_template_not_found",
    )
    changed = await world.call(
        "PUT",
        f"{PATH}/{template['id']}",
        a,
        a.admin,
        json={"name": "Taken", "bodies": {"en": "<p>x</p>"}, "visibility": "personal"},
        headers={"If-Match": f'"{template["version"]}"'},
    )
    assert problem(changed) == (404, "reply_template_not_found")
    removed = await world.call(
        "DELETE", f"{PATH}/{template['id']}", a, a.admin, headers={"If-Match": '"1"'}
    )
    assert problem(removed) == (404, "reply_template_not_found")
    # Two people may each have a personal one of the same name.
    same = await make(world, a, a.tech_c, name="My thanks", visibility="personal")
    assert same.status_code == 201, same.text
    # Its owner changes it, but sharing it needs the settings right.
    shared = await world.call(
        "PUT",
        f"{PATH}/{template['id']}",
        a,
        a.tech_a,
        json={"name": "My thanks", "bodies": {"en": "<p>x</p>"}, "visibility": "shared"},
        headers={"If-Match": f'"{template["version"]}"'},
    )
    assert shared.status_code == 403, shared.text
    own = await world.call(
        "PUT",
        f"{PATH}/{template['id']}",
        a,
        a.tech_a,
        json={"name": "My thanks", "bodies": {"en": "<p>Thank you</p>"}, "visibility": "personal"},
        headers={"If-Match": f'"{template["version"]}"'},
    )
    assert own.status_code == 200, own.text


async def test_shared_templates_need_the_settings_right_and_honour_groups(world: World) -> None:
    a = world.a
    refused = await make(world, a, a.tech_a, name="Everyone")
    assert refused.status_code == 403, refused.text
    for_ga = await make(world, a, a.admin, name="GA only", group_ids=[str(a.ga)])
    assert for_ga.status_code == 201, for_ga.text
    assert for_ga.json()["may_edit"] is True
    # Offered to GA's members only; listed for management to everyone, editable by the right.
    assert "GA only" in await names(world, a, a.tech_a)
    assert "GA only" not in await names(world, a, a.tech_b)
    listed = await world.call("GET", f"{PATH}/manage", a, a.tech_b)
    row = next(t for t in listed.json() if t["name"] == "GA only")
    assert row["may_edit"] is False
    item = await world.create(a, a.admin, group_id=str(a.gb))
    assert problem(await fill(world, a, a.tech_b, item, for_ga.json())) == (
        404,
        "reply_template_not_found",
    )
    # A personal template takes no groups; a reply takes no categories.
    wrong = await make(
        world, a, a.tech_a, visibility="personal", group_ids=[str(a.ga)], category_ids=[]
    )
    assert field_codes(wrong) == {"group_ids": "not_for_personal"}
    tree = (await world.call("GET", f"{BASE}/categories", a, a.admin)).json()
    printer = next(n for n in tree if n["code"] == "printer")
    reply = await make(world, a, a.admin, category_ids=[printer["id"]])
    assert field_codes(reply) == {"category_ids": "not_for_replies"}


async def test_other_tenants_ids_are_refused(world: World) -> None:
    a, b = world.a, world.b
    tree = (await world.call("GET", f"{BASE}/categories", b, b.admin)).json()
    theirs = next(n for n in tree if n["code"] == "printer")
    group = await make(world, a, a.admin, group_ids=[str(b.ga)])
    assert field_codes(group) == {"group_ids": "unknown_group"}
    category = await make(world, a, a.admin, kind="resolution", category_ids=[theirs["id"]])
    assert field_codes(category) == {"category_ids": "unknown_category"}
    made = (await make(world, a, a.admin, name="A's own")).json()
    assert "A's own" not in await managed(world, b, b.admin)
    item = await world.create(b, b.admin)
    assert (await fill(world, b, b.admin, item, made)).status_code == 404


async def test_req_inc_041_variables_language_and_not_set(world: World) -> None:
    a = world.a
    unknown = await make(world, a, a.admin, bodies={"en": "<p>{{ record.nope }}</p>"})
    assert field_codes(unknown) == {"bodies.en": "unknown_variable"}
    made = await make(
        world,
        a,
        a.admin,
        name="Update",
        subject="About {{ record.display_id }}",
        bodies={
            "en": "<p>{{ record.title }} for {{ assignee.name }}</p>",
            "ar": "<p>{{ record.title }} - {{assignee.name}}</p>",
        },
    )
    assert made.status_code == 201, made.text
    template = made.json()
    item = await world.create(a, a.admin, subject="Printer <jammed> & stuck")
    # AC1: the values in place, escaped as text; AC3: an empty one reads "not set".
    filled = await fill(world, a, a.admin, item, template)
    assert filled.status_code == 200, filled.text
    out = filled.json()
    assert out["language"] == "en"
    assert out["subject"] == f"About {item['display_id']}"
    assert out["body"] == "<p>Printer &lt;jammed&gt; &amp; stuck for not set</p>"
    # AC2: the requester's language first; the screen's choice wins over it.
    await world.sql(
        "UPDATE users SET ui_locale = 'ar' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        a.requester,
    )
    arabic = (await fill(world, a, a.admin, item, template)).json()
    assert arabic["language"] == "ar"
    assert "{{" not in arabic["body"]
    assert (await fill(world, a, a.admin, item, template, "en")).json()["language"] == "en"
    # A language the template lacks falls back to one it has.
    assert (await fill(world, a, a.admin, item, template, "ur")).json()["language"] in {"ar", "en"}


async def test_req_inc_042_the_record_s_category_comes_first(world: World) -> None:
    a = world.a
    tree = (await world.call("GET", f"{BASE}/categories", a, a.admin)).json()
    printer = next(n for n in tree if n["code"] == "printer")
    general = await make(world, a, a.admin, kind="resolution", name="AAA general")
    printers = await make(
        world, a, a.admin, kind="resolution", name="ZZZ printers", category_ids=[printer["id"]]
    )
    assert (general.status_code, printers.status_code) == (201, 201), printers.text
    plain = await names(world, a, a.tech_a, "?kind=resolution")
    assert plain.index("AAA general") < plain.index("ZZZ printers")
    first = await names(world, a, a.tech_a, f"?kind=resolution&category_id={printer['id']}")
    assert first[0] == "ZZZ printers"
    # Resolution templates are not offered in the composer.
    assert "ZZZ printers" not in await names(world, a, a.tech_a)


async def test_older_clients_one_body_still_works(world: World) -> None:
    a = world.a
    made = await world.call(
        "POST",
        PATH,
        a,
        a.admin,
        json={"name": "Legacy", "body": "<p>Old</p>"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    assert (made.json()["bodies"], made.json()["body"]) == ({"en": "<p>Old</p>"}, "<p>Old</p>")
