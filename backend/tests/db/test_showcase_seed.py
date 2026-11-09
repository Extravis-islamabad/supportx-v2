"""The showcase seed (D-124 (5)): only `showcase`, through the API, once, nobody else's data."""

import asyncio
import json
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any

import asyncpg
import httpx
import pytest

from app.core.config import Settings
from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.audit.infra.signing import LocalSigner, new_key_config, trusted_keys
from app.modules.audit.service.integrity import seal, verify
from conftest import create_tenant, make_settings
from tooling import db_testing
from tooling import showcase_lane_a as lane_a
from tooling import showcase_seed as seed

pytestmark = pytest.mark.db


class FakeKeycloak:
    """Just the admin API calls the seed makes, with state, so a second run finds everything."""

    def __init__(self) -> None:
        self.orgs: list[dict[str, Any]] = []
        self.users: dict[str, dict[str, Any]] = {}
        self.roles: dict[str, set[str]] = {}
        self.members: dict[str, set[str]] = {}
        self.passwords: dict[str, str] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:  # noqa: C901, PLR0911, PLR0912 - one branch per call
        path = request.url.path.removeprefix("/admin/realms/supportx")
        method = request.method
        if request.url.path == "/realms/master/protocol/openid-connect/token":
            return httpx.Response(200, json={"access_token": "t"})
        if path == "/organizations" and method == "GET":
            # Like Keycloak: `search` matches the name (exactly with exact=true), never the alias.
            wanted = request.url.params.get("search", "")
            exact = request.url.params.get("exact") == "true"
            found = [
                o for o in self.orgs if (o["name"] == wanted if exact else wanted in o["name"])
            ]
            # Brief answers, like Keycloak's search: no attributes.
            brief = [{k: v for k, v in o.items() if k != "attributes"} for o in found]
            return httpx.Response(200, json=brief)
        if path.startswith("/organizations/") and path.count("/") == 2 and method == "GET":
            org = next(o for o in self.orgs if o["id"] == path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=org)
        if path == "/organizations" and method == "POST":
            org = {**json.loads(request.content), "id": "org-1"}
            self.orgs.append(org)
            self.members["org-1"] = set()
            return httpx.Response(201, headers={"Location": "/organizations/org-1"})
        if path == "/users" and method == "GET":
            email = request.url.params["email"]
            found = [u for u in self.users.values() if u["email"] == email]
            return httpx.Response(200, json=found)
        if path == "/users" and method == "POST":
            body = json.loads(request.content)
            user_id = str(uuid.uuid4())
            self.users[user_id] = {**body, "id": user_id}
            self.roles[user_id] = set()
            return httpx.Response(201, headers={"Location": f"/users/{user_id}"})
        if path.endswith("/credentials"):
            user_id = path.split("/")[2]
            held = [{"type": "password"}] if user_id in self.passwords else []
            return httpx.Response(200, json=held)
        if path.endswith("/reset-password"):
            self.passwords[path.split("/")[2]] = json.loads(request.content)["value"]
            return httpx.Response(204)
        if path.startswith("/roles/"):
            return httpx.Response(200, json={"name": path.rsplit("/", 1)[-1]})
        if path.endswith("/role-mappings/realm"):
            user_id = path.split("/")[2]
            if method == "GET":
                return httpx.Response(200, json=[{"name": r} for r in self.roles[user_id]])
            self.roles[user_id] |= {r["name"] for r in json.loads(request.content)}
            return httpx.Response(204)
        if path.endswith("/members"):
            org_id = path.split("/")[2]
            if method == "GET":
                return httpx.Response(200, json=[{"id": m} for m in self.members[org_id]])
            self.members[org_id].add(json.loads(request.content))
            return httpx.Response(201)
        return httpx.Response(404, json={"error": f"{method} {path}"})


async def _counts(url: str, tenant: uuid.UUID) -> dict[str, int]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            return {
                table: await conn.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed names
                for table in ("users", "work_items", "sites", "support_groups", "dashboards")
            }
    finally:
        await conn.close()


