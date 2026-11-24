"""Guard: each record type offers exactly the trigger events it should (WP-053 S5d, C1).

`RecordType.offered_events` defaults to `WORK_ITEM_EVENTS` (lane C's shape), so adding a trigger
event code never offers it to an existing type by accident. Every work item type registered by
the built app keeps today's seven and never a configuration item's events; a type that offers
something else must be listed here on purpose.
"""

import uuid
from typing import TYPE_CHECKING, cast

from app.modules.automation.domain.triggers import WORK_ITEM_EVENTS, TriggerEvent
from app.modules.automation.service.registry import (
    _READERS,
    RecordEvent,
    record_type,
    record_types,
)
from app.modules.automation.service.triggers import TRIGGER_EVENT_TYPES
from app.modules.automation.service.triggers import _fires as fires
from app.modules.cmdb.service.automation import read_event as ci_reader
from app.modules.work_items.domain.types import TYPES
from app.modules.work_items.service.automated import read_event as work_item_reader
from app.shared.events import EventEnvelope
from tooling.route_permissions import build_app

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

CI_EVENTS = frozenset(
    {
        TriggerEvent.RELATIONSHIP_ADDED,
        TriggerEvent.RELATIONSHIP_REMOVED,
        TriggerEvent.DOWNTIME_STARTED,
    }
)
# Work item types with a stage model (ADR-041): only they offer stage_entered (lane A, S5d).
STAGED = frozenset(w.code.value for w in TYPES.values() if w.stages is not None)
# Types that offer their own set, on purpose (and what it is checked against below).
OWN_OFFERS: dict[str, frozenset[TriggerEvent]] = {
    # WP-053 S5d: a CI's own six, the three CI events included.
    # downtime_started joins with its reader, after #608.
    "cmdb_ci": frozenset(
        {
            TriggerEvent.CREATED,
            TriggerEvent.UPDATED,
            TriggerEvent.STATUS_CHANGED,
            TriggerEvent.RELATIONSHIP_ADDED,
            TriggerEvent.RELATIONSHIP_REMOVED,
        }
    ),
}


def test_every_work_item_type_keeps_todays_events_and_no_ci_event() -> None:
    build_app()  # registers every module's record types
    codes = record_types()
    assert codes, "no record type registered: the guard would pass on nothing"
    for code in codes:
        kind = record_type(code)
        assert kind is not None
        staged = code in STAGED
        unstaged = WORK_ITEM_EVENTS - {TriggerEvent.STAGE_ENTERED}
        expected = OWN_OFFERS.get(code, WORK_ITEM_EVENTS if staged else unstaged)
        assert kind.offered_events == expected, code
        if code not in OWN_OFFERS:
            assert not (kind.offered_events & CI_EVENTS), code


def test_every_event_with_a_reader_reaches_the_trigger_consumers() -> None:
    """A reader the consumers never subscribe to would make a type's triggers silently dead."""
    build_app()
    assert set(_READERS) <= set(TRIGGER_EVENT_TYPES), sorted(
        set(_READERS) - set(TRIGGER_EVENT_TYPES)
    )


def _envelope(event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "schema_version": 1,
            "tenant_id": str(uuid.uuid4()),
            "actor": {"type": "system", "id": "tests"},
            "occurred_at": "2026-11-24T12:00:00Z",
            "aggregate_type": "x",
            "aggregate_id": str(uuid.uuid4()),
            "payload": payload,
        }
    )


async def test_the_work_item_reader_still_gives_exactly_one_record_per_event() -> None:
    """R1: wrapping the reader as a list changed nothing for work items."""
    item = uuid.uuid4()
    for event_type, event in (
        ("work_items.work_item.created", TriggerEvent.CREATED),
        ("work_items.work_item.updated", TriggerEvent.UPDATED),
        ("work_items.work_item.assigned", TriggerEvent.ASSIGNED),
    ):
        found = await work_item_reader(
            cast("AsyncSession", None),
            _envelope(
                event_type,
                {"work_item_id": str(item), "type": "incident", "changed_fields": ["title"]},
            ),
        )
        assert [(f.record_type, f.record_id, f.event) for f in found] == [("incident", item, event)]
    assert await work_item_reader(cast("AsyncSession", None), _envelope("work_items.x.y", {})) == []


async def test_a_relationship_gives_each_end_once_in_order_and_nothing_about_the_other() -> None:
    """R1, R3 and C2: both ends, sorted, de-duplicated, each saying only "relationships"."""
    ends = sorted((uuid.uuid4() for _ in range(2)), key=str)
    found = await ci_reader(
        cast("AsyncSession", None),
        _envelope(
            "cmdb.relationship.changed",
            {
                "ci_id": str(ends[1]),
                "action": "added",
                "type_id": str(uuid.uuid4()),
                "relationship_ids": [str(uuid.uuid4())],
                "other_ci_ids": [str(ends[0]), str(ends[1])],  # a repeat of the source
            },
        ),
    )
    assert [f.record_id for f in found] == ends
    for f in found:
        assert f.event == TriggerEvent.RELATIONSHIP_ADDED
        assert list(f.changed) == ["relationships"]
        assert dict(f.known_before) == {}
        assert f.action is None


async def test_every_event_the_ci_offers_is_one_its_reader_can_produce() -> None:
    """Lane C: an event offered with nothing to fire it is a trigger that silently never runs."""
    ci = str(uuid.uuid4())
    other = str(uuid.uuid4())
    produced: set[TriggerEvent] = set()
    cases: list[tuple[str, dict[str, object]]] = [
        ("cmdb.ci.created", {"ci_id": ci, "type_id": ci, "source": "manual"}),
        ("cmdb.ci.updated", {"ci_id": ci, "type_id": ci, "changed_fields": ["name"]}),
        ("cmdb.ci.updated", {"ci_id": ci, "type_id": ci, "changed_fields": ["state_id"]}),
    ]
    for action in ("added", "removed"):
        relationship: dict[str, object] = {
            "ci_id": ci,
            "action": action,
            "type_id": ci,
            "relationship_ids": [],
            "other_ci_ids": [other],
        }
        cases.append(("cmdb.relationship.changed", relationship))
    for event_type, payload in cases:
        assert event_type in TRIGGER_EVENT_TYPES
        found = await ci_reader(cast("AsyncSession", None), _envelope(event_type, payload))
        produced |= {f.event for f in found if f.event is not None}
    kind = record_type("cmdb_ci")
    assert kind is not None
    assert kind.offered_events <= produced, sorted(kind.offered_events - produced)


def _status(changed: list[str]) -> RecordEvent:
    return RecordEvent("cmdb_ci", uuid.uuid4(), TriggerEvent.STATUS_CHANGED, changed=changed)


def test_a_state_saved_with_other_fields_is_also_an_update_where_status_is_an_edit() -> None:
    """Lane C (2): a CI's combined save reaches "updated" triggers, once."""
    assert fires(["updated"], _status(["state_id", "criticality"]), status_is_an_edit=True)
    # A state alone is a state change, not an "updated" one.
    assert not fires(["updated"], _status(["state_id"]), status_is_an_edit=True)
    # Work item types keep their own status moves apart from edits.
    assert not fires(["updated"], _status(["state_id", "criticality"]))
