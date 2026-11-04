"""`make showcase-seed`: Showcase Company, a tenant for demos (D-124 (5)).

Fills the tenant with the slug `showcase` and nothing else: never `demo` (the e2e suite's tenant)
or `other`. Any other slug is refused. Idempotent: what exists is left alone, what is missing is
added, nothing is ever updated or deleted (CLAUDE.md rule 5h).

1. The tenant, its IT desk and an Enterprise plan, as the migrator (like `make db-seed`).
2. Keycloak: the organization `showcase` and two sign-ins, an admin and a technician, through
   the admin API (the dev realm file lists them for fresh installs, without passwords). Their
   password comes from `SUPPORTX_SHOWCASE_PASSWORD` and is only set when a user is created here.
3. Both are signed in once through the first-sign-in path (`provision_user`), so their records
   and role assignments are exactly what a real first login makes.
4. Everything else goes through the public API, in process, as the showcase admin (P2): so
   permissions, validation, history, events and RLS apply as for a person at the console. Sites,
   groups and their members, people, incidents in realistic states with replies, and a shared
   dashboard.

5. Dates (the product owner's choice (b), 2026-11-04): the API never backdates, so every record
   would carry the day the seed ran, with flat trend charts and "0 min to resolve". One SQL step
   outside the API, in this tenant only (`app.tenant_id` set, RLS applies), then spreads the
   incidents over the 30 days before the tenant was created. Each incident moves by one delta,
   applied to every timestamp of the incident and of its rows (conversation, tasks, worklogs,
   followers, SLA applications, targets, pauses and escalation runs, field history). The order
   of its times (created <= first response <= resolved) and its SLA clocks stay as they were.
   The target time is fixed (the tenant's creation minus a per-incident offset), so a re-run
   computes a delta of zero: idempotent. This step is dev tooling; no API or product code path
   ever backdates.
"""

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import asyncpg
import httpx
from fastapi import FastAPI, Request

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.modules import ModuleRegistry, discover_modules
from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from app.modules.identity_access.domain.identity import Identity
from app.modules.identity_access.service.users import provision_user
from app.modules.licensing import Edition, SubscriptionPlan, apply_subscription
from tooling.keycloak_theme import admin_token

SLUG = "showcase"
TENANT_ID = uuid.UUID("01900000-0000-7000-8000-00000005ca5e")
TENANT_NAME = "Showcase Company"
DOMAIN = "showcase.test"
PLAN = SubscriptionPlan(edition=Edition.ENTERPRISE, starts_at=datetime(2026, 1, 1, tzinfo=UTC))
PASSWORD_ENV = "SUPPORTX_SHOWCASE_PASSWORD"  # noqa: S105 - the variable's name, not a password
# Every Idempotency-Key is derived from this, so a retried run never makes a second copy.
KEYS = uuid.UUID("5ca5e5ee-d000-4000-8000-000000000000")
SEED_HEADER = "x-showcase-seed-user"


@dataclass(frozen=True)
class SignIn:
    """A Keycloak user of the showcase organization."""

    email: str
    first_name: str
    last_name: str
    roles: tuple[str, ...]


ADMIN = SignIn("admin@showcase.test", "Sana", "Malik", ("tenant_admin", "technician"))
TECHNICIAN = SignIn("tech@showcase.test", "Omar", "Farooq", ("technician",))
SIGN_INS = (ADMIN, TECHNICIAN)

SITES = (
    ("Islamabad headquarters", "Asia/Karachi"),
    ("Dubai office", "Asia/Dubai"),
)
GROUPS = (
    ("Service desk", ("Islamabad headquarters", "Dubai office")),
    ("Network and access", ("Islamabad headquarters",)),
    ("Business applications", ("Islamabad headquarters", "Dubai office")),
)


@dataclass(frozen=True)
class Person:
    """Someone made in Admin > People (no sign-in of their own)."""

    first_name: str
    last_name: str
    email: str
    user_type: str  # technician | requester
    site: str
    groups: tuple[str, ...] = ()
    job_title: str = ""
    locale: str = "en"