async def _slas(url: str) -> Counter[str]:
    """Each incident's SLA policy by name; "none" when it has no target clock."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            rows = await conn.fetch(
                "SELECT CASE WHEN EXISTS (SELECT FROM sla_targets t WHERE t.record_id = w.id)"
                " THEN p.name ELSE 'none' END AS name FROM work_items w"
                " LEFT JOIN sla_applications a ON a.record_id = w.id"
                " LEFT JOIN sla_policies p ON p.id = a.policy_id"
                " WHERE w.type = 'incident'"
            )
    finally:
        await conn.close()
    return Counter(r["name"] for r in rows)


async def _states(url: str) -> Counter[str]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            rows = await conn.fetch(
                "SELECT type, status, technician_id, known_error_at IS NOT NULL AS known"
                " FROM work_items WHERE type <> 'release'"
            )
    finally:
        await conn.close()
    return Counter(
        f"{'' if r['type'] == 'incident' else r['type'] + ' '}{r['status']}"
        f"{'' if r['technician_id'] or r['type'] != 'incident' else ' unassigned'}"
        f"{' known error' if r['known'] else ''}"
        for r in rows
    )


async def _without_a_manager(url: str) -> int:
    """QA6-SR-01: people (and the sign-ins) left with nobody to approve their requests."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            found: int = await conn.fetchval(
                "SELECT count(*) FROM users WHERE manager_id IS NULL AND user_type = 'requester'"
            )
    finally:
        await conn.close()
    return found


async def _run(database: db_testing.ThrowawayDatabase, keycloak: FakeKeycloak) -> seed.Report:
    settings = make_settings(
        database_url=database.app_url, migration_database_url=database.migrator_url
    )
    target = seed.KeycloakTarget("http://kc", "admin", "pw", "Showcase-Pass-2026!")
    report = seed.Report()
    report.tenant = await seed.ensure_tenant(database.migrator_url)
    transport = httpx.MockTransport(keycloak.handle)
    async with httpx.AsyncClient(base_url="http://kc", transport=transport) as client:
        found = await seed.ensure_keycloak(client, target)
    report.keycloak = found.made
    await seed.fill(settings, found.subjects, report)
    report.backdated = await seed.backdate(database.migrator_url, report.made)  # step 5
    report.sla_from_creation = await seed.sla_from_creation(  # step 6
        settings, seed.TENANT_ID, report.admin_id, report.without_sla
    )
    return report


