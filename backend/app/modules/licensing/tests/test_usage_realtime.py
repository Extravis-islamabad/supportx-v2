"""The licence page hears when the technician count may have changed (WP-042, REQ-ADM-109)."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import pytest

from app.modules.licensing.service.realtime import ROUTES
from app.shared.events import Actor, EventEnvelope

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

TENANT = uuid.uuid4()


def _envelope(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type=event_type,
        schema_version=1,
        tenant_id=TENANT,
        actor=Actor.user(uuid.uuid4()),
        occurred_at=datetime.now(UTC),
        aggregate_type="user",
        aggregate_id=str(uuid.uuid4()),
        payload=payload,
    )


async def _signals(
    event_type: str, payload: dict[str, Any]
) -> list[tuple[str, str, tuple[str, ...]]]:
    route = next(r for r in ROUTES if event_type in r.event_types)
    # The route reads nothing from the database.
    effects = await route.route(_envelope(event_type, payload), cast("AsyncSession", None))
    return [(p.channel.name, p.type, p.ids) for p in effects.publications]


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("identity_access.user.created", {}),
        ("identity_access.user.provisioned", {}),
        ("identity_access.user.status_changed", {"status": "disabled"}),
        ("identity_access.user.updated", {"changed_fields": ["user_type"]}),
    ],
)
async def test_a_change_to_who_counts_signals_the_licence_page(
    event_type: str, payload: dict[str, Any]
) -> None:
    assert await _signals(event_type, payload) == [
        (f"t:{TENANT}:broadcast", "entitlements.usage_changed", ())
    ]


async def test_a_profile_edit_says_nothing() -> None:
    assert (
        await _signals("identity_access.user.updated", {"changed_fields": ["display_name"]}) == []
    )