PEOPLE = (
    Person(
        "Ayesha",
        "Khan",
        "ayesha.khan@showcase.test",
        "technician",
        "Islamabad headquarters",
        ("Service desk",),
        "Service desk analyst",
    ),
    Person(
        "Bilal",
        "Ahmed",
        "bilal.ahmed@showcase.test",
        "technician",
        "Islamabad headquarters",
        ("Network and access",),
        "Network engineer",
    ),
    Person(
        "Fatima",
        "Noor",
        "fatima.noor@showcase.test",
        "technician",
        "Dubai office",
        ("Service desk", "Business applications"),
        "Applications specialist",
        "ar",
    ),
    Person(
        "Hamza",
        "Ali",
        "hamza.ali@showcase.test",
        "technician",
        "Islamabad headquarters",
        ("Business applications",),
        "ERP administrator",
    ),
    Person(
        "Zainab",
        "Hussain",
        "zainab.hussain@showcase.test",
        "requester",
        "Islamabad headquarters",
        job_title="Finance manager",
    ),
    Person(
        "Usman",
        "Tariq",
        "usman.tariq@showcase.test",
        "requester",
        "Islamabad headquarters",
        job_title="Sales lead",
    ),
    Person(
        "Mariam",
        "Saeed",
        "mariam.saeed@showcase.test",
        "requester",
        "Dubai office",
        job_title="HR officer",
        locale="ar",
    ),
    Person(
        "Khalid",
        "Rahman",
        "khalid.rahman@showcase.test",
        "requester",
        "Dubai office",
        job_title="Operations director",
        locale="ar",
    ),
    Person(
        "Hira",
        "Javed",
        "hira.javed@showcase.test",
        "requester",
        "Islamabad headquarters",
        job_title="Marketing executive",
    ),
    Person(
        "Saad",
        "Qureshi",
        "saad.qureshi@showcase.test",
        "requester",
        "Islamabad headquarters",
        job_title="Procurement officer",
    ),
)
# Who sits in which group besides the people above: the two sign-ins.
SIGN_IN_GROUPS = {
    ADMIN.email: ("Service desk",),
    TECHNICIAN.email: ("Service desk", "Network and access"),
}

# (subject, group, urgency, impact). Each is logged twice, for two requesters, so lists look
# lived-in; four Arabic subjects show right-to-left text in an English list.
SUBJECTS = (
    ("Laptop will not connect to the office Wi-Fi", "Network and access", "medium", "one_person"),
    (
        "VPN drops every few minutes when working from home",
        "Network and access",
        "high",
        "one_person",
    ),
    (
        "Shared drive for Finance is read-only since this morning",
        "Network and access",
        "high",
        "team",
    ),
    ("Printer on the second floor keeps jamming", "Service desk", "low", "team"),
    ("Outlook asks for my password again and again", "Service desk", "medium", "one_person"),
    ("New starter needs a laptop and accounts on Monday", "Service desk", "medium", "one_person"),
    ("Monitor flickers after the latest update", "Service desk", "low", "one_person"),
    ("Cannot join Teams meetings with video", "Service desk", "medium", "one_person"),
    ("ERP invoice approval screen shows an error", "Business applications", "high", "team"),
    (
        "Payroll export file is missing last week's overtime",
        "Business applications",
        "critical",
        "department_or_site",
    ),
    ("CRM is very slow for the whole sales team", "Business applications", "high", "team"),
    ("Request access to the procurement module", "Business applications", "low", "one_person"),
    (
        "Website contact form stopped sending e-mails",
        "Business applications",
        "high",
        "organisation",
    ),
    ("Phone extension 214 has no dial tone", "Network and access", "medium", "one_person"),
    ("Meeting room screen does not detect HDMI", "Service desk", "low", "team"),
    ("Password reset for the HR portal", "Service desk", "medium", "one_person"),
    ("Two-factor codes arrive late on my phone", "Service desk", "medium", "one_person"),
    ("Antivirus blocked a supplier's spreadsheet", "Service desk", "medium", "one_person"),
    (
        "Backup job for the file server failed overnight",
        "Network and access",
        "critical",
        "organisation",
    ),
    ("Keyboard missing keys, need a replacement", "Service desk", "low", "one_person"),
    ("Dubai office internet is down", "Network and access", "critical", "department_or_site"),
    ("Expense claims cannot attach receipts", "Business applications", "medium", "team"),
    ("Mobile e-mail stopped syncing after a phone change", "Service desk", "medium", "one_person"),
    ("Install the drawing software for the design team", "Service desk", "low", "team"),
    ("Calendar invites show the wrong time zone", "Service desk", "medium", "one_person"),
    ("Sales dashboard numbers do not match the ERP", "Business applications", "high", "team"),
    ("الطابعة في الطابق الأول لا تطبع", "Service desk", "low", "team"),
    ("لا أستطيع الدخول إلى البريد الإلكتروني", "Service desk", "high", "one_person"),
    ("طلب صلاحية الوصول إلى نظام الموارد البشرية", "Business applications", "low", "one_person"),
    ("الشبكة بطيئة جدًا في مكتب دبي", "Network and access", "high", "department_or_site"),
)
# What happens to each incident after it is logged, by position (60 in all): a realistic mix.
STATES = (
    ("new",) * 10
    + ("assigned",) * 14
    + ("in_progress",) * 12
    + ("awaiting_requester",) * 6
    + ("resolved",) * 10
    + ("closed",) * 8
)
REPLIES = (
    "Thanks for reporting this. I'm looking into it now.",
    "Could you tell me when this started and whether anything changed on your side?",
    "We've found the cause and are applying a fix.",
)
RESOLUTION = "<p>Found the cause and fixed it; confirmed working with the requester.</p>"


