"""Address ranges mapped to sites (WP-057 S2b-1; D-170 item 2).

- The list is saved whole under the identity settings version (If-Match), most specific first.
- Wrong ranges (host bits set, not a range), a range twice, too many, and a site that is not an
  active site of this tenant are refused at their entry.
- Every change is audited with the ranges and site IDs before and after, and emits the settings
  event; only identity managers see or change it.
"""

import json
import uuid
from datetime import timedelta

import asyncpg

from tests.db.test_identity_api import World, _admin_rows, world
from tests.db.test_sign_in_log_api import _event

__all__ = ["world"]  # the fixture, re-used

PATH = "/identity/site-networks"


async def _site(world: World) -> str:
    sites = await world.call("GET", "/organization/sites", world.a)
    assert sites.status_code == 200, sites.text
    return str(sites.json()[0]["id"])


async def test_the_list_is_saved_whole_most_specific_first_and_audited(world: World) -> None:
    site = await _site(world)
    shown = await world.call("GET", PATH, world.a)
    assert (shown.status_code, shown.json()) == (200, {"entries": [], "version": 0})
    body = {
        "entries": [
            {"network": "10.1.0.0/16", "site_id": site},
            {"network": "2001:db8:1::/48", "site_id": site},
            {"network": "10.1.7.0/24", "site_id": site},
            {"network": "203.0.113.9", "site_id": site},
        ]
    }
    saved = await world.call("PUT", PATH, world.a, json=body, headers={"If-Match": '"0"'})
    assert saved.status_code == 200, saved.text
    assert [e["network"] for e in saved.json()["entries"]] == [
        "203.0.113.9/32",  # one address, as its range; IPv4 by prefix length, then IPv6
        "10.1.7.0/24",
        "10.1.0.0/16",
        "2001:db8:1::/48",
    ]
    assert (saved.json()["version"], saved.headers["ETag"]) == (1, '"1"')
    again = await world.call("GET", PATH, world.a)
    assert again.json() == saved.json()
    stale = await world.call(
        "PUT", PATH, world.a, json={"entries": []}, headers={"If-Match": '"0"'}
    )
    assert stale.status_code == 409
    (entry,) = await _admin_rows(
        world.db,
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2"
        " AND outcome = 'done'",
        world.a.tenant,
        "identity.site_networks_changed",
    )
    details = json.loads(entry["details"])
    assert details["before"] == []
    assert {"network": "10.1.0.0/16", "site_id": site} in details["after"]
    events = await _admin_rows(
        world.db,
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2",
        world.a.tenant,
        "identity_access.identity_settings.changed",
    )
    assert any(
        json.loads(e["envelope"])["payload"]["changed_fields"] == ["site_networks"] for e in events
    )
    # Saving the same list again changes nothing: no new version, no audit entry.
    same = await world.call("PUT", PATH, world.a, json=body, headers={"If-Match": '"1"'})
    assert (same.status_code, same.json()["version"]) == (200, 1)


async def test_wrong_entries_are_refused_at_their_entry(world: World) -> None:
    site = await _site(world)
    refused = await world.call(
        "PUT",
        PATH,
        world.a,
        json={
            "entries": [
                {"network": "10.1.2.3/16", "site_id": site},  # host bits set
                {"network": "office", "site_id": site},
                {"network": "10.2.0.0/16", "site_id": site},
                {"network": "10.2.0.0/16", "site_id": site},  # twice
                {"network": "10.3.0.0/16", "site_id": str(uuid.uuid4())},  # no such site
            ]
        },
        headers={"If-Match": '"0"'},
    )
    assert refused.status_code == 422, refused.text
    codes = {(e["field"], e["code"]) for e in refused.json()["errors"]}
    assert ("entries.0", "site_network_invalid") in codes
    assert ("entries.1", "site_network_invalid") in codes
    assert ("entries.3", "duplicate_value") in codes
    assert any(code == "site_not_found" for _field, code in codes)
    too_many = await world.call(
        "PUT",
        PATH,
        world.a,
        json={"entries": [{"network": f"10.{i}.0.0/16", "site_id": site} for i in range(201)]},
        headers={"If-Match": '"0"'},
    )
    assert too_many.status_code == 422  # the body's own limit (200)


async def test_another_tenants_site_is_never_accepted(world: World) -> None:
    theirs = await world.call("GET", "/organization/sites", world.b)
    other_site = str(theirs.json()[0]["id"])
    refused = await world.call(
        "PUT",
        PATH,
        world.a,
        json={"entries": [{"network": "10.4.0.0/16", "site_id": other_site}]},
        headers={"If-Match": '"0"'},
    )
    assert refused.status_code == 422
    assert refused.json()["errors"][0]["code"] == "site_not_found"


async def test_only_identity_managers_see_or_change_the_list(world: World) -> None:
    assert (await world.call("GET", PATH, world.a, world.a.tech)).status_code == 403
    put = await world.call(
        "PUT", PATH, world.a, world.a.tech, json={"entries": []}, headers={"If-Match": '"0"'}
    )
    assert put.status_code == 403


async def test_the_sign_in_log_shows_the_place_read_now_from_the_address(world: World) -> None:
    """D-170: internal until its range is mapped, then the site; erased address, no place."""
    site = await _site(world)
    event = await _event(world, world.a, outcome="success", ago=timedelta(minutes=5))

    async def place() -> object:
        listed = await world.call("GET", "/identity/sign-ins", world.a)
        assert listed.status_code == 200, listed.text
        (item,) = [i for i in listed.json()["items"] if i["id"] == str(event)]
        return item["place"]

    assert await place() == {"kind": "internal", "site_id": None, "city": None, "country": None}
    mapped = await world.call(
        "PUT",
        PATH,
        world.a,
        json={"entries": [{"network": "192.0.2.0/24", "site_id": site}]},
        headers={"If-Match": '"0"'},
    )
    assert mapped.status_code == 200, mapped.text
    assert await place() == {"kind": "site", "site_id": site, "city": None, "country": None}
    conn = await asyncpg.connect(world.db.admin_url)
    try:  # what the GDPR erasure job does to the row
        await conn.execute("UPDATE sign_in_events SET ip = NULL WHERE id = $1", event)
    finally:
        await conn.close()
    assert await place() is None
