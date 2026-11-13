"""Every locked notification event really reaches the person (lane B's #480 guard).

A locked event's shipped default can never be changed by an admin, so that default must already
be the strongest one: required (no personal opt-out), enabled, and in the notification centre.
Collected from the record sources the modules register, so a new locked event that breaks this
fails here.
"""

from app.core.modules import discover_modules
from app.shared.notifications.ports import NotificationChannel, NotificationEvent, record_sources


def _locked() -> list[NotificationEvent]:
    discover_modules()  # the modules register their record sources at import
    return [event for source in record_sources() for event in source.events if event.locked]


def test_break_glass_is_locked() -> None:
    assert "break_glass.signed_in" in {event.code for event in _locked()}


def test_every_locked_event_is_required_enabled_and_in_app() -> None:
    weak = [
        event.code
        for event in _locked()
        if not event.required
        or not event.default.enabled
        or NotificationChannel.IN_APP not in event.default.channels
        or not event.default.recipients
    ]
    assert weak == [], "a locked event must be required, on, in-app and reach someone"