def key(*parts: str) -> str:
    """A stable Idempotency-Key for one thing this seed makes."""
    return str(uuid.uuid5(KEYS, "/".join(parts)))


class SeedError(RuntimeError):
    """A step the seed cannot do; the message says which and why (never a secret)."""


# --- 1. Tenant -------------------------------------------------------------------------------


BACKDATE_DAYS = 30
# The incident and every row of it (table, how a row points at the incident `s.id`).
_BACKDATE_TARGETS = (
    ("work_items", "t.id = s.id"),
    ("work_item_conversations", "t.work_item_id = s.id"),
    ("work_item_tasks", "t.work_item_id = s.id"),
    ("work_item_worklogs", "t.work_item_id = s.id"),
    ("work_item_followers", "t.work_item_id = s.id"),
    ("sla_applications", "t.record_id = s.id"),
    ("sla_targets", "t.record_id = s.id"),
    (
        "sla_pauses",
        "t.target_id IN (SELECT g.id FROM sla_targets g WHERE g.record_id = s.id)",
    ),
    (
        "sla_escalation_runs",
        "t.target_id IN (SELECT g.id FROM sla_targets g WHERE g.record_id = s.id)",
    ),
    ("field_changes", "t.record_type = 'work_item' AND t.record_id = s.id"),
)
# Each incident's fixed target: 1 to 30 days and 0 to 8 hours before the tenant was created.
_BACKDATE_DELTAS = """
CREATE TEMP TABLE showcase_shift ON COMMIT DROP AS
SELECT w.id,
       (t.created_at
        - make_interval(days => 1 + ((w.display_number * 7) % $2)::int,
                        hours => ((w.display_number * 5) % 9)::int))
       - w.created_at AS delta
  FROM work_items w JOIN tenants t ON t.id = w.tenant_id
 WHERE w.tenant_id = $1
"""


async def backdate(migrator_url: str) -> int:
    """Step 5: spread the incidents over the past 30 days (see the module docstring).

    Returns how many incidents moved (0 on a re-run).
    """
    conn = await asyncpg.connect(migrator_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(TENANT_ID))
            await conn.execute(_BACKDATE_DELTAS, TENANT_ID, BACKDATE_DAYS)
            await conn.execute("DELETE FROM showcase_shift WHERE delta = interval '0'")
            moved: int = await conn.fetchval("SELECT count(*) FROM showcase_shift")
            if moved == 0:
                return 0
            for table, link in _BACKDATE_TARGETS:
                columns = [
                    row["column_name"]
                    for row in await conn.fetch(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_schema = 'public' AND table_name = $1"
                        " AND data_type = 'timestamp with time zone' ORDER BY column_name",
                        table,
                    )
                ]
                if not columns:
                    continue
                shift = ", ".join(f"{c} = t.{c} + s.delta" for c in columns)
                await conn.execute(
                    f"UPDATE {table} t SET {shift} FROM showcase_shift s"  # noqa: S608 - names from the fixed list above and the catalogue
                    f" WHERE t.tenant_id = $1 AND {link}",
                    TENANT_ID,
                )
            return moved
    finally:
        await conn.close()


