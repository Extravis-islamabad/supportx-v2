"""Policy on real PostgreSQL with a sample resource (`probe_tickets`, test-only) (WP-016).

- each scope (own / group / site / all) returns exactly the right rows;
- an attribute rule (filter DSL) narrows a grant; SQL and in-memory evaluation agree;
- field masking and segregation of duties on the sample resource;
- 100,000 rows: the scoped list stays fast (index-backed).
"""

import asyncio
import statistics
import time
import uuid
from datetime import UTC, datetime
from typing import cast

import asyncpg
import pytest
from sqlalchemy import Column, Index, MetaData, String, Table, Uuid, func, select
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.database import Database
from app.core.modules import ModuleRegistry, discover_modules
from app.core.tenancy import TenantContext
from app.modules.identity_access import build_catalogue
from app.modules.identity_access.domain.policy import (
    Grant,
    RecordFacts,
    Subject,
    compile_subject,
    matches,
)
from app.modules.identity_access.service.policy import (
    FieldRule,
    ResourceType,
    SodRule,
    authorize,
    authorize_stored,
    requested_it_yourself,
    scope_filter,
    visible,
)
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.db.models import NAMING_CONVENTION, Base
from app.shared.db.rls import app_grant_statements, tenant_rls_statements
from conftest import create_tenant
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db


class ProbeBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = Base.type_annotation_map


Table("tenants", ProbeBase.metadata, Column("id", Uuid, primary_key=True))


