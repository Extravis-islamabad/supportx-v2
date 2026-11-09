"""Every notification event and its area has a label (rule d; settings QA CHN-01).

Admin > Notifications groups the events by the area they belong to (the record type in front of
the event code, `incident.assigned` → `incident`) and names both through labels. Collected from
the record sources the modules register, so a new event or area without labels fails here.
"""

import pytest

from app.core.modules import discover_modules
from app.shared.notifications.ports import record_sources
from tests.test_error_labels import label_keys


def _codes() -> tuple[set[str], set[str]]:
    discover_modules()  # the modules register their record sources at import
    events: set[str] = set()
    areas: set[str] = set()
    for source in record_sources():
        for event in source.events:
            events.add(event.code)
            areas.add(event.code.split(".", 1)[0])
    return events, areas


def test_the_scan_finds_the_known_events() -> None:
    events, areas = _codes()
    assert {"incident.assigned", "kb_article.submitted"} <= events
    assert {"incident", "kb_article", "mailbox"} <= areas


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_every_event_and_area_has_a_label(locale: str) -> None:
    keys = label_keys(locale)
    events, areas = _codes()
    missing = sorted(
        [f"notification_event.{e}" for e in events if f"notification_event.{e}" not in keys]
        + [f"notification_area.{a}" for a in areas if f"notification_area.{a}" not in keys]
    )
    assert missing == [], f"add these keys to packages/labels/src/resources/{locale}.ts"
