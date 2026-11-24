"""CIs and relationships as reporting sources (WP-053 S5a; REQ-CMDB-032).

- AC1: CIs by type and state match the CMDB list's counts.
- AC2: a report never includes a CI outside the reader's fine-grained access (ADR-053): the
  source's rows ARE the list's narrowed query, so a narrowed reader's total is their list total
  (the coordinator's condition: narrowing before any grouping).
- A relationship counts only when both of its CIs are visible: a link to a hidden CI is not
  counted, never shown as a placeholder (lane C).
- A withheld custom field (ADR-047) is neither a field nor a dimension, and is named in
  `withheld`; `asset_id` is never reported.
- CMDB values are named for report files in the reader's language; people are the shared "user"
  reference that the screens name themselves (D-180 masking), never named by the CMDB.

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h).
"""

import uuid
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.tenancy import TenantContext
from app.modules.cmdb.infra.models import Ci, Relationship
from app.modules.cmdb.service.reporting import (
    CI_ENTITY,
    RELATIONSHIP_ENTITY,
    CiSource,
    RelationshipSource,
)
from app.modules.identity_access import subject_for
from app.shared.reporting import names_resolver, provider_for
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_api import _types
from tests.db.test_cmdb_custom_fields import _field, _role_id
from tests.db.test_cmdb_custom_fields import _rule as field_rule
from tests.db.test_cmdb_relationships import _link
from tests.db.test_incidents_api import Org, World
from tests.db.test_resource_access import _edition, _holding, _made, _rule

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

CI_RIGHTS = [("cmdb.view", "all")]


async def _listed(world: World, org: Org, user: uuid.UUID) -> list[dict[str, Any]]:
    """Every CI the person's list shows, page by page."""
    found: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        path = "/cmdb/cis?limit=100" + (f"&cursor={cursor}" if cursor else "")
        page = await world.call("GET", path, org, user)
        assert page.status_code == 200, page.text
        body = page.json()
        found.extend(body["items"])
        cursor = body.get("next_cursor")
        if not cursor:
            return found


async def _source(world: World, org: Org, user: uuid.UUID, entity: str) -> Any:  # noqa: ANN401 - a ReportingSource and a session-bound count
    async with world.app.state.db.tenant_session(TenantContext(org.tenant, user)) as session:
        subject = await subject_for(session, org.tenant, user)
        found = await provider_for(entity).source(session, subject)
        ids = set(
            await session.scalars(
                found.rows.with_only_columns(Ci.id if entity == CI_ENTITY else Relationship.id)
            )
        )
    return found, ids


async def test_the_sources_are_the_real_ones() -> None:
    assert isinstance(provider_for(CI_ENTITY), CiSource)
    assert isinstance(provider_for(RELATIONSHIP_ENTITY), RelationshipSource)


async def test_a_ci_report_counts_what_each_reader_lists_narrowed_included(world: World) -> None:
    """AC1 (by type and state, as the list counts) and AC2 (fine-grained access first)."""
    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    tag = uuid.uuid4().hex[:6]
    for n in range(2):
        await _made(world, a, f"Report server {tag} {n}", "server")
    await _made(world, a, f"Report database {tag}", "database")

    admin_listed = await _listed(world, a, a.admin)
    found, ids = await _source(world, a, a.admin, CI_ENTITY)
    assert ids == {uuid.UUID(c["id"]) for c in admin_listed}  # AC1: the same CIs as the list
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        by_type = Counter(
            (str(t), str(s))
            for t, s in await session.execute(select(Ci.type_id, Ci.state_id).where(Ci.id.in_(ids)))
        )
    assert by_type == Counter((c["type_id"], c["state_id"]) for c in admin_listed)
    assert set(found.dimensions) <= set(found.fields.fields)  # every grouping is filterable

    async with _holding(world, a, a.requester, CI_RIGHTS) as narrowed:
        made = await _rule(world, a, narrowed, "ci", {"type_ids": [types["server"]["id"]]})
        assert made.status_code == 201, made.text
        await _edition(world, a, "enterprise")  # drops the cached subjects
        mine = await _listed(world, a, a.requester)
        _found, narrowed_ids = await _source(world, a, a.requester, CI_ENTITY)
        assert narrowed_ids == {uuid.UUID(c["id"]) for c in mine}  # AC2: the narrowed list
        assert {c["type_id"] for c in mine} == {types["server"]["id"]}
        assert narrowed_ids < ids  # narrower than the admin's, before any grouping
        # The narrowed rows read the CI type tree (a type rule takes its subtree): they run as
        # the reporting role, as analytics runs them, so 0200's grant on cmdb_ci_types is proven.
        found, _ids = await _source(world, a, a.requester, CI_ENTITY)
        rels, _ids = await _source(world, a, a.requester, RELATIONSHIP_ENTITY)
        context = TenantContext(a.tenant, a.requester)
        async with world.app.state.db.reporting_session(context, timeout_seconds=30) as report:
            for source in (found, rels):
                counted = await report.scalar(
                    select(func.count()).select_from(source.rows.subquery())
                )
                assert counted is not None, source.entity


