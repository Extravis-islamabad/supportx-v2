"""Converting incidents and service requests (WP-046b S2; REQ-INC-089; lane B's conditions).

A new record of the other type, never a type change in place: the old record becomes
`converted`, linked, its signed history still verifies; its old number leads to the new record
only for a reader who may read that record (404 otherwise); open approvals are withdrawn; the
new record's timeline lists the old one's entries.
"""

from typing import Any

from tests.db.test_audit_api import run_verify, seal_all
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, world  # noqa: F401 - fixture
from tests.db.test_service_requests_api import SR, an_item, raise_request


def _problem(response: Any) -> tuple[int, str | None]:  # noqa: ANN401 - an httpx response
    body = response.json()
    codes = [e.get("code") for e in body.get("errors") or []]
    return response.status_code, (codes[0] if codes else body.get("code"))


async def _convert(
    world: World,  # noqa: F811
    org: Org,
    path: str,
    item: dict[str, Any],
    **body: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - an httpx response
    fresh = (await world.call("GET", f"{path}/{item['id']}", org, org.admin)).json()
    return await world.call(
        "POST",
        f"{path}/{item['id']}/convert",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )


async def test_an_incident_becomes_a_request_and_its_old_number_leads_there(
    world: World,  # noqa: F811
) -> None:
    a = world.a
    # Requester at site S2, so the request (group B) is out of tech_a's reach (D-052).
    incident = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    note = await world.call(
        "POST",
        f"{BASE}/{incident['id']}/conversation",
        a,
        a.admin,
        json={"kind": "note", "body": "<p>Asked for a laptop, not a fault.</p>"},
        headers=CONSOLE,
    )
    assert note.status_code == 201, note.text
    item = await an_item(world, a, group_id=str(a.gb))  # the request lands in group B
    shown = await world.call("GET", f"{BASE}/{incident['id']}/convert-preview", a, a.admin)
    assert shown.status_code == 200, shown.text
    assert shown.json()["to_type"] == "service_request"
    done = await _convert(
        world, a, BASE, incident, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["new_type"] == "service_request"
    assert out["new_display_id"].startswith("SR-")
    # The old incident stays, converted and linked; the request lists its entries.
    old = (await world.call("GET", f"{BASE}/{incident['id']}", a, a.admin)).json()
    assert old["status"] == "converted"
    links = (await world.call("GET", f"{BASE}/{incident['id']}/links", a, a.admin)).json()
    assert [(x["relation"], x["other_id"]) for x in links] == [("converted_to", out["new_id"])]
    talk = (await world.call("GET", f"{SR}/{out['new_id']}/conversation", a, a.admin)).json()
    assert [e["from_record"] for e in talk["items"]] == [incident["display_id"]]
    # Its old number leads to the request, for someone who may read it...
    found = await world.call("GET", f"{BASE}/alias/{incident['display_id']}", a, a.admin)
    assert found.status_code == 200, found.text
    assert (found.json()["record_type"], found.json()["record_id"]) == (
        "service_request",
        out["new_id"],
    )
    # ...and is simply not found for someone who may not (technicians see every request, so
    # the within-tenant case is the reverse conversion, below).
    # Another tenant never finds it either (the alias table is the tenant's own, RLS).
    b = world.b
    elsewhere = await world.call("GET", f"{BASE}/alias/{incident['display_id']}", b, b.admin)
    assert _problem(elsewhere) == (404, "alias_not_found")
    # Audited with both IDs; the old record's signed history still verifies.
    (audit,) = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'incident.converted' AND object_id = $2",
        a.tenant,
        incident["id"],
    )
    assert out["new_id"] in str(audit["details"])
    await seal_all(world, a)
    result = await run_verify(world, a)
    runs = await world.call("GET", "/audit/verification-runs", a, a.admin)
    run = next(r for r in runs.json() if r["id"] == str(result.run_id))
    assert run["fingerprint_mismatches"] == 0


async def test_a_request_awaiting_approval_becomes_an_incident_its_approvals_withdrawn(
    world: World,  # noqa: F811
) -> None:
    a = world.a
    item = await an_item(world, a, approval={"approvers": [{"kind": "requested_for_manager"}]})
    raised = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert raised.status_code == 201, raised.text
    request = raised.json()
    assert request["approval_status"] == "pending"
    done = await _convert(world, a, SR, request)
    assert done.status_code == 200, done.text
    assert done.json()["new_type"] == "incident"
    approvals = (await world.call("GET", f"{SR}/{request['id']}/approvals", a, a.admin)).json()
    assert {row["state"] for row in approvals["items"]} == {"withdrawn"}
    # A converted record is closed: it cannot be converted again.
    again = await _convert(world, a, SR, request)
    assert _problem(again)[0] == 409


async def test_an_old_number_is_not_found_by_someone_who_may_not_read_the_new_record(
    world: World,  # noqa: F811
) -> None:
    a = world.a
    item = await an_item(world, a)
    # A request for requester2 (site S2): as an incident with no group it is out of tech_a's
    # reach (D-052), though tech_a may read every request.
    raised = await raise_request(
        world,
        a,
        a.admin,
        catalog_item_id=item["id"],
        answers={"model": "air"},
        requester_id=str(a.requester2),
    )
    assert raised.status_code == 201, raised.text
    request = raised.json()
    done = await _convert(world, a, SR, request)
    assert done.status_code == 200, done.text
    found = await world.call("GET", f"{SR}/alias/{request['display_id']}", a, a.admin)
    assert found.json()["record_id"] == done.json()["new_id"]
    hidden = await world.call("GET", f"{SR}/alias/{request['display_id']}", a, a.tech_a)
    assert _problem(hidden) == (404, "alias_not_found")


async def test_a_sealed_value_carries_sealed_again_for_the_new_record(
    world: World,  # noqa: F811
) -> None:
    """Lane B: a sealed field is opened and sealed again under the new record's binding."""
    from tests.db.test_sealed_custom_fields import _stored, _with_keys  # noqa: PLC0415

    _with_keys(world)
    a = world.a
    keys = []
    for entity in ("incident", "service_request"):
        made = await world.call(
            "POST",
            "/custom-fields",
            a,
            a.admin,
            json={"entity": entity, "field_type": "text", "labels": {"en": "Pay band"}},
            headers=CONSOLE,
        )
        assert made.status_code == 201, made.text
        keys.append(str(made.json()["key"]))
        await world.sql(
            "UPDATE custom_fields SET sensitive = true, seal_state = 'sealed'"
            " WHERE tenant_id = $1 AND entity = $2 AND key = $3",
            a.tenant,
            entity,
            keys[-1],
        )
    key = keys[0]
    assert keys[1] == key  # the same field on both types
    incident = await world.create(a, a.admin, group_id=str(a.ga), custom={key: "B7"})
    before, _ = await _stored(world, a, incident["id"], key)
    assert before.startswith("sx2:")
    item = await an_item(world, a)
    done = await _convert(
        world, a, BASE, incident, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert done.status_code == 200, done.text
    assert done.json()["not_carried"] == []
    after, _ = await _stored(world, a, done.json()["new_id"], key)
    assert after.startswith("sx2:")
    assert after != before  # sealed for the new record, never the old ciphertext
    shown = (await world.call("GET", f"{SR}/{done.json()['new_id']}", a, a.admin)).json()
    assert shown["custom"][key] == "B7"


async def test_protection_is_never_dropped_by_converting(world: World) -> None:  # noqa: F811
    """Lane C: sealed on the source and plain on the target stays behind; the reverse seals."""
    from tests.db.test_sealed_custom_fields import _stored, _with_keys  # noqa: PLC0415

    _with_keys(world)
    a = world.a
    keys: dict[tuple[str, str], str] = {}
    for label, sealed_on in (("Badge", "incident"), ("Desk", "service_request")):
        for entity in ("incident", "service_request"):
            made = await world.call(
                "POST",
                "/custom-fields",
                a,
                a.admin,
                json={"entity": entity, "field_type": "text", "labels": {"en": label}},
                headers=CONSOLE,
            )
            assert made.status_code == 201, made.text
            keys[(label, entity)] = str(made.json()["key"])
            if entity == sealed_on:
                await world.sql(
                    "UPDATE custom_fields SET sensitive = true, seal_state = 'sealed'"
                    " WHERE tenant_id = $1 AND entity = $2 AND key = $3",
                    a.tenant,
                    entity,
                    keys[(label, entity)],
                )
    badge, desk = keys[("Badge", "incident")], keys[("Desk", "incident")]
    incident = await world.create(
        a, a.admin, group_id=str(a.ga), custom={badge: "B-17", desk: "4F-12"}
    )
    item = await an_item(world, a)
    done = await _convert(
        world, a, BASE, incident, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert done.status_code == 200, done.text
    # Sealed on the incident, plain on the request: not carried, named, kept on the old one.
    assert done.json()["not_carried"] == [f"custom.{badge}"]
    new_badge: str | None = (await _stored(world, a, done.json()["new_id"], badge))[0]
    assert new_badge is None
    # Plain on the incident, sealed on the request: carried, and sealed on create.
    new_desk, _ = await _stored(world, a, done.json()["new_id"], desk)
    assert new_desk.startswith("sx2:")
    shown = (await world.call("GET", f"{SR}/{done.json()['new_id']}", a, a.admin)).json()
    assert shown["custom"][desk] == "4F-12"
