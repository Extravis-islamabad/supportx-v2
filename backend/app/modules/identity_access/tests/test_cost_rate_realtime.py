"""A cost rate change reaches only cost-rate viewers' screens, naming the person only (§8)."""

import uuid
from datetime import UTC, datetime

from app.modules.identity_access.events import UserCostRateChanged
from app.modules.identity_access.service.realtime import COST_RATES_LIST, ROUTES
from app.shared.events import Actor, EventEnvelope


def _envelope(tenant: uuid.UUID, person: uuid.UUID) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type=UserCostRateChanged.event_type,
        schema_version=1,
        tenant_id=tenant,
        actor=Actor.user(uuid.uuid4()),
        occurred_at=datetime.now(UTC),
        aggregate_type="user_cost_rate",
        aggregate_id=str(uuid.uuid4()),
        aggregate_version=1,
        payload=UserCostRateChanged(user_id=person, change="updated").model_dump(mode="json"),
    )


async def test_only_the_cost_rate_list_hears_and_only_the_person_id() -> None:
    tenant, person = uuid.uuid4(), uuid.uuid4()
    envelope = _envelope(tenant, person)
    (route,) = [r for r in ROUTES if UserCostRateChanged.event_type in r.event_types]
    effects = await route.route(envelope, None)  # type: ignore[arg-type]  # the session is unused
    channels = {p.channel.name for p in effects.publications}
    assert channels == {
        f"t:{tenant}:queue:user_cost_rates",
        f"t:{tenant}:queue:user_cost_rates.signal",
    }
    assert {p.ids for p in effects.publications} <= {(str(person),), ()}
    assert all(p.fields == () for p in effects.publications)
    assert COST_RATES_LIST.permission == "users.view_cost_rates"
    assert set(envelope.payload) == {"user_id", "change"}  # never an amount