async def test_a_relationship_counts_only_when_both_cis_are_visible(world: World) -> None:
    a = world.a
    await _edition(world, a, "enterprise")
    types = await _types(world, a)
    tag = uuid.uuid4().hex[:6]
    app = await _made(world, a, f"Rel server {tag}", "server")
    other = await _made(world, a, f"Rel server two {tag}", "server")
    hidden = await _made(world, a, f"Rel database {tag}", "database")
    assert (await _link(world, a, app, "depends_on", [hidden])).status_code == 201
    assert (await _link(world, a, app, "connected_to", [other])).status_code == 201

    _found, admin_rels = await _source(world, a, a.admin, RELATIONSHIP_ENTITY)
    async with _holding(world, a, a.requester, CI_RIGHTS) as narrowed:
        made = await _rule(world, a, narrowed, "ci", {"type_ids": [types["server"]["id"]]})
        assert made.status_code == 201, made.text
        await _edition(world, a, "enterprise")
        _found, seen_rels = await _source(world, a, a.requester, RELATIONSHIP_ENTITY)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        ends = {
            r.id: (r.from_ci_id, r.to_ci_id)
            for r in await session.scalars(
                select(Relationship).where(Relationship.from_ci_id == uuid.UUID(app["id"]))
            )
        }
    to_hidden = {i for i, (_, to) in ends.items() if to == uuid.UUID(hidden["id"])}
    to_other = {i for i, (_, to) in ends.items() if to == uuid.UUID(other["id"])}
    assert to_hidden
    assert to_other
    assert to_hidden <= admin_rels
    assert to_other <= admin_rels
    assert to_other <= seen_rels  # both ends seen: counted
    assert not (to_hidden & seen_rels)  # one end hidden: never counted


async def test_a_withheld_custom_field_is_neither_a_field_nor_a_dimension(world: World) -> None:
    a = world.a
    key = (await _field(world, a, "Rack position", None))["key"]
    await field_rule(world, a, await _role_id(world, a, "technician"), f"custom.{key}", "hidden")
    found, _ids = await _source(world, a, a.tech_a, CI_ENTITY)
    assert f"custom.{key}" in found.withheld
    assert f"custom.{key}" not in found.fields.fields
    assert f"custom.{key}" not in found.dimensions
    admin, _ids = await _source(world, a, a.admin, CI_ENTITY)
    assert f"custom.{key}" in admin.fields.fields  # no rule for the admin: reportable
    for source in (found, admin):
        assert "asset_id" not in source.fields.fields  # another module's record: never reported
        assert "asset_id" not in source.dimensions


async def test_cmdb_values_are_named_and_people_are_never_named_here(world: World) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    made = await _made(world, a, f"Named server {tag}", "server")
    rels = (await world.call("GET", "/cmdb/relationship-types", a, a.admin)).json()["items"]
    depends = next(t for t in rels if t["code"] == "depends_on")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        for kind, value in (
            ("ci_type", made["type_id"]),
            ("ci_state", made["state_id"]),
            ("ci_relationship_type", depends["id"]),
        ):
            resolver = names_resolver(kind)
            assert resolver is not None, kind
            named = await resolver(session, [value, "not-an-id"], "ar", "")
            assert named.get(value), kind  # a name, in Arabic or else English
            assert "not-an-id" not in named
    # A person is the shared "user" reference: the screens name it (masked for vendor support,
    # D-180); the CMDB registers no resolver that could name one in a file.
    found, _ids = await _source(world, a, a.admin, CI_ENTITY)
    assert found.dimensions["owner_user_id"].reference == "user"
    assert names_resolver("user") is None
