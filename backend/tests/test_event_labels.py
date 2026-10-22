"""Every registered event type has an English and an Arabic label (CLAUDE.md rule d, WP-007).

Event types appear in activity feeds and audit views; the UI renders `event_type.<type>`
through the labels package and never shows the raw code.
"""

import pytest

from app.core.modules import discover_modules
from app.shared.events import EventRegistry
from tests.test_error_labels import label_keys


@pytest.mark.parametrize("locale", ["en", "ar"])
def test_every_event_type_has_a_label(locale: str) -> None:
    registry = EventRegistry.from_modules(discover_modules())
    missing = sorted(
        f"event_type.{event_type}"
        for event_type in registry.event_types()
        if f"event_type.{event_type}" not in label_keys(locale)
    )
    assert missing == [], f"add these keys to packages/labels/src/resources/{locale}.ts"
