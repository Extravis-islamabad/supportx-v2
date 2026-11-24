"""Guard: each record type offers exactly the trigger events it should (WP-053 S5d, C1).

`RecordType.offered_events` defaults to `WORK_ITEM_EVENTS` (lane C's shape), so adding a trigger
event code never offers it to an existing type by accident. Every work item type registered by
the built app keeps today's seven and never a configuration item's events; a type that offers
something else must be listed here on purpose.
"""

from app.modules.automation.domain.triggers import WORK_ITEM_EVENTS, TriggerEvent
from app.modules.automation.service.registry import record_type, record_types
from tooling.route_permissions import build_app

CI_EVENTS = frozenset(
    {
        TriggerEvent.RELATIONSHIP_ADDED,
        TriggerEvent.RELATIONSHIP_REMOVED,
        TriggerEvent.DOWNTIME_STARTED,
    }
)
# Types that offer their own set, on purpose (and what it is checked against below).
OWN_OFFERS: dict[str, frozenset[TriggerEvent]] = {
    # WP-053 S5d: a CI's own six, the three CI events included.
    "cmdb_ci": frozenset(
        {
            TriggerEvent.CREATED,
            TriggerEvent.UPDATED,
            TriggerEvent.STATUS_CHANGED,
            *CI_EVENTS,
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
        expected = OWN_OFFERS.get(code, WORK_ITEM_EVENTS)
        assert kind.offered_events == expected, code
        if code not in OWN_OFFERS:
            assert not (kind.offered_events & CI_EVENTS), code
