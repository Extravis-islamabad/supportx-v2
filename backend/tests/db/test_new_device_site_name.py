"""The new-device notice names a mapped site as it is called now (S2b-1 follow-up; lane B's #491).

`organization.site_names` reads the tenant's own sites (RLS). A site that is not found (another
tenant's, or none) keeps the "a mapped site" wording; a city place is unchanged.
"""

import uuid
from datetime import UTC, datetime

from app.core.tenancy import TenantContext
from app.modules.identity_access.service.security_notices import NEW_DEVICE, SOURCE
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import LabelRef
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used


def _envelope(world: World, place: dict[str, str] | None) -> EventEnvelope:
    return EventEnvelope.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "identity_access.new_device.signed_in",
            "schema_version": 1,
            "tenant_id": str(world.a.tenant),
            "actor": {"type": "user", "id": str(world.a.admin)},
            "occurred_at": datetime.now(UTC).isoformat(),
            "aggregate_type": "user",
            "aggregate_id": str(world.a.admin),
            "payload": {
                "user_id": str(world.a.admin),
                "device": "chrome:windows",
                "place": place,
                "signed_in_at": datetime.now(UTC).isoformat(),
            },
        }
    )


async def _place(world: World, place: dict[str, str] | None) -> object:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        context = await SOURCE.context(session, NEW_DEVICE, _envelope(world, place))
    assert context is not None
    return context.variables["notice.place"]


async def test_a_mapped_site_is_named_and_an_unknown_one_says_a_mapped_site(world: World) -> None:
    named = await _place(world, {"kind": "site", "site_id": str(world.a.s1)})
    assert isinstance(named, str)
    assert named  # the site's name as it is now
    for site in (world.b.s1, uuid.uuid4()):  # another tenant's site, or none: never named
        unknown = await _place(world, {"kind": "site", "site_id": str(site)})
        assert unknown == LabelRef("sign_in_place.site_unknown")
    assert await _place(world, {"kind": "geo", "city": "Lahore", "country": "PK"}) == "Lahore, PK"