async def ensure_tenant(migrator_url: str) -> list[str]:
    """The tenant, its IT desk and its plan, each only if absent. Returns what was made now."""
    made: list[str] = []
    conn = await asyncpg.connect(migrator_url)
    try:
        taken = await conn.fetchval(
            "SELECT id FROM tenants WHERE slug = $1 AND id <> $2", SLUG, TENANT_ID
        )
        if taken is not None:
            msg = f"the slug {SLUG!r} belongs to another tenant; nothing was changed"
            raise SeedError(msg)
        status = await conn.execute(
            "INSERT INTO tenants (id, name, slug, status) VALUES ($1, $2, $3, 'active')"
            " ON CONFLICT DO NOTHING",
            TENANT_ID,
            TENANT_NAME,
            SLUG,
        )
        if status.endswith(" 1"):
            made.append("tenant")
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(TENANT_ID))
            await conn.execute(
                "INSERT INTO desks (id, tenant_id, code, labels, is_default)"
                " VALUES (gen_random_uuid(), $1, 'it', '{\"en\": \"IT\"}'::jsonb, true)"
                " ON CONFLICT DO NOTHING",
                TENANT_ID,
            )
    finally:
        await conn.close()
    database = Database(
        create_engine(migrator_url, application_name="showcase-seed", use_null_pool=True)
    )
    try:
        async with database.tenant_session(TenantContext(TENANT_ID)) as session:
            if await apply_subscription(session, PLAN, only_if_absent=True):
                made.append("subscription")
    finally:
        await database.dispose()
    return made


# --- 2. Keycloak -----------------------------------------------------------------------------


@dataclass(frozen=True)
class KeycloakTarget:
    """Which Keycloak and realm, as whom (the bootstrap admin), and the sign-ins' password."""

    base_url: str
    user: str
    password: str = field(repr=False)
    sign_in_password: str = field(repr=False)
    realm: str = "supportx"


@dataclass(frozen=True)
class KeycloakResult:
    """Each sign-in's Keycloak user ID, and what was made now."""

    subjects: dict[str, str]
    made: list[str]


async def _ensure_user(  # noqa: PLR0913, PLR0917 - the realm call context and the person, explicit
    client: httpx.AsyncClient,
    realm: str,
    headers: dict[str, str],
    org_id: str,
    person: SignIn,
    password: str,
) -> tuple[str, list[str]]:
    """One sign-in: the user, its password where none, its roles and membership."""
    made: list[str] = []
    users = await client.get(
        f"{realm}/users", params={"email": person.email, "exact": "true"}, headers=headers
    )
    users.raise_for_status()
    if users.json():
        user_id = str(users.json()[0]["id"])
    else:
        response = await client.post(
            f"{realm}/users",
            headers=headers,
            json={
                "username": person.email,
                "email": person.email,
                "emailVerified": True,
                "enabled": True,
                "firstName": person.first_name,
                "lastName": person.last_name,
                "attributes": {"locale": ["en"]},
            },
        )
        response.raise_for_status()
        user_id = response.headers["Location"].rsplit("/", 1)[-1]
        made.append(f"user {person.email}")
    # A password only where there is none (made now, or imported from the dev realm file
    # without one): a password set or changed since is never overwritten.
    held_credentials = await client.get(f"{realm}/users/{user_id}/credentials", headers=headers)
    held_credentials.raise_for_status()
    if not any(c.get("type") == "password" for c in held_credentials.json()):
        reset = await client.put(
            f"{realm}/users/{user_id}/reset-password",
            headers=headers,
            json={"type": "password", "value": password, "temporary": False},
        )
        if reset.status_code == 400:  # noqa: PLR2004 - Keycloak's answer to a weak password
            msg = f"Keycloak refused {PASSWORD_ENV} for {person.email}: {reset.text[:200]}"
            raise SeedError(msg)
        reset.raise_for_status()
        made.append(f"password {person.email}")
    held = await client.get(f"{realm}/users/{user_id}/role-mappings/realm", headers=headers)
    held.raise_for_status()
    missing = [r for r in person.roles if r not in {h["name"] for h in held.json()}]
    if missing:
        roles = []
        for name in missing:
            role = await client.get(f"{realm}/roles/{name}", headers=headers)
            role.raise_for_status()
            roles.append(role.json())
        granted = await client.post(
            f"{realm}/users/{user_id}/role-mappings/realm", headers=headers, json=roles
        )
        granted.raise_for_status()
        made.append(f"roles {person.email}")
    members = await client.get(
        f"{realm}/organizations/{org_id}/members",
        params={"search": person.email},
        headers=headers,
    )
    members.raise_for_status()
    if not any(m.get("id") == user_id for m in members.json()):
        # Keycloak takes the user ID as a bare JSON string.
        joined = await client.post(
            f"{realm}/organizations/{org_id}/members",
            headers={**headers, "Content-Type": "application/json"},
            content=f'"{user_id}"',
        )
        if joined.status_code not in (201, 204, 409):
            joined.raise_for_status()
        made.append(f"member {person.email}")
    return user_id, made