async def _by_hand(database: db_testing.ThrowawayDatabase) -> str:
    """An incident the showcase admin makes at the console (not the seed), with an edit."""
    conn = await asyncpg.connect(database.migrator_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            admin: uuid.UUID = await conn.fetchval(
                "SELECT id FROM users WHERE email = $1", seed.ADMIN.email
            )
    finally:
        await conn.close()
    settings = make_settings(
        database_url=database.app_url, migration_database_url=database.migrator_url
    )
    contexts = {admin: TenantContext(seed.TENANT_ID, admin, roles=frozenset(seed.ADMIN.roles))}
    async with seed.console_api(settings, contexts) as client:
        person = seed.Api(client, admin)  # its own helper: nothing it makes is the seed's
        record = await person.call(
            "POST",
            "/api/v1/incidents",
            json={"subject": "QA-2026-11-09 made by hand", "requester_id": str(admin)},
            idempotency=str(uuid.uuid4()),
        )
        await person.call(
            "PATCH",
            f"/api/v1/incidents/{record['id']}",
            json={"urgency": "high"},
            version=record["version"],
        )
    return str(record["id"])


async def _times_of(url: str, record_id: str) -> tuple[Any, ...]:
    """The incident's own times and every history row's time, to compare after a run."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            row = await conn.fetchrow(
                "SELECT created_at, updated_at FROM work_items WHERE id = $1", uuid.UUID(record_id)
            )
            history = await conn.fetch(
                "SELECT id, occurred_at FROM field_changes"
                " WHERE record_type = 'work_item' AND record_id = $1 ORDER BY id",
                uuid.UUID(record_id),
            )
    finally:
        await conn.close()
    assert row is not None
    return (row["created_at"], row["updated_at"], [tuple(h) for h in history])


def test_a_weak_password_is_named_before_keycloak_is_asked() -> None:
    assert seed.password_problem("short") == "must be set, 12 characters or more"
    assert seed.password_problem("0123456789abcdef") == (
        "needs an upper-case letter, a special character"
    )
    assert seed.password_problem("Showcase-Pass-2026!") is None


def test_refuses_every_slug_but_showcase(production_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    for slug in ("demo", "other", "showcase2", ""):
        assert seed.refuse(slug, settings) is not None
    assert seed.refuse("showcase", settings) is None
    assert seed.refuse("showcase", production_settings()) is not None


async def _audit_chain(app_url: str) -> str:
    """Seal the showcase tenant's queued audit entries and verify its whole hash chain."""
    database = Database.from_settings(make_settings(database_url=app_url))
    assert database is not None
    signer = LocalSigner.from_config(new_key_config("showcase-test"))
    try:
        async with database.tenant_session(TenantContext(seed.TENANT_ID)) as session:
            await seal(session, 500)
        async with database.tenant_session(TenantContext(seed.TENANT_ID)) as session:
            result = await verify(session, kind="on_demand", trusted_keys=trusted_keys("", signer))
    finally:
        await database.dispose()
    return str(result.status)


async def _shift_one_audit_entry(admin_url: str) -> str:
    """Move one showcase audit entry back a day: 'shifted', or 'refused' by the database."""
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(
            "UPDATE audit_entries SET occurred_at = occurred_at - interval '1 day'"
            " WHERE id = (SELECT id FROM audit_entries WHERE tenant_id = $1 LIMIT 1)",
            seed.TENANT_ID,
        )
    except asyncpg.PostgresError:
        return "refused"
    finally:
        await conn.close()
    return "shifted"


async def _backdating_is_consistent(url: str) -> list[str]:
    """What is wrong with the showcase dates after step 5, as readable lines (empty: fine)."""
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(seed.TENANT_ID))
        rows = await conn.fetch(
            "SELECT w.display_id, w.created_at, w.first_responded_at, w.resolved_at,"
            " w.closed_at, t.created_at AS tenant_created"
            " FROM work_items w JOIN tenants t ON t.id = w.tenant_id"
            " WHERE w.tenant_id = $1 AND w.type = 'incident'",  # what step 5 spreads
            seed.TENANT_ID,
        )
        history_ahead = await conn.fetchval(
            "SELECT count(*) FROM field_changes f JOIN work_items w ON w.id = f.record_id"
            " WHERE f.record_type = 'work_item' AND w.tenant_id = $1 AND w.type = 'incident'"
            " AND f.occurred_at < w.created_at - interval '1 second'",
            seed.TENANT_ID,
        )
    finally:
        await conn.close()
    wrong = [f"history before its incident: {history_ahead}"] if history_ahead else []
    days = {r["created_at"].date() for r in rows}
    if len(days) < 10:
        wrong.append(f"only {len(days)} distinct days")
    for r in rows:
        window = r["tenant_created"] - timedelta(days=31)
        if not window <= r["created_at"] < r["tenant_created"]:
            wrong.append(f"{r['display_id']} outside the 30 days")
        times = [r["created_at"], r["first_responded_at"], r["resolved_at"], r["closed_at"]]
        present = [t for t in times if t is not None]
        if present != sorted(present):
            wrong.append(f"{r['display_id']} times out of order")
    return wrong


