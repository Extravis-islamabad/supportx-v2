# ruff: noqa: F811 - the identity world fixture is imported and re-used by name in every test
"""Verified e-mail domains (WP-057 S5d, REQ-SEC-010; lane B's and the coordinator's conditions).

- AC1: a domain is verified only once its TXT record is found; a missing record leaves it
  pending, and DNS that can't be asked is its own labelled outcome, never "not found".
- AC2: a second tenant may add the same domain but never verify it while another holds it.
- Keycloak follows our rows: verified marks the organisation's domain verified; a lapse (3 failed
  checks over at least 72 hours, never sooner) or a delete removes it from the organisation.
- Only the token's hash is stored; the record's value is in the add answer once.
- The tenant's own rows only (RLS); every write audited; a manual verify asks for a reason.
"""

import uuid
from datetime import timedelta
from typing import Any

import asyncpg
import pytest

from app.core.tenancy import TenantContext
from app.modules.identity_access.domain import verified_domains as rules
from app.modules.identity_access.infra.models import VerifiedDomain
from app.modules.identity_access.service import verified_domains as domains
from app.shared.clock import system_clock
from tests.app_state import set_state
from tests.db.test_identity_api import World, world  # noqa: F401 - the fixture, reused

pytestmark = pytest.mark.db

BASE = "/identity/domains"


class Dns:
    """TXT records by name; `down` makes every lookup fail as unreachable."""

    def __init__(self) -> None:
        self.records: dict[str, list[str]] = {}
        self.down = False

    async def lookup(self, name: str) -> list[str]:
        if self.down:
            raise rules.DnsUnreachable
        return list(self.records.get(name, []))


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> Dns:
    fake = Dns()
    monkeypatch.setattr(domains, "resolver", fake.lookup)
    return fake


async def _sql(world: World, statement: str, *args: Any) -> list[asyncpg.Record]:  # noqa: ANN401
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        return list(await conn.fetch(statement, *args))
    finally:
        await conn.close()