async def ensure_keycloak(client: httpx.AsyncClient, target: KeycloakTarget) -> KeycloakResult:
    """The organization and both users with their roles and membership, each only if absent."""
    token = await admin_token(client, target.user, target.password)
    if token is None:
        msg = "Keycloak refused the bootstrap admin (SUPPORTX_KEYCLOAK_ADMIN_USER/PASSWORD)"
        raise SeedError(msg)
    headers = {"Authorization": f"Bearer {token}"}
    realm = f"/admin/realms/{target.realm}"
    made: list[str] = []

    found = await client.get(
        # Keycloak searches organizations by name, not alias: find by name, match the alias.
        f"{realm}/organizations",
        params={"search": TENANT_NAME, "exact": "true"},
        headers=headers,
    )
    found.raise_for_status()
    orgs = [o for o in found.json() if o.get("alias") == SLUG]
    if orgs:
        org_id = str(orgs[0]["id"])
        # Search answers in brief, without attributes: read the organization itself.
        whole = await client.get(f"{realm}/organizations/{org_id}", headers=headers)
        whole.raise_for_status()
        if whole.json().get("attributes", {}).get("tenant_id") != [str(TENANT_ID)]:
            msg = f"the Keycloak organization {SLUG!r} points at another tenant; nothing changed"
            raise SeedError(msg)
    else:
        response = await client.post(
            f"{realm}/organizations",
            headers=headers,
            json={
                "name": TENANT_NAME,
                "alias": SLUG,
                "enabled": True,
                "description": "Showcase tenant for demos (SupportX showcase seed)",
                "attributes": {"tenant_id": [str(TENANT_ID)]},
                "domains": [{"name": DOMAIN, "verified": False}],
            },
        )
        response.raise_for_status()
        org_id = response.headers["Location"].rsplit("/", 1)[-1]
        made.append("organization")

    subjects: dict[str, str] = {}
    for person in SIGN_INS:
        user_id, done = await _ensure_user(
            client, realm, headers, org_id, person, target.sign_in_password
        )
        made += done
        subjects[person.email] = user_id
    return KeycloakResult(subjects, made)


# --- 3. First sign-in ------------------------------------------------------------------------


async def sign_in_once(database: Database, subjects: Mapping[str, str]) -> dict[str, uuid.UUID]:
    """Each sign-in's SupportX person, made or linked as a first login would."""
    users: dict[str, uuid.UUID] = {}
    for person in SIGN_INS:
        identity = Identity(
            subject=subjects[person.email],
            email=person.email,
            display_name=f"{person.first_name} {person.last_name}",
            locale="en",
            roles=person.roles,
            memberships=(),
            keycloak_session_id=None,
        )
        provisioned = await provision_user(
            database, TENANT_ID, identity, datetime.now(UTC), client="console", reason="login"
        )
        users[person.email] = provisioned.user_id
    return users


# --- 4. Through the public API ---------------------------------------------------------------


@asynccontextmanager
async def console_api(
    settings: Settings, contexts: Mapping[uuid.UUID, TenantContext]
) -> AsyncIterator[httpx.AsyncClient]:
    """The API in process; each request acts as the person its seed header names."""
    app: FastAPI = create_app(settings, ModuleRegistry.from_specs(discover_modules()))

    async def resolve(request: Request) -> TenantContext | None:
        named = request.headers.get(SEED_HEADER)
        return None if named is None else contexts.get(uuid.UUID(named))

    async with app.router.lifespan_context(app):
        # This app object is the seed's own and is never served: only it trusts the header.
        setattr(app.state, SESSION_RESOLVER_STATE, resolve)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(transport=transport, base_url="http://seed") as client:
            yield client