def test_fills_showcase_through_the_api_once_and_leaves_other_tenants_alone(  # noqa: PLR0915 - one journey: two runs and what each must leave
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config)
    try:
        bystander = asyncio.run(create_tenant(database.migrator_url, "Bystander"))
        before = asyncio.run(_counts(database.migrator_url, bystander))
        keycloak = FakeKeycloak()
        # The technician came from the dev realm file without a password: the seed gives one.
        imported = "imported-tech"
        keycloak.users[imported] = {"id": imported, "email": seed.TECHNICIAN.email}
        keycloak.roles[imported] = set()

        first = asyncio.run(_run(database, keycloak))
        assert first.tenant == ["tenant", "subscription", "starter_catalog"]
        assert first.catalog_published == 14  # the starter catalog (D-138), with its group
        assert first.incidents == len(seed.STATES) == 60
        # QA6-DATA-01: service requests in every state, problems with known errors.
        assert first.service_requests == len(lane_a.REQUESTS) == 7
        assert first.problems == len(lane_a.PROBLEMS) == 3
        assert first.rules == len(lane_a.RULES) == 3
        assert first.managers == sum(p.user_type == "requester" for p in seed.PEOPLE) + 1
        assert first.dashboard
        # QA6-DATA-01: knowledge and releases to show, not empty modules.
        assert first.articles == len(seed.KB_ARTICLES) == 5
        assert first.releases == len(seed.RELEASES) == 2
        assert first.backdated == 70  # spread over the past 30 days (choice (b)); not releases
        assert asyncio.run(_backdating_is_consistent(database.migrator_url)) == []
        assert asyncio.run(_audit_chain(database.app_url)) == "passed"  # never shifted
        # The password is the environment's, set only on the users made here.
        assert keycloak.passwords == dict.fromkeys(keycloak.users, "Showcase-Pass-2026!")
        assert any(f"password {seed.TECHNICIAN.email}" == m for m in first.keycloak)
        keycloak.passwords[imported] = "Changed-By-Hand-1!"  # never overwritten
        assert {u["email"] for u in keycloak.users.values()} == {s.email for s in seed.SIGN_INS}
        counts = asyncio.run(_counts(database.migrator_url, seed.TENANT_ID))
        assert counts["users"] == len(seed.PEOPLE) + len(seed.SIGN_INS)
        assert counts["work_items"] == 70 + len(seed.RELEASES)
        assert asyncio.run(_without_a_manager(database.migrator_url)) == 0
        # Named SLAs with live countdowns, not "No SLA applies" (QA9, Haider): every incident
        # has targets, the urgent ones and the network ones on the showcase's own policies.
        assert first.sla_policies == len(lane_a.SLA_POLICIES) == 2
        assert first.sla_from_creation == 0  # every new incident took its SLA when created
        slas = asyncio.run(_slas(database.migrator_url))
        assert slas["none"] == 0
        assert slas["Critical and high incidents"] == 10  # p1 and p2
        assert slas["Network and access faults"] > 0
        assert asyncio.run(_states(database.migrator_url)) == {
            "service_request awaiting_approval": 2,
            "service_request in_progress": 1,
            "service_request fulfilled": 1,
            "service_request closed": 1,
            "service_request rejected": 1,
            "service_request canceled": 1,
            "problem assigned known error": 2,  # the creator owns a new problem (#267)
            "problem assigned": 1,
            "new unassigned": 10,
            "assigned": 14,
            "in_progress": 12,
            "awaiting_requester": 6,
            "resolved": 10,
            "closed": 8,
        }

        # QA 2026-11-09 (INC-62): a record someone else made keeps its times and its history.
        by_hand = asyncio.run(_by_hand(database))
        untouched = asyncio.run(_times_of(database.migrator_url, by_hand))
        assert untouched[2], "the edit wrote history to compare"

        second = asyncio.run(_run(database, keycloak))
        assert asyncio.run(_times_of(database.migrator_url, by_hand)) == untouched
        assert (
            second.tenant,
            second.keycloak,
            second.incidents,
            second.dashboard,
            second.catalog_published,
            second.articles,
            second.releases,
            second.service_requests,
            second.problems,
            second.managers,
            second.rules,
            second.sla_policies,
            second.sla_from_creation,
        ) == ([], [], 0, False, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        assert second.backdated == 0  # nothing made now, so nothing moved
        assert asyncio.run(_audit_chain(database.app_url)) == "passed"
        # The check has teeth: an audit entry shifted as step 5 must never do is caught (or the
        # database refuses the change outright).
        if asyncio.run(_shift_one_audit_entry(database.admin_url)) == "shifted":
            assert asyncio.run(_audit_chain(database.app_url)) == "failed"
        assert asyncio.run(_counts(database.migrator_url, seed.TENANT_ID)) == {
            **counts,
            "work_items": counts["work_items"] + 1,  # the one made by hand
        }
        assert asyncio.run(_counts(database.migrator_url, bystander)) == before
        assert keycloak.passwords[imported] == "Changed-By-Hand-1!"
    finally:
        db_testing.destroy(db_config, database)


# --- step 6: SLAs from creation for incidents made before any SLA (Haider, 2026-11-09) --------

_SLA_ROWS = """
WITH r AS (SELECT unnest($1::uuid[]) AS id),
t AS (SELECT s.id FROM sla_targets s JOIN r ON s.record_id = r.id),
e AS (DELETE FROM sla_escalation_runs WHERE target_id IN (SELECT id FROM t)),
p AS (DELETE FROM sla_pauses WHERE target_id IN (SELECT id FROM t)),
d AS (DELETE FROM sla_targets WHERE id IN (SELECT id FROM t))
DELETE FROM sla_applications WHERE record_id IN (SELECT id FROM r)
"""


async def _hand_made(database: db_testing.ThrowawayDatabase) -> uuid.UUID:
    """An incident a person makes through the API: the technician, a seed subject and requester."""
    settings = make_settings(
        database_url=database.app_url, migration_database_url=database.migrator_url
    )
    conn = await asyncpg.connect(database.admin_url)
    try:
        tech = await conn.fetchval(
            "SELECT id FROM users WHERE tenant_id = $1 AND email = $2",
            seed.TENANT_ID,
            seed.TECHNICIAN.email,
        )
        requester = await conn.fetchval(
            "SELECT requester_id FROM work_items WHERE tenant_id = $1 AND type = 'incident'"
            " AND subject = $2 LIMIT 1",
            seed.TENANT_ID,
            seed.SUBJECTS[0][0],
        )
    finally:
        await conn.close()
    contexts = {tech: TenantContext(seed.TENANT_ID, tech, roles=frozenset(seed.TECHNICIAN.roles))}
    async with seed.console_api(settings, contexts) as client:
        made = await seed.Api(client, tech).call(
            "POST",
            "/api/v1/incidents",
            json={
                "subject": seed.SUBJECTS[0][0],
                "requester_id": str(requester),
                "confirm_lose_access": True,  # outside their group: they keep following
                "keep_following": True,
            },
            idempotency=str(uuid.uuid4()),
        )
    return uuid.UUID(made["id"])


async def _row_and_history(url: str, record_id: uuid.UUID) -> tuple[Any, ...]:
    """A record's times, SLA columns and history, to prove nothing about it changed."""
    conn = await asyncpg.connect(url)
    try:
        row = await conn.fetchrow(
            "SELECT version, created_at, updated_at, sla_policy_id, resolution_due_at"
            " FROM work_items WHERE id = $1",
            record_id,
        )
        history = await conn.fetch(
            "SELECT id, occurred_at FROM field_changes WHERE record_id = $1 ORDER BY id", record_id
        )
        slas = await conn.fetchval(
            "SELECT count(*) FROM sla_targets WHERE record_id = $1", record_id
        )
    finally:
        await conn.close()
    assert row is not None
    return (tuple(row), [tuple(h) for h in history], slas)


async def _as_before_slas(url: str, extra: Sequence[uuid.UUID] = ()) -> tuple[uuid.UUID, uuid.UUID]:
    """Test data only: two seeded incidents as the shared stack's older ones are, with no SLA.

    One urgent (4 h to resolve) and open since its backdated creation days ago; one answered in
    5 and resolved in 20 minutes. Returns (open, quick).
    """
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            open_id = await conn.fetchval(
                "SELECT id FROM work_items WHERE type = 'incident' AND status_category = 'open'"
                " AND priority IN ('p1', 'p2') AND created_at < now() - interval '2 days'"
                " ORDER BY display_id LIMIT 1"
            )
            quick_id = await conn.fetchval(
                "SELECT id FROM work_items WHERE type = 'incident' AND status = 'resolved'"
                " ORDER BY display_id LIMIT 1"
            )
            ids = [open_id, quick_id, *extra]
            assert None not in ids, ids
            await conn.execute(_SLA_ROWS, ids)
            await conn.execute(
                "UPDATE work_items SET sla_policy_id = NULL, first_response_due_at = NULL,"
                " resolution_due_at = NULL, first_response_sla_state = NULL,"
                " resolution_sla_state = NULL, first_response_breached = false,"
                " resolution_breached = false WHERE id = ANY($1::uuid[])",
                ids,
            )
            await conn.execute(
                "UPDATE work_items SET first_responded_at = created_at + interval '5 minutes',"
                " resolved_at = created_at + interval '20 minutes' WHERE id = $1",
                quick_id,
            )
    finally:
        await conn.close()
    return open_id, quick_id


async def _clocks(url: str, ids: Sequence[uuid.UUID]) -> dict[tuple[uuid.UUID, str], str]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            rows = await conn.fetch(
                "SELECT record_id, kind, met_at, breached_at FROM sla_targets t"
                " WHERE record_id = ANY($1::uuid[])",
                list(ids),
            )
    finally:
        await conn.close()
    return {
        (r["record_id"], r["kind"]): "breached"
        if r["breached_at"] is not None
        else ("met" if r["met_at"] is not None else "running")
        for r in rows
    }


async def _audit(url: str, tenant: uuid.UUID) -> list[tuple[Any, ...]]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT id, action, object_id, occurred_at FROM audit_entries WHERE tenant_id = $1",
            tenant,
        )
    finally:
        await conn.close()
    return sorted(tuple(r) for r in rows)


