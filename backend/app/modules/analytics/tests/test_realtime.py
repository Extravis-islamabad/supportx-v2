"""Who hears about a report change (rule c; payloads carry ids only to people who may see them)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.modules.analytics.service.realtime import ROUTES
from app.shared.events import EventEnvelope

TENANT = uuid.uuid4()
OWNER = uuid.uuid4()


def _envelope(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope.model_validate(
        {
            "event_id": uuid.uuid4(),
            "event_type": event_type,
            "schema_version": 1,
            "tenant_id": TENANT,
            "actor": {"type": "user", "id": str(OWNER)},
            "occurred_at": datetime.now(UTC),
            "aggregate_type": "report",
            "aggregate_id": "x",
            "payload": payload,
        }
    )


async def _channels(event_type: str, payload: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    handler = next(r for r in ROUTES if event_type in r.event_types).route
    effects = await handler(_envelope(event_type, payload), None)  # type: ignore[arg-type]  # the route reads no rows
    return {p.channel.name: p.ids for p in effects.publications}


async def test_private_reports_reach_only_their_owner_with_the_id() -> None:
    report = str(uuid.uuid4())
    found = await _channels(
        "analytics.report.saved",
        {"report_id": report, "owner_id": str(OWNER), "folder_id": None, "changed_fields": []},
    )
    assert found == {f"t:{TENANT}:user:{OWNER}": (report,)}


async def test_shared_changes_are_an_id_free_broadcast() -> None:
    shared = await _channels(
        "analytics.report.saved",
        {"report_id": str(uuid.uuid4()), "owner_id": str(OWNER), "folder_id": str(uuid.uuid4())},
    )
    assert shared == {f"t:{TENANT}:broadcast": ()}
    folder = await _channels("analytics.report_folder.saved", {"folder_id": str(uuid.uuid4())})
    assert folder == {f"t:{TENANT}:broadcast": ()}
    moved_out = await _channels(
        "analytics.report.saved",
        {
            "report_id": str(uuid.uuid4()),
            "owner_id": str(OWNER),
            "folder_id": None,
            "changed_fields": ["folder_id"],
        },
    )
    assert f"t:{TENANT}:broadcast" in moved_out