class Api:
    """Calls as one person; a refusal stops the seed with what was refused."""

    def __init__(self, client: httpx.AsyncClient, user: uuid.UUID) -> None:
        self.client = client
        self.headers = {SEED_HEADER: str(user)}

    def as_user(self, user: uuid.UUID) -> "Api":
        """The same API, acting as someone else."""
        return Api(self.client, user)

    async def call(  # noqa: PLR0913 - one request helper for every endpoint
        self,
        method: str,
        path: str,
        *,
        json: Any = None,  # noqa: ANN401 - request bodies of every endpoint
        params: Mapping[str, Any] | None = None,
        idempotency: str | None = None,
        version: int | None = None,
    ) -> Any:  # noqa: ANN401 - the endpoint's JSON
        """One request as this person; the JSON answer, or SeedError on a refusal."""
        headers = dict(self.headers)
        if idempotency is not None:
            headers["Idempotency-Key"] = idempotency
        if version is not None:
            headers["If-Match"] = f'"{version}"'
        response = await self.client.request(
            method, path, json=json, params=params, headers=headers
        )
        if response.status_code >= 400:  # noqa: PLR2004 - HTTP error range
            msg = f"{method} {path} was refused: {response.status_code} {response.text[:300]}"
            raise SeedError(msg)
        return response.json() if response.content else None

    async def all_pages(self, path: str, params: Mapping[str, Any] | None = None) -> list[Any]:
        """Every row of a cursor-paged list."""
        rows: list[Any] = []
        cursor: str | None = None
        while True:
            page = await self.call(
                "GET",
                path,
                params={**(params or {}), "limit": 100, **({"cursor": cursor} if cursor else {})},
            )
            rows.extend(page["items"])
            cursor = page.get("next_cursor")
            if not page.get("has_more") or cursor is None:
                return rows


async def ensure_units(api: Api) -> tuple[dict[str, str], dict[str, str]]:
    """Sites and groups by name, made when missing."""
    sites = {s["name"]: s["id"] for s in await api.call("GET", "/api/v1/organization/sites")}
    for name, zone in SITES:
        if name not in sites:
            made = await api.call(
                "POST",
                "/api/v1/organization/sites",
                json={"name": name, "time_zone": zone},
                idempotency=key("site", name),
            )
            sites[name] = made["id"]
    groups = {g["name"]: g["id"] for g in await api.call("GET", "/api/v1/organization/groups")}
    for name, at in GROUPS:
        if name not in groups:
            made = await api.call(
                "POST",
                "/api/v1/organization/groups",
                json={"name": name, "site_ids": [sites[s] for s in at]},
                idempotency=key("group", name),
            )
            groups[name] = made["id"]
    return sites, groups


async def ensure_people(
    api: Api,
    sites: Mapping[str, str],
    groups: Mapping[str, str],
    signed_in: Mapping[str, uuid.UUID],
) -> dict[str, str]:
    """People by e-mail, made when missing; then group and site memberships."""
    known = {u["email"]: u["id"] for u in await api.all_pages("/api/v1/users") if u.get("email")}
    for person in PEOPLE:
        if person.email not in known:
            made = await api.call(
                "POST",
                "/api/v1/users",
                json={
                    "first_name": person.first_name,
                    "last_name": person.last_name,
                    "email": person.email,
                    "user_type": person.user_type,
                    "site_id": sites[person.site],
                    "job_title": person.job_title or None,
                    "locale": person.locale,
                    "can_sign_in": False,
                },
                idempotency=key("person", person.email),
            )
            known[person.email] = made["id"]
    memberships = [(p.email, g) for p in PEOPLE for g in p.groups]
    memberships += [(email, g) for email, gs in SIGN_IN_GROUPS.items() for g in gs]
    for email, group in memberships:
        user = known.get(email) or str(signed_in[email])
        # PUT is idempotent: an existing membership stays as it is.
        await api.call("PUT", f"/api/v1/organization/groups/{groups[group]}/members/{user}")
    for email in SIGN_IN_GROUPS:
        known.setdefault(email, str(signed_in[email]))
    return known


@dataclass(frozen=True)
class Catalogue:
    """What the tenant's incident settings allow: transitions' reasons and closure codes."""

    transitions: list[dict[str, Any]]
    reasons: list[dict[str, Any]]
    closure_codes: list[str]

    def reason(self, action: str, status: str) -> dict[str, Any]:
        """The reason fields a move needs, if any (the first reason of its list)."""
        for move in self.transitions:
            if move["action"] == action and move.get("from_status") in (status, None):
                mode = move.get("reason_mode") or "none"
                if mode == "none":
                    return {}
                body: dict[str, Any] = {"reason_text": "Logged by the showcase seed."}
                codes = [
                    r["code"]
                    for r in self.reasons
                    if r.get("list") == move.get("reason_list") and not r.get("disabled")
                ]
                if codes:
                    body["reason_code"] = codes[0]
                return body
        return {}