async def _add(world: World, org: Any, domain: str) -> dict[str, Any]:  # noqa: ANN401
    made = await world.call(
        "POST", BASE, org, json={"domain": domain}, headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


def _publish(dns: Dns, added: dict[str, Any]) -> None:
    dns.records[added["record_name"]] = ["v=spf1 -all", added["record_value"]]


async def _sync(world: World, org: Any, domain_id: str, *, multi_tenant: bool = True) -> None:  # noqa: ANN401
    """What the outbox consumer does after a verify or un-verify."""
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        row = await session.get(VerifiedDomain, uuid.UUID(domain_id))
        assert row is not None
        await domains.sync_one(session, world.admin, row, multi_tenant=multi_tenant)


def _kc_domains(world: World, org: Any) -> dict[str, Any]:  # noqa: ANN401
    found = world.admin.orgs[str(org.tenant)]
    return {d["name"]: d for d in found.raw.get("domains") or []}


async def test_a_domain_is_verified_only_once_its_record_is_found(world: World, dns: Dns) -> None:
    """AC1, and the token kept as its hash only."""
    added = await _add(world, world.a, "Acme-Proof.test")
    assert (added["domain"], added["state"]) == ("acme-proof.test", "pending")
    assert added["record_name"] == "_supportx.acme-proof.test"
    token = added["record_value"].removeprefix(rules.RECORD_PREFIX)
    (row,) = await _sql(world, "SELECT token_digest FROM verified_domains WHERE id = $1",
                        uuid.UUID(added["id"]))  # fmt: skip
    assert bytes(row["token_digest"]) == rules.digest_of(token)
    listed = await world.call("GET", BASE, world.a)
    assert "record_value" not in listed.text  # shown once
    assert token not in listed.text
    check = f"{BASE}/{added['id']}/check"
    missing = await world.call("POST", check, world.a)
    assert (missing.json()["outcome"], missing.json()["domain"]["state"]) == (
        "not_found",
        "pending",
    )
    dns.down = True
    unreachable = await world.call("POST", check, world.a)
    assert unreachable.json()["outcome"] == "dns_unreachable"  # never "not found"
    dns.down = False
    _publish(dns, added)
    found = await world.call("POST", check, world.a)
    assert (found.json()["outcome"], found.json()["domain"]["state"]) == ("found", "verified")
    assert found.json()["domain"]["verified_by_method"] == "dns"
    # Keycloak follows: the organisation's domain is verified (the consumer's work).
    await _sync(world, world.a, added["id"])
    assert _kc_domains(world, world.a)["acme-proof.test"]["verified"] is True


async def test_a_second_tenant_never_verifies_a_domain_another_holds(
    world: World, dns: Dns
) -> None:
    """AC2: B may add it (pending), but its proof finds it held: 409 code, no tenant named."""
    mine = await _add(world, world.a, "held.test")
    _publish(dns, mine)
    assert (await world.call("POST", f"{BASE}/{mine['id']}/check", world.a)).json()["outcome"] == (
        "found"
    )
    theirs = await _add(world, world.b, "held.test")
    _publish(dns, theirs)  # even with B's own record published
    tried = await world.call("POST", f"{BASE}/{theirs['id']}/check", world.b)
    assert tried.json()["outcome"] == domains.ELSEWHERE
    assert tried.json()["domain"]["state"] == "pending"
    assert str(world.a.tenant) not in tried.text
    vouched = await world.call(
        "POST",
        f"{BASE}/{theirs['id']}/verify",
        world.b,
        json={"reason": "Our own domain"},
        headers={"If-Match": f'"{tried.json()["domain"]["version"]}"'},
    )
    assert (vouched.status_code, vouched.json()["code"]) == (409, domains.ELSEWHERE)


async def test_a_lost_record_lapses_only_after_three_failures_over_72_hours(
    world: World, dns: Dns
) -> None:
    """Lane B (3): a DNS hiccup never un-verifies; a lapse removes the Keycloak domain (B (2))."""
    added = await _add(world, world.a, "lapsing.test")
    _publish(dns, added)
    await world.call("POST", f"{BASE}/{added['id']}/check", world.a)
    await _sync(world, world.a, added["id"])
    assert "lapsing.test" in _kc_domains(world, world.a)
    dns.records.clear()
    start = system_clock.now()
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        row = await session.get(VerifiedDomain, uuid.UUID(added["id"]))
        assert row is not None
        for hours in (0, 24, 48):  # three failures, but only 48 hours apart
            await domains.check(session, row, now=start + timedelta(hours=hours))
        assert row.state == "verified"
        await domains.check(session, row, now=start + timedelta(hours=73))
        assert row.state == "lapsed"
    await _sync(world, world.a, added["id"], multi_tenant=False)
    # One organisation per realm: the domain stays (an SSO set-up's routing with it), unverified.
    assert _kc_domains(world, world.a)["lapsing.test"]["verified"] is False
    await _sync(world, world.a, added["id"], multi_tenant=True)
    assert "lapsing.test" not in _kc_domains(world, world.a)  # shared realm: removed, never squats


async def test_a_manual_verify_needs_a_reason_and_is_audited(world: World, dns: Dns) -> None:
    """The coordinator's on-prem fallback: no DNS to ask, an admin vouches, audited."""
    dns.down = True
    added = await _add(world, world.a, "offline.test")
    path = f"{BASE}/{added['id']}/verify"
    etag = {"If-Match": f'"{added["version"]}"'}
    short = await world.call("POST", path, world.a, json={"reason": ""}, headers=etag)
    assert short.status_code == 422
    done = await world.call(
        "POST", path, world.a, json={"reason": "Air-gapped; checked by phone"}, headers=etag
    )
    assert done.status_code == 200, done.text
    assert (done.json()["state"], done.json()["verified_by_method"]) == ("verified", "manual")
    rows = await _sql(
        world,
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = $2"
        " AND outcome = 'done'",  # the refused empty reason is audited too, as failed
        world.a.tenant,
        "identity.domain_verified_manually",
    )
    assert rows[0]["n"] == 1


async def test_domains_no_company_can_own_are_refused_and_a_domain_is_added_once(
    world: World, dns: Dns
) -> None:
    del dns
    for raw, code in (
        ("gmail.com", "domain_public_mail"),
        ("co.uk", "domain_public_suffix"),
        ("intranet", "domain_single_label"),
    ):
        refused = await world.call(
            "POST", BASE, world.a, json={"domain": raw},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )  # fmt: skip
        assert refused.status_code == 422, refused.text
        assert refused.json()["errors"][0]["code"] == code
    await _add(world, world.a, "once.test")
    again = await world.call(
        "POST", BASE, world.a, json={"domain": "ONCE.test"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )  # fmt: skip
    assert (again.status_code, again.json()["code"]) == (409, "domain_already_added")


async def test_a_tenant_sees_and_touches_its_own_domains_only(world: World, dns: Dns) -> None:
    del dns
    mine = await _add(world, world.a, "private.test")
    theirs = await world.call("GET", BASE, world.b)
    assert "private.test" not in theirs.text
    reach = await world.call("POST", f"{BASE}/{mine['id']}/check", world.b)
    assert reach.status_code == 404
    gone = await world.call(
        "DELETE", f"{BASE}/{mine['id']}", world.b, headers={"If-Match": f'"{mine["version"]}"'}
    )
    assert gone.status_code == 404
    removed = await world.call(
        "DELETE", f"{BASE}/{mine['id']}", world.a, headers={"If-Match": f'"{mine["version"]}"'}
    )
    assert removed.status_code == 204, removed.text


async def test_a_manual_verify_is_refused_on_a_multi_tenant_installation(
    world: World,
    dns: Dns,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lane B's #569 review: on a shared realm only the DNS proof counts (D-098)."""
    dns.down = True
    added = await _add(world, world.a, "claimed.test")
    shared = world.app.state.settings.model_copy(update={"multi_tenant": True})
    set_state(monkeypatch, world.app.state, "settings", shared)
    refused = await world.call(
        "POST",
        f"{BASE}/{added['id']}/verify",
        world.a,
        json={"reason": "Ours, honestly"},
        headers={"If-Match": f'"{added["version"]}"'},
    )
    assert (refused.status_code, refused.json()["code"]) == (
        403,
        "domain_manual_verify_not_allowed",
    )
    (row,) = await _sql(
        world, "SELECT state FROM verified_domains WHERE id = $1", uuid.UUID(added["id"])
    )
    assert row["state"] == "pending"


async def test_without_a_lookup_installed_nothing_lapses(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The coordinator: with no resolver configured (an air-gapped host), a check says automatic
    checking isn't possible (never a network fault), and that never counts towards a lapse."""
    monkeypatch.setattr(domains, "resolver", domains._no_resolver)  # noqa: SLF001 - the default
    added = await _add(world, world.a, "unavailable.test")
    checked = await world.call("POST", f"{BASE}/{added['id']}/check", world.a)
    assert checked.json()["outcome"] == "dns_check_unavailable"
    vouched = await world.call(
        "POST",
        f"{BASE}/{added['id']}/verify",
        world.a,
        json={"reason": "Single-tenant, ours"},
        headers={"If-Match": f'"{checked.json()["domain"]["version"]}"'},
    )
    assert vouched.status_code == 200, vouched.text
    start = system_clock.now()
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        row = await session.get(VerifiedDomain, uuid.UUID(added["id"]))
        assert row is not None
        for hours in (0, 48, 96):
            await domains.check(session, row, now=start + timedelta(hours=hours))
        assert (row.state, row.failure_count) == ("verified", 0)
