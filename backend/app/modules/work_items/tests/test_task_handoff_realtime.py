"""A task handed off leaves its previous owner's lists live (WP-047a S5; lane C's #630 review).

No I/O: the realtime route with a session stub that names the task's current owner.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.modules.work_items.events import WorkItemPartChanged
from app.modules.work_items.service import parts
from app.modules.work_items.service.realtime import MY_TASKS_CHANGED, _part_changed
from app.shared.events import Actor, EventEnvelope
from app.shared.history import Change


class _Session:
    """Answers the route's one question: who owns the task now."""

    def __init__(self, owner: uuid.UUID | None) -> None:
        self.owner = owner

    async def scalar(self, _statement: Any) -> uuid.UUID | None:  # noqa: ANN401 - a select
        return self.owner


def _envelope(tenant: uuid.UUID, **payload: object) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type=WorkItemPartChanged.event_type,
        schema_version=1,
        tenant_id=tenant,
        occurred_at=datetime.now(UTC),
        actor=Actor.system("work_items"),
        aggregate_type="work_item",
        aggregate_id=str(uuid.uuid4()),
        payload={
            "work_item_id": str(uuid.uuid4()),
            "part": "task",
            "part_id": str(uuid.uuid4()),
            "change": "changed",
            **payload,
        },
    )


def _personal(effects: Any) -> set[str]:  # noqa: ANN401 - RealtimeEffects
    return {str(p.channel) for p in effects.publications if p.type == MY_TASKS_CHANGED}


async def test_both_owners_hear_a_handoff_and_nobody_twice() -> None:
    tenant, before, now = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    effects = await _part_changed(
        _envelope(tenant, previous_owner_id=str(before)),
        _Session(now),  # type: ignore[arg-type]  # a stub of the one call the route makes
    )
    told = _personal(effects)
    assert any(str(before) in c for c in told)
    assert any(str(now) in c for c in told)
    assert len(told) == 2


async def test_a_task_given_to_nobody_still_tells_its_previous_owner() -> None:
    tenant, before = uuid.uuid4(), uuid.uuid4()
    effects = await _part_changed(
        _envelope(tenant, previous_owner_id=str(before)),
        _Session(None),  # type: ignore[arg-type]  # a stub of the one call the route makes
    )
    told = _personal(effects)
    assert len(told) == 1
    assert str(before) in next(iter(told))


def test_the_previous_owner_is_read_from_the_changes() -> None:
    old, new = uuid.uuid4(), uuid.uuid4()
    assert parts._owner_before([Change("task.owner_id", str(old), str(new))]) == old  # noqa: SLF001
    assert parts._owner_before([Change("task.owner_id", None, str(new))]) is None  # noqa: SLF001
    assert parts._owner_before([Change("task.status", "open", "done")]) is None  # noqa: SLF001