async def catalogue(api: Api) -> Catalogue:
    """The incident settings the seed's moves need."""
    found = await api.call("GET", "/api/v1/incidents/settings")
    codes = [c["code"] for c in found["closure_codes"] if not c.get("disabled")]
    return Catalogue(found["transitions"], found["reasons"], codes)


async def ensure_incidents(  # noqa: C901 - one branch per state, flat
    api: Api,
    people: Mapping[str, str],
    groups: Mapping[str, str],
    signed_in: Mapping[str, uuid.UUID],
) -> int:
    """Sixty incidents, each once (by subject and requester); returns how many were made now."""
    existing = {(i["subject"], i["requester_id"]) for i in await api.all_pages("/api/v1/incidents")}
    requesters = [people[p.email] for p in PEOPLE if p.user_type == "requester"]
    technicians: dict[str, list[str]] = {name: [] for name in groups}
    for person in PEOPLE:
        for group in person.groups:
            technicians[group].append(people[person.email])
    for email, gs in SIGN_IN_GROUPS.items():
        for group in gs:
            technicians[group].append(str(signed_in[email]))
    rules = await catalogue(api)
    made = 0
    for n, state in enumerate(STATES):
        subject, group, urgency, impact = SUBJECTS[n % len(SUBJECTS)]
        requester = requesters[(n * 7) % len(requesters)]
        if (subject, requester) in existing:
            continue
        record = await api.call(
            "POST",
            "/api/v1/incidents",
            json={
                "subject": subject,
                "requester_id": requester,
                "urgency": urgency,
                "impact": impact,
                "channel": "phone" if n % 3 else "walk_up",
                "description": f"<p>{subject}.</p>",
            },
            idempotency=key("incident", str(n)),
        )
        made += 1
        if state == "new":
            continue
        pool = technicians[group]
        technician = pool[n % len(pool)]
        record = await api.call(
            "POST",
            f"/api/v1/incidents/{record['id']}/assign",
            json={
                "group_id": groups[group],
                "technician_id": technician,
                **rules.reason("assign", record["status"]),
            },
            version=record["version"],
        )
        if state == "assigned":
            continue
        # A technician who can sign in works their own incidents; the admin moves the others.
        worker = (
            api.as_user(uuid.UUID(technician))
            if technician in {str(u) for u in signed_in.values()}
            else api
        )
        record = await act(worker, rules, record, "start_work")
        await worker.call(
            "POST",
            f"/api/v1/incidents/{record['id']}/conversation",
            json={"kind": "reply", "body": f"<p>{REPLIES[n % len(REPLIES)]}</p>"},
            idempotency=key("reply", str(n)),
        )
        record = await worker.call("GET", f"/api/v1/incidents/{record['id']}")
        if state == "in_progress":
            continue
        if state == "awaiting_requester":
            await act(worker, rules, record, "wait_requester")
            continue
        record = await act(
            worker, rules, record, "resolve", {"resolution": RESOLUTION, "confirm_open_work": True}
        )
        if state == "closed":
            await act(
                worker,
                rules,
                record,
                "close",
                {
                    "closure_code": rules.closure_codes[0] if rules.closure_codes else None,
                    "confirm_open_work": True,
                },
            )
    return made


