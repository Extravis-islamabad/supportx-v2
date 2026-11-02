"""Which notification events a conversation entry raises (WP-023; WP-024 automatic replies)."""

import uuid
from datetime import UTC, datetime

from app.modules.work_items.events import WorkItemConversationAdded
from app.modules.work_items.service.notifications import IncidentNotifications
from app.shared.events import Actor, EventEnvelope


def _added(**payload: object) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type=WorkItemConversationAdded.event_type,
        schema_version=1,
        tenant_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        actor=Actor.system("work_items"),
        aggregate_type="work_item_conversation",
        aggregate_id=str(uuid.uuid4()),
        payload={"kind": "reply", "visibility": "public", **payload},
    )


def test_a_requester_reply_notifies() -> None:
    assert IncidentNotifications().events_for(_added()) == ("incident.public_reply",)


def test_an_automatic_reply_notifies_nobody() -> None:
    """REQ-INC-024 AC2: an out-of-office is on the timeline, and nobody hears of it."""
    assert IncidentNotifications().events_for(_added(automatic=True)) == ()