class ProbeTicket(ProbeBase):
    """A ticket-shaped test record: requester, assignee, site, group, category, a secret field."""

    __tablename__ = "probe_tickets"
    __table_args__ = (
        Index("ix_probe_tickets_tenant_created", "tenant_id", "created_at", "id"),
        Index("ix_probe_tickets_tenant_site", "tenant_id", "site_id", "created_at"),
        Index("ix_probe_tickets_tenant_group", "tenant_id", "group_id", "created_at"),
        Index("ix_probe_tickets_tenant_requester", "tenant_id", "requester_id"),
        Index("ix_probe_tickets_tenant_assignee", "tenant_id", "assignee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    requester_id: Mapped[uuid.UUID | None]
    assignee_id: Mapped[uuid.UUID | None]
    site_id: Mapped[uuid.UUID | None]
    group_id: Mapped[uuid.UUID | None]
    cost_centre: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


TICKET_FIELDS = ResourceFields(
    name="tickets",
    fields={
        "category": FilterField(ProbeTicket.category, FieldType.STRING),
        "title": FilterField(ProbeTicket.title, FieldType.STRING),
        "created_at": FilterField(ProbeTicket.created_at, FieldType.DATETIME),
    },
    id_column=ProbeTicket.id,
)
TICKETS = ResourceType(
    name="tickets",
    fields=TICKET_FIELDS,
    owner_columns=(ProbeTicket.requester_id, ProbeTicket.assignee_id),
    site_scope=ProbeTicket.site_id.in_,
    group_scope=ProbeTicket.group_id.in_,
    field_rules={"cost_centre": FieldRule("changes.approve", "mask")},
    sod_rules={"changes.approve": (SodRule("own_request_approval", requested_it_yourself),)},
)
CATALOGUE = build_catalogue(ModuleRegistry.from_specs(discover_modules()))
ME, OTHER = uuid.uuid4(), uuid.uuid4()
MY_SITE, OTHER_SITE, MY_GROUP, OTHER_GROUP = (uuid.uuid4() for _ in range(4))


def subject(tenant: uuid.UUID, *grants: tuple[str, Grant]) -> Subject:
    return compile_subject(
        tenant_id=tenant,
        user_id=ME,
        role_keys=["custom"],
        grants=grants,
        catalogue=CATALOGUE,
        entitled_features=frozenset({"incident", "change"}),
        site_ids=frozenset({MY_SITE}),
        group_ids=frozenset({MY_GROUP}),
    )


def ddl() -> list[str]:
    dialect = PGDialect()  # type: ignore[no-untyped-call]  # SQLAlchemy dialect classes are unannotated
    table = cast("Table", ProbeTicket.__table__)
    statements = [str(CreateTable(table, if_not_exists=True).compile(dialect=dialect))]
    statements += [
        str(CreateIndex(i, if_not_exists=True).compile(dialect=dialect)) for i in table.indexes
    ]
    return (
        statements + tenant_rls_statements("probe_tickets") + app_grant_statements("probe_tickets")
    )


async def _create_table(migrator_url: str) -> None:
    conn = await asyncpg.connect(migrator_url)
    try:
        if not await conn.fetchval("SELECT to_regclass('probe_tickets') IS NOT NULL"):
            for statement in ddl():
                await conn.execute(statement)
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def tickets_table(migrated_db: ThrowawayDatabase) -> None:
    """The sample table in the session's throwaway database (created once)."""
    asyncio.run(_create_table(migrated_db.migrator_url))


async def insert(
    db: ThrowawayDatabase, tenant: uuid.UUID, rows: dict[str, dict[str, object]]
) -> dict[str, uuid.UUID]:
    """Named rows → their IDs."""
    ids: dict[str, uuid.UUID] = {}
    conn = await asyncpg.connect(db.admin_url)
    try:
        for name, row in rows.items():
            ids[name] = uuid.uuid4()
            await conn.execute(
                "INSERT INTO probe_tickets (id, tenant_id, title, category, requester_id,"
                " assignee_id, site_id, group_id, cost_centre)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                ids[name],
                tenant,
                name,
                row.get("category", "it"),
                row.get("requester_id"),
                row.get("assignee_id"),
                row.get("site_id"),
                row.get("group_id"),
                row.get("cost_centre"),
            )
    finally:
        await conn.close()
    return ids


ROWS: dict[str, dict[str, object]] = {
    "requested_by_me": {"requester_id": ME, "site_id": OTHER_SITE},
    "assigned_to_me": {"assignee_id": ME, "requester_id": OTHER},
    "my_site": {"site_id": MY_SITE, "requester_id": OTHER},
    "my_group": {"group_id": MY_GROUP, "requester_id": OTHER},
    "my_site_hr": {"site_id": MY_SITE, "category": "hr", "requester_id": OTHER},
    "elsewhere": {"site_id": OTHER_SITE, "group_id": OTHER_GROUP, "requester_id": OTHER},
}


async def visible_titles(app_db: Database, subject_: Subject) -> set[str]:
    async with app_db.tenant_session(TenantContext(subject_.tenant_id)) as session:
        rows = await session.scalars(
            select(ProbeTicket.title).where(scope_filter(subject_, "requests.view", TICKETS))
        )
        return set(rows.all())


@pytest.mark.parametrize(
    ("grants", "expected"),
    [
        ([("requests.view", Grant("own"))], {"requested_by_me", "assigned_to_me"}),
        ([("requests.view", Grant("site"))], {"my_site", "my_site_hr"}),
        ([("requests.view", Grant("group"))], {"my_group"}),
        ([("requests.view", Grant("all"))], set(ROWS)),
        (
            [("requests.view", Grant("own")), ("requests.view", Grant("group"))],
            {"requested_by_me", "assigned_to_me", "my_group"},
        ),
        ([], set()),  # no grant: nothing, never everything
        (
            [("requests.view", Grant("site", {"field": "category", "op": "eq", "value": "hr"}))],
            {"my_site_hr"},
        ),
    ],
)
async def test_scope_filter_returns_exactly_the_right_rows(
    tickets_table: None,
    app_db: Database,
    migrated_db: ThrowawayDatabase,
    grants: list[tuple[str, Grant]],
    expected: set[str],
) -> None:
    del tickets_table
    tenant = await create_tenant(migrated_db.migrator_url, "Scopes")
    await insert(migrated_db, tenant, ROWS)
    assert await visible_titles(app_db, subject(tenant, *grants)) == expected


async def test_stored_check_matches_the_list(
    tickets_table: None, app_db: Database, migrated_db: ThrowawayDatabase
) -> None:
    del tickets_table
    tenant = await create_tenant(migrated_db.migrator_url, "Stored")
    ids = await insert(migrated_db, tenant, ROWS)
    me = subject(tenant, ("requests.view", Grant("site")))
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        for name, row_id in ids.items():
            decision = await authorize_stored(
                session, me, "requests.view", TICKETS, ProbeTicket.id, row_id
            )
            assert decision.allowed is (name in {"my_site", "my_site_hr"}), name
            if not decision:
                assert decision.reason == "out_of_scope"


@pytest.mark.parametrize(
    "condition",
    [
        {"field": "category", "op": "eq", "value": "hr"},
        {"field": "category", "op": "ne", "value": "hr"},
        {"field": "title", "op": "contains", "value": "SITE"},
        {"field": "title", "op": "starts_with", "value": "my_"},
        {
            "or": [
                {"field": "category", "op": "in", "value": ["hr"]},
                {"field": "title", "op": "eq", "value": "elsewhere"},
            ]
        },
    ],
)
async def test_sql_and_in_memory_rules_agree(
    tickets_table: None,
    app_db: Database,
    migrated_db: ThrowawayDatabase,
    condition: dict[str, object],
) -> None:
    """The same attribute rule gives the same answer in a list (SQL) and on one record (memory)."""
    del tickets_table
    tenant = await create_tenant(migrated_db.migrator_url, "Parity")
    await insert(migrated_db, tenant, ROWS)
    in_sql = await visible_titles(
        app_db, subject(tenant, ("requests.view", Grant("all", condition)))
    )
    in_memory = {
        name
        for name, row in ROWS.items()
        if matches(condition, {"title": name, "category": row.get("category", "it")})
    }
    assert in_sql == in_memory


def test_field_masking_and_segregation_of_duties() -> None:
    tenant = uuid.uuid4()
    approver = subject(tenant, ("changes.approve", Grant("all")), ("requests.view", Grant("all")))
    viewer = subject(tenant, ("requests.view", Grant("all")))
    row = {"title": "Laptop", "cost_centre": "CC-4410"}
    assert visible(approver, TICKETS, row)["cost_centre"] == "CC-4410"
    assert visible(viewer, TICKETS, row)["cost_centre"] == "••••"
    assert visible(viewer, TICKETS, {"cost_centre": None})["cost_centre"] is None

    mine = RecordFacts(owner_ids=frozenset({ME}), attributes={"requester_id": ME})
    theirs = RecordFacts(owner_ids=frozenset({OTHER}), attributes={"requester_id": OTHER})
    refused = authorize(approver, "changes.approve", TICKETS, mine)
    assert (refused.allowed, refused.reason) == (False, "own_request_approval")
    assert authorize(approver, "changes.approve", TICKETS, theirs)
    assert authorize(viewer, "changes.approve", TICKETS, theirs).reason == "no_permission"


async def test_scoped_list_over_100000_rows_is_fast(
    tickets_table: None, app_db: Database, migrated_db: ThrowawayDatabase
) -> None:
    del tickets_table
    tenant = await create_tenant(migrated_db.migrator_url, "Big")
    conn = await asyncpg.connect(migrated_db.admin_url)
    try:
        sites = [MY_SITE, OTHER_SITE, uuid.uuid4(), uuid.uuid4()]
        await conn.execute(
            "INSERT INTO probe_tickets (id, tenant_id, title, category, requester_id, site_id,"
            " group_id, created_at)"
            " SELECT gen_random_uuid(), $1, 'T' || n, CASE WHEN n % 10 = 0 THEN 'hr' ELSE 'it' END,"
            " CASE WHEN n % 1000 = 0 THEN $2::uuid ELSE $3::uuid END, ($4::uuid[])[1 + n % 4],"
            " CASE WHEN n % 50 = 0 THEN $5::uuid ELSE $6::uuid END, now() - n * interval '1 second'"
            " FROM generate_series(1, 100000) AS n",
            tenant,
            ME,
            OTHER,
            sites,
            MY_GROUP,
            OTHER_GROUP,
        )
        await conn.execute("ANALYZE probe_tickets")
    finally:
        await conn.close()
    cases = {
        "own": subject(tenant, ("requests.view", Grant("own"))),
        "site": subject(tenant, ("requests.view", Grant("site"))),
        "group": subject(tenant, ("requests.view", Grant("group"))),
        "own+group+site_hr": subject(
            tenant,
            ("requests.view", Grant("own")),
            ("requests.view", Grant("group")),
            ("requests.view", Grant("site", {"field": "category", "op": "eq", "value": "hr"})),
        ),
    }
    timings: dict[str, float] = {}
    for name, who in cases.items():
        samples = []
        async with app_db.tenant_session(TenantContext(tenant)) as session:
            query = (
                select(ProbeTicket.id)
                .where(scope_filter(who, "requests.view", TICKETS, now=datetime.now(UTC)))
                .order_by(ProbeTicket.created_at.desc(), ProbeTicket.id)
                .limit(50)
            )
            for _ in range(7):
                start = time.perf_counter()
                rows = (await session.scalars(query)).all()
                samples.append((time.perf_counter() - start) * 1000)
            assert len(rows) == 50
            total = await session.scalar(
                select(func.count())
                .select_from(ProbeTicket)
                .where(scope_filter(who, "requests.view", TICKETS))
            )
        timings[name] = statistics.median(samples)
        print(f"scoped page ({name}, {total} visible of 100,000): p50 {timings[name]:.1f} ms")  # noqa: T201
    assert max(timings.values()) < 250