async def act(
    worker: Api,
    rules: Catalogue,
    record: Mapping[str, Any],
    action: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One status move with the reason it needs; returns the record after it."""
    moved = await worker.call(
        "POST",
        f"/api/v1/incidents/{record['id']}/actions/{action}",
        json={**rules.reason(action, record["status"]), **(extra or {})},
        version=record["version"],
    )
    return dict(moved)


DASHBOARD = "Showcase overview"


async def ensure_dashboard(api: Api) -> bool:
    """A shared copy of the built-in Service desk dashboard, once."""
    found = await api.call("GET", "/api/v1/dashboards")
    if any(d.get("name") == DASHBOARD for d in found["items"]):
        return False
    builtin = next((d for d in found["items"] if d.get("builtin")), None)
    await api.call(
        "POST",
        "/api/v1/dashboards",
        json={
            "name": DASHBOARD,
            "shared": True,
            **({"copied_from": builtin["ref"], "body": builtin["body"]} if builtin else {}),
        },
        idempotency=key("dashboard", DASHBOARD),
    )
    return True


@dataclass
class Report:
    """What this run made (empty lists and zero: everything was already there)."""

    tenant: list[str] = field(default_factory=list)
    keycloak: list[str] = field(default_factory=list)
    incidents: int = 0
    dashboard: bool = False
    backdated: int = 0


async def fill(settings: Settings, subjects: Mapping[str, str], report: Report) -> None:
    """Steps 3 and 4, inside the running app (sign-in needs its entitlements service)."""
    contexts: dict[uuid.UUID, TenantContext] = {}
    async with console_api(settings, contexts) as client:
        database = Database.from_settings(settings)
        if database is None:
            msg = "SUPPORTX_DATABASE_URL is not set"
            raise SeedError(msg)
        try:
            signed_in = await sign_in_once(database, subjects)
        finally:
            await database.dispose()
        for person in SIGN_INS:
            uid = signed_in[person.email]
            contexts[uid] = TenantContext(TENANT_ID, uid, roles=frozenset(person.roles))
        admin = Api(client, signed_in[ADMIN.email])
        sites, groups = await ensure_units(admin)
        people = await ensure_people(admin, sites, groups, signed_in)
        report.incidents = await ensure_incidents(admin, people, groups, signed_in)
        report.dashboard = await ensure_dashboard(admin)


def password_problem(password: str) -> str | None:
    """What the realm's password policy would refuse, said before Keycloak is asked."""
    if len(password) < 12:  # noqa: PLR2004 - the realm's minimum length
        return "must be set, 12 characters or more"
    needs = {
        "an upper-case letter": any(c.isupper() for c in password),
        "a lower-case letter": any(c.islower() for c in password),
        "a digit": any(c.isdigit() for c in password),
        "a special character": any(not c.isalnum() for c in password),
    }
    missing = [what for what, ok in needs.items() if not ok]
    return None if not missing else "needs " + ", ".join(missing)


def refuse(slug: str, settings: Settings) -> str | None:
    """Why this run must not go ahead, or None."""
    if slug != SLUG:
        return f"this seed only fills the tenant {SLUG!r}, never {slug!r}"
    if settings.profile == "production":
        return "refusing to run against production"
    return None


async def run(settings: Settings, keycloak: KeycloakTarget) -> Report:
    """All four steps."""
    report = Report()
    migrator = settings.migration_database_url
    if migrator is None or settings.database_url is None:
        msg = "SUPPORTX_DATABASE_URL and SUPPORTX_MIGRATION_DATABASE_URL must be set"
        raise SeedError(msg)
    report.tenant = await ensure_tenant(migrator.get_secret_value())
    async with httpx.AsyncClient(base_url=keycloak.base_url, timeout=20) as client:
        found = await ensure_keycloak(client, keycloak)
    report.keycloak = found.made
    await fill(settings, found.subjects, report)
    report.backdated = await backdate(migrator.get_secret_value())
    return report


def main(argv: Sequence[str]) -> int:  # pragma: no cover - thin CLI over the tested steps
    """`python -m tooling.showcase_seed showcase`."""
    settings = Settings.load(service_name="supportx-showcase-seed")
    slug = argv[0] if argv else SLUG
    why = refuse(slug, settings)
    if why is not None:
        sys.stderr.write(f"showcase seed: {why}\n")
        return 2
    env = os.environ
    password = env.get(PASSWORD_ENV, "")
    weak = password_problem(password)
    if weak is not None:
        sys.stderr.write(f"showcase seed: {PASSWORD_ENV} {weak}\n")
        return 2
    target = KeycloakTarget(
        env["SUPPORTX_KEYCLOAK_URL"],
        user=env.get("SUPPORTX_KEYCLOAK_ADMIN_USER", "admin"),
        password=env["SUPPORTX_KEYCLOAK_ADMIN_PASSWORD"],
        sign_in_password=password,
        realm=env.get("SUPPORTX_KEYCLOAK_REALM", "supportx"),
    )
    try:
        report = asyncio.run(run(settings, target))
    except SeedError as error:
        sys.stderr.write(f"showcase seed: {error}\n")
        return 1
    sys.stdout.write(
        f"showcase seed: tenant {SLUG} ({TENANT_ID})\n"
        f"  made now: {', '.join(report.tenant + report.keycloak) or 'nothing (all present)'}\n"
        f"  incidents made now: {report.incidents}; dashboard made now: {report.dashboard}\n"
        f"  incidents moved into the past 30 days now: {report.backdated}\n"
        f"  sign in as {ADMIN.email} or {TECHNICIAN.email} with ${PASSWORD_ENV}\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv[1:]))
