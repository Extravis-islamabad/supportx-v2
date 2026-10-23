"""Announcements: statuses, visibility in time, and the rules every save must keep (WP-012).

Pure domain code, no I/O. Two independent ideas:

* **status** (draft → published → archived) changes only through named actions (MACHINE);
* **visibility** says whether a *published* announcement is on screens right now, given its
  optional publish window: scheduled (before `publish_from`), live, ended (after
  `publish_until`). It is computed from the clock, never stored, so it cannot go stale; screens
  are told how long until it next changes (`seconds_until_next_change`) and refresh then.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.shared.domain import StatusMachine

TITLE_MAX = 200
BODY_MAX = 20_000
REASON_MAX = 500
AUDIENCE_MAX = 50


class AnnouncementStatus(StrEnum):
    """Lifecycle of an announcement. Stored as a code; the UI shows a label."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class AnnouncementSeverity(StrEnum):
    """How prominent it is: one scale, no mixing of "high" and "affects users"."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AnnouncementAudience(StrEnum):
    """Who it is for: everyone in the tenant, or members of chosen sites / support groups."""

    EVERYONE = "everyone"
    SITES = "sites"
    GROUPS = "groups"


class AnnouncementVisibility(StrEnum):
    """Whether it is on screens now (computed)."""

    HIDDEN = "hidden"  # draft or archived
    SCHEDULED = "scheduled"  # published, window not started
    LIVE = "live"
    ENDED = "ended"  # published, window over


class AnnouncementAction(StrEnum):
    """AnnouncementStatus actions, in the order the UI shows them."""

    PUBLISH = "publish"
    UNPUBLISH = "unpublish"
    ARCHIVE = "archive"
    REOPEN = "reopen"


MACHINE = StatusMachine(
    {
        AnnouncementStatus.DRAFT: {
            AnnouncementAction.PUBLISH: AnnouncementStatus.PUBLISHED,
            AnnouncementAction.ARCHIVE: AnnouncementStatus.ARCHIVED,
        },
        AnnouncementStatus.PUBLISHED: {
            AnnouncementAction.UNPUBLISH: AnnouncementStatus.DRAFT,
            AnnouncementAction.ARCHIVE: AnnouncementStatus.ARCHIVED,
        },
        AnnouncementStatus.ARCHIVED: {AnnouncementAction.REOPEN: AnnouncementStatus.DRAFT},
    },
    order=tuple(AnnouncementAction),
)

# Actions that may carry a reason (kept in the history, shown on the History tab).
REASON_ACTIONS = frozenset({AnnouncementAction.UNPUBLISH, AnnouncementAction.ARCHIVE})


@dataclass(frozen=True)
class Window:
    """The optional publish window (UTC instants)."""

    publish_from: datetime | None = None
    publish_until: datetime | None = None

    def problems(self) -> list[str]:
        """Rule codes this window breaks (empty when fine)."""
        if (
            self.publish_from is not None
            and self.publish_until is not None
            and self.publish_until <= self.publish_from
        ):
            return ["window_end_before_start"]
        return []


def visibility(status: str, window: Window, now: datetime) -> AnnouncementVisibility:
    """Whether the announcement is on screens at `now`."""
    if status != AnnouncementStatus.PUBLISHED:
        return AnnouncementVisibility.HIDDEN
    if window.publish_from is not None and now < window.publish_from:
        return AnnouncementVisibility.SCHEDULED
    if window.publish_until is not None and now >= window.publish_until:
        return AnnouncementVisibility.ENDED
    return AnnouncementVisibility.LIVE


def next_change(status: str, window: Window, now: datetime) -> datetime | None:
    """When its visibility changes next by the clock alone (None: not by the clock)."""
    if status != AnnouncementStatus.PUBLISHED:
        return None
    for boundary in (window.publish_from, window.publish_until):
        if boundary is not None and boundary > now:
            return boundary
    return None


# Why publishing is refused (409 cannot_publish `reason`, and the disabled Publish button).
PUBLISH_PROBLEMS = (
    "window_end_before_start",
    "content_missing",
    "audience_empty",
    "window_already_ended",
)


def publish_problems(  # noqa: PLR0913 - every input of the rule, keyword-only
    *, title: str, body: str, audience: str, units: int, window: Window, now: datetime
) -> list[str]:
    """Why it cannot be published right now (empty when it can)."""
    problems = window.problems()
    if not title.strip() or not body.strip():
        problems.append("content_missing")
    if audience != AnnouncementAudience.EVERYONE and units == 0:
        problems.append("audience_empty")
    if window.publish_until is not None and window.publish_until <= now:
        problems.append("window_already_ended")
    return problems
