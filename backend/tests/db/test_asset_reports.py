"""Assets as a reporting source (WP-035 port; lane C's P6 review).

The source counts exactly the assets the viewer could list (its own scope-filtered list query),
and report files name states, product types, products and vendors in the reader's language,
never as ids. Analytics' asset measures and built-in reports are lane C's.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.shared.reporting import names_resolver, provider_for
from tests.db.test_assets_api import _add, _product
from tests.db.test_incidents_api import Org, World, world

pytestmark = pytest.mark.db
__all__ = ["world"]  # the fixture, used by name


async def _listed(world: World, org: Org, user: uuid.UUID) -> int:
    response = await world.call("GET", "/assets?limit=100", org, user)
    assert response.status_code == 200, response.text
    return len(response.json()["items"])


async def test_an_asset_report_counts_what_the_viewer_can_list(world: World) -> None:
    from app.modules.assets.service.reporting import AssetSource  # noqa: PLC0415 - this test only

    assert isinstance(provider_for("asset"), AssetSource)  # the real source, never a stand-in
    a = world.a
    laptop = await _product(world, a, "laptop", "Report laptop")
    for site in (None, a.s1, a.s2):
        body: dict[str, Any] = {"name": f"Counted {site}", "product_id": laptop}
        if site is not None:
            body["site_id"] = str(site)
        assert (await _add(world, a, body)).status_code == 201
    assert (await _add(world, world.b, {"name": "Other tenant"})).status_code in {201, 422}
    provider = provider_for("asset")
    for user in (a.admin, a.tech_a, a.tech_b):
        async with world.app.state.db.tenant_session(TenantContext(a.tenant, user)) as session:
            subject = await subject_for(session, a.tenant, user)
            found = await provider.source(session, subject)
            counted = await session.scalar(select(func.count()).select_from(found.rows.subquery()))
        assert counted == await _listed(world, a, user), user
        assert set(found.dimensions) <= set(found.fields.fields)  # every grouping is filterable


async def test_states_product_types_and_vendors_are_named_for_files(world: World) -> None:
    a = world.a
    laptop = await _product(world, a, "laptop", "Named laptop")
    made = (await _add(world, a, {"name": "Named", "product_id": laptop})).json()
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        for kind, value in (
            ("asset_state", made["state_id"]),
            ("asset_product_type", made["product_type_id"]),
            ("asset_product", made["product_id"]),
        ):
            resolver = names_resolver(kind)
            assert resolver is not None, kind
            found = await resolver(session, [value, "not-an-id"], "ar", "")
            assert found.get(value), kind  # a name, in Arabic or else English
            assert "not-an-id" not in found
        vendors = names_resolver("vendor")
        assert vendors is not None
        assert await vendors(session, [str(uuid.uuid4())], "en", "") == {}


async def test_the_asset_built_ins_run_and_name_their_values_in_the_reader_s_language(
    world: World,
) -> None:
    """Lane C's asset reports: they run for the admin, and a run names states for the screen."""
    from app.modules.analytics.domain.builtin import BUILTIN  # noqa: PLC0415 - this test only
    from tests.db.test_incidents_api import CONSOLE  # noqa: PLC0415 - this test only

    a = world.a
    laptop = await _product(world, a, "laptop", "Named for screen")
    assert (await _add(world, a, {"name": "On screen", "product_id": laptop})).status_code == 201
    for code in (
        "assets_by_state",
        "assets_by_product_type",
        "assets_warranty_ending",
        "assets_by_age",
    ):
        report = BUILTIN[code]
        ran = await world.call(
            "POST",
            "/reports/run",
            a,
            a.admin,
            json={"definition": report.definition.model_dump(mode="json"), "language": "ar"},
            headers=CONSOLE,
        )
        assert ran.status_code == 200, (code, ran.text)
        body = ran.json()
        if code == "assets_by_state":
            keys = {row["keys"][0] for row in body["rows"]}
            assert keys
            assert set(body["names"]["state_id"]) == keys  # every state named, none as an id