def test_older_incidents_get_their_sla_from_creation_once(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config)
    try:
        bystander = asyncio.run(create_tenant(database.migrator_url, "Bystander"))
        keycloak = FakeKeycloak()
        keycloak.users["imported-tech"] = {"id": "imported-tech", "email": seed.TECHNICIAN.email}
        keycloak.roles["imported-tech"] = set()
        asyncio.run(_run(database, keycloak))
        # A person's own incident, the worst case: a seed subject and requester, made by the
        # technician (not the seed's admin), and with no SLA either. Step 6 never touches it.
        hand_made = asyncio.run(_hand_made(database))
        open_id, quick_id = asyncio.run(_as_before_slas(database.admin_url, extra=[hand_made]))
        hand_before = asyncio.run(_row_and_history(database.admin_url, hand_made))
        audit_before = asyncio.run(_audit(database.admin_url, seed.TENANT_ID))
        bystander_before = asyncio.run(_counts(database.migrator_url, bystander))

        again = asyncio.run(_run(database, keycloak))
        assert again.sla_from_creation == 2  # not the hand-made one
        assert asyncio.run(_row_and_history(database.admin_url, hand_made)) == hand_before
        clocks = asyncio.run(_clocks(database.migrator_url, [open_id, quick_id]))
        # From creation, never from now: open for days, its 4 hours ran out long ago.
        assert clocks[(open_id, "resolution")] == "breached"
        assert clocks[(quick_id, "first_response")] == "met"
        assert clocks[(quick_id, "resolution")] == "met"
        # New audit entries, one per incident; the old ones are exactly as they were.
        audit_after = asyncio.run(_audit(database.admin_url, seed.TENANT_ID))
        assert set(audit_before) <= set(audit_after)
        added = [e for e in audit_after if e not in set(audit_before)]
        applied = [e for e in added if e[1] == "incident.sla_applied_from_creation"]
        assert sorted(e[2] for e in applied) == sorted(str(i) for i in (open_id, quick_id))
        assert asyncio.run(_audit_chain(database.app_url)) == "passed"
        history = asyncio.run(_history_sources(database.migrator_url, open_id))
        assert "api" in history

        # A re-run changes nothing; another tenant is never touched, nor can be asked for.
        third = asyncio.run(_run(database, keycloak))
        assert third.sla_from_creation == 0
        assert asyncio.run(_clocks(database.migrator_url, [open_id, quick_id])) == clocks
        assert asyncio.run(_counts(database.migrator_url, bystander)) == bystander_before
        settings = make_settings(database_url=database.app_url)
        with pytest.raises(seed.SeedError):
            asyncio.run(seed.sla_from_creation(settings, bystander, uuid.uuid4(), [open_id]))
    finally:
        db_testing.destroy(db_config, database)


async def _history_sources(url: str, record_id: uuid.UUID) -> set[str]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            rows = await conn.fetch(
                "SELECT source FROM field_changes WHERE record_id = $1", record_id
            )
    finally:
        await conn.close()
    return {r["source"] for r in rows}
