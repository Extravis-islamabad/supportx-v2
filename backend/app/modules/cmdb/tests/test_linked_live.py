"""The Associations tab stays live (WP-053 S5c, rule c). No I/O: the routes with a stand-in port."""

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from app.modules.cmdb.service import linked, realtime
from app.modules.cmdb.service.linked import CiLinkedRecord
from app.shared.events import Actor, EventEnvelope

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.identity_access import Subject
    from app.shared.realtime import RealtimeEffects

TENANT = uuid.uuid4()
SESSION = cast("AsyncSession", None)


def _envelope(event_type: str, payload: dict[str, str]) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type=event_type,
        schema_version=1,
        tenant_id=TENANT,
        actor=Actor.system("test"),
        occurred_at=datetime.now(UTC),
        aggregate_type="work_item",
        aggregate_id=payload["work_item_id"],
        payload=payload,
    )


def _run(event_type: str, payload: dict[str, str]) -> "RealtimeEffects":
    """Through the module's public routes, as the fan-out worker calls them."""
    [route] = [r for r in realtime.ROUTES if event_type in r.event_types]

    async def call() -> "RealtimeEffects":
        return await route.route(_envelope(event_type, payload), SESSION)

    return asyncio.run(call())


class _Port:
    def __init__(self, cis: list[uuid.UUID]) -> None:
        self.cis = cis

    async def linked_page(
        self,
        session: "AsyncSession",
        subject: "Subject",
        ci_id: uuid.UUID,
        kind: str,
        *,
        cursor: str | None = None,
        limit: int = 25,
    ) -> tuple[Sequence[CiLinkedRecord], str | None]:
        del session, subject, ci_id, kind, cursor, limit
        return [], None

    async def ci_ids_of(self, session: "AsyncSession", work_item_id: uuid.UUID) -> list[uuid.UUID]:
        del session, work_item_id
        return self.cis


def test_a_link_or_unlink_publishes_on_that_cis_record_channel_ids_only() -> None:
    ci, item = uuid.uuid4(), uuid.uuid4()
    payload = {"work_item_id": str(item), "type": "incident", "ci_id": str(ci), "change": "added"}
    [one] = _run("work_items.ci_link.changed", payload).publications
    assert one.channel.key == str(ci)
    assert one.ids == (str(ci),)
    assert one.fields == (realtime.LINKED,)
    assert str(item) not in repr(one)  # which work item is the API's to say, per reader


def test_a_linked_records_status_change_reaches_each_of_its_cis() -> None:
    first, second, item = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    linked.register_ci_linked_records(_Port([first, second]))
    try:
        effects = _run("work_items.work_item.status_changed", {"work_item_id": str(item)})
    finally:
        linked.clear_ci_linked_records()
    assert sorted(p.channel.key or "" for p in effects.publications) == sorted(
        [str(first), str(second)]
    )
    assert all(p.fields == (realtime.LINKED,) for p in effects.publications)


def test_without_the_port_a_status_change_publishes_nothing() -> None:
    linked.clear_ci_linked_records()
    effects = _run("work_items.work_item.status_changed", {"work_item_id": str(uuid.uuid4())})
    assert effects.publications == []
