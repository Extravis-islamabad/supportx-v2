"""Announcement domain rules without I/O: status moves, visibility in time, publish checks."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.announcements.domain.announcement import (
    MACHINE,
    AnnouncementAction,
    AnnouncementAudience,
    AnnouncementStatus,
    AnnouncementVisibility,
    Window,
    next_change,
    publish_problems,
    visibility,
)
from app.shared.domain import InvalidTransition

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


@pytest.mark.parametrize(
    ("status", "action", "target"),
    [
        (AnnouncementStatus.DRAFT, AnnouncementAction.PUBLISH, AnnouncementStatus.PUBLISHED),
        (AnnouncementStatus.DRAFT, AnnouncementAction.ARCHIVE, AnnouncementStatus.ARCHIVED),
        (AnnouncementStatus.PUBLISHED, AnnouncementAction.UNPUBLISH, AnnouncementStatus.DRAFT),
        (AnnouncementStatus.PUBLISHED, AnnouncementAction.ARCHIVE, AnnouncementStatus.ARCHIVED),
        (AnnouncementStatus.ARCHIVED, AnnouncementAction.REOPEN, AnnouncementStatus.DRAFT),
    ],
)
def test_allowed_moves(
    status: AnnouncementStatus, action: AnnouncementAction, target: AnnouncementStatus
) -> None:
    assert MACHINE.apply(status, action) == target


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (AnnouncementStatus.DRAFT, AnnouncementAction.UNPUBLISH),
        (AnnouncementStatus.DRAFT, AnnouncementAction.REOPEN),
        (AnnouncementStatus.PUBLISHED, AnnouncementAction.PUBLISH),
        (AnnouncementStatus.PUBLISHED, AnnouncementAction.REOPEN),
        (AnnouncementStatus.ARCHIVED, AnnouncementAction.PUBLISH),
        (AnnouncementStatus.ARCHIVED, AnnouncementAction.ARCHIVE),
        (AnnouncementStatus.ARCHIVED, AnnouncementAction.UNPUBLISH),
    ],
)
def test_every_other_move_is_refused(
    status: AnnouncementStatus, action: AnnouncementAction
) -> None:
    with pytest.raises(InvalidTransition) as raised:
        MACHINE.apply(status, action)
    assert (raised.value.status, raised.value.action) == (status, action)


def test_actions_keep_one_fixed_order_for_the_ui() -> None:
    assert MACHINE.actions == ("publish", "unpublish", "archive", "reopen")
    assert list(MACHINE.actions_from(AnnouncementStatus.PUBLISHED)) == [
        AnnouncementAction.UNPUBLISH,
        AnnouncementAction.ARCHIVE,
    ]


@pytest.mark.parametrize(
    ("status", "window", "expected", "changes_at"),
    [
        (AnnouncementStatus.DRAFT, Window(NOW + HOUR), AnnouncementVisibility.HIDDEN, None),
        (AnnouncementStatus.ARCHIVED, Window(), AnnouncementVisibility.HIDDEN, None),
        (AnnouncementStatus.PUBLISHED, Window(), AnnouncementVisibility.LIVE, None),
        (
            AnnouncementStatus.PUBLISHED,
            Window(NOW + HOUR, NOW + 2 * HOUR),
            AnnouncementVisibility.SCHEDULED,
            NOW + HOUR,
        ),
        (
            AnnouncementStatus.PUBLISHED,
            Window(NOW - HOUR, NOW + HOUR),
            AnnouncementVisibility.LIVE,
            NOW + HOUR,
        ),
        (
            AnnouncementStatus.PUBLISHED,
            Window(None, NOW),
            AnnouncementVisibility.ENDED,
            None,
        ),  # the end is exclusive
        (
            AnnouncementStatus.PUBLISHED,
            Window(NOW, None),
            AnnouncementVisibility.LIVE,
            None,
        ),  # the start is inclusive
    ],
)
def test_visibility_follows_the_clock(
    status: AnnouncementStatus,
    window: Window,
    expected: AnnouncementVisibility,
    changes_at: datetime | None,
) -> None:
    assert visibility(status, window, NOW) == expected
    assert next_change(status, window, NOW) == changes_at


def test_window_must_end_after_it_starts() -> None:
    assert Window(NOW, NOW).problems() == ["window_end_before_start"]
    assert Window(NOW, NOW - HOUR).problems() == ["window_end_before_start"]
    assert Window(NOW, NOW + HOUR).problems() == []
    assert Window(None, NOW).problems() == []


def problems(
    *,
    body: str = "Mail is down",
    audience: AnnouncementAudience = AnnouncementAudience.EVERYONE,
    units: int = 0,
    window: Window = Window(),  # noqa: B008 - frozen dataclass, safe as a default
) -> list[str]:
    return publish_problems(
        title="Outage", body=body, audience=audience, units=units, window=window, now=NOW
    )


def test_publish_rules() -> None:
    assert problems() == []
    assert problems(body="  ") == ["content_missing"]
    assert problems(audience=AnnouncementAudience.SITES) == ["audience_empty"]
    assert problems(audience=AnnouncementAudience.GROUPS, units=1) == []
    assert problems(window=Window(None, NOW - HOUR)) == ["window_already_ended"]
    # A future window is fine: it is published now and goes live by itself.
    assert problems(window=Window(NOW + HOUR)) == []
