"""The IP allow-lists' screen API (REQ-SEC-034; WP-057 S1a; the coordinator's conditions).

- AC2: a list that would shut out the admin saving it is refused at that list, with their
  address; the API list counts only when they save with an API key.
- Every change is audited with the lists before and after, and emits the settings event.
- Wrong entries are refused at their list with the entry; If-Match as every setting; only
  identity managers see or change them.

The test client calls from 127.0.0.1 (httpx's ASGI transport).
"""

import json

from tests.db.test_identity_api import World, _admin_rows, world

__all__ = ["world"]  # the fixture, re-used

PATH = "/identity/network-rules"
OFFICE = "10.20.0.0/16"


def _lists(
    console: list[str], portal: list[str] | None = None, api: list[str] | None = None
) -> dict[str, list[str]]:
    return {"console_ip_allow": console, "portal_ip_allow": portal or [], "api_ip_allow": api or []}


async def test_req_sec_034_ac2_a_list_that_shuts_you_out_is_refused(world: World) -> None:
    shown = await world.call("GET", PATH, world.a)
    assert shown.status_code == 200, shown.text
    assert shown.json() == {**_lists([]), "your_address": "127.0.0.1", "version": 0}
    refused = await world.call(
        "PUT", PATH, world.a, json=_lists([OFFICE]), headers={"If-Match": '"0"'}
    )
    assert refused.status_code == 422, refused.text
    (error,) = refused.json()["errors"]
    assert (error["field"], error["code"]) == ("console_ip_allow", "ip_allow_locks_you_out")
    assert error["params"] == {"address": "127.0.0.1"}
    # The portal's list never locks the admin out of the console.
    portal_only = await world.call(
        "PUT", PATH, world.a, json=_lists([], [OFFICE]), headers={"If-Match": '"0"'}
    )
    assert portal_only.status_code == 200, portal_only.text


async def test_a_change_is_audited_with_before_and_after_and_emits_the_event(world: World) -> None:
    saved = await world.call(
        "PUT",
        PATH,
        world.a,
        json=_lists(["127.0.0.0/8", OFFICE, "2001:db8::/32"], ["192.0.2.7"]),
        headers={"If-Match": '"0"'},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["console_ip_allow"] == ["127.0.0.0/8", OFFICE, "2001:db8::/32"]
    assert body["portal_ip_allow"] == ["192.0.2.7/32"]  # a single address, as its range
    assert (body["version"], saved.headers["ETag"]) == (1, '"1"')
    stale = await world.call("PUT", PATH, world.a, json=_lists([]), headers={"If-Match": '"0"'})
    assert stale.status_code == 409
    (entry,) = await _admin_rows(
        world.db,
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2"
        " AND outcome = 'done'",  # the stale attempt is audited too, as failed
        world.a.tenant,
        "identity.network_rules_changed",
    )
    details = json.loads(entry["details"])
    assert details["changed_fields"] == ["console_ip_allow", "portal_ip_allow"]
    assert details["before"]["console_ip_allow"] == []
    assert details["after"]["portal_ip_allow"] == ["192.0.2.7/32"]
    events = await _admin_rows(
        world.db,
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2",
        world.a.tenant,
        "identity_access.identity_settings.changed",
    )
    assert len(events) == 1
    # The other tenant's lists are untouched (RLS).
    other = await world.call("GET", PATH, world.b)
    assert (other.json()["console_ip_allow"], other.json()["version"]) == ([], 0)


async def test_a_wrong_entry_is_refused_at_its_list(world: World) -> None:
    refused = await world.call(
        "PUT",
        PATH,
        world.a,
        json=_lists(["127.0.0.0/8"], ["0.0.0.0/0"], ["not-a-range"]),
        headers={"If-Match": '"0"'},
    )
    assert refused.status_code == 422
    errors = {e["field"]: e for e in refused.json()["errors"]}
    assert errors["portal_ip_allow"]["code"] == "ip_allow_everything"
    assert errors["api_ip_allow"]["params"] == {"entry": "not-a-range"}


async def test_only_identity_managers_see_or_change_the_lists(world: World) -> None:
    assert (await world.call("GET", PATH, world.a, world.a.tech)).status_code == 403
    put = await world.call(
        "PUT", PATH, world.a, world.a.tech, json=_lists([]), headers={"If-Match": '"0"'}
    )
    assert put.status_code == 403
