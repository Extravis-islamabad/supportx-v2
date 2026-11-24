"""CI downtimes (WP-053 S5b; REQ-CMDB-020). Pure: no I/O.

A downtime is scheduled, active or completed, from its times alone: scheduled before it starts,
active from its start until its end, completed once it ends. A change's or release's planned
and actual downtimes (REQ-CHG-063, -064) and an incident's unplanned one reach a CI from
work_items' `work_items.downtime.changed`; a downtime recorded on the CI by hand is the CMDB's
own (`manual`), the only kind edited here. The sweep moves the stored state as time passes, so
a CI shows "active" at the start without a refresh (AC1).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

DESCRIPTION_MAX = 2000
LONGEST = timedelta(days=366)  # a hand-recorded downtime spans at most this


class DowntimeState(StrEnum):
    """Where a downtime is in time (`cmdb_downtime_state.<code>`)."""

    SCHEDULED = "scheduled"
    ACTIVE = "active"
    COMPLETED = "completed"


class DowntimeSource(StrEnum):
    """Where it came from (`cmdb_downtime_source.<code>`); only `manual` is edited here."""

    CHANGE = "change"
    RELEASE = "release"
    INCIDENT = "incident"
    MANUAL = "manual"


class DowntimePhase(StrEnum):
    """Planned ahead, or what actually happened (work_items' phases)."""

    PLANNED = "planned"
    ACTUAL = "actual"


# work_items' record type codes that send downtimes, and the source each becomes.
SOURCE_OF_TYPE = {
    "change": DowntimeSource.CHANGE,
    "release": DowntimeSource.RELEASE,
    "incident": DowntimeSource.INCIDENT,
}


def state_at(starts_at: datetime, ends_at: datetime | None, now: datetime) -> DowntimeState:
    """The state at `now`: an open-ended one is active from its start until it is given an end."""
    if now < starts_at:
        return DowntimeState.SCHEDULED
    if ends_at is not None and now >= ends_at:
        return DowntimeState.COMPLETED
    return DowntimeState.ACTIVE


@dataclass(frozen=True)
class Problem:
    """A field and the code of what is wrong with it."""

    field: str
    code: str


def check_manual(
    starts_at: datetime, ends_at: datetime | None, description: str | None
) -> list[Problem]:
    """What is wrong with a hand-recorded downtime (empty when it may be saved)."""
    problems: list[Problem] = []
    if starts_at.tzinfo is None:
        problems.append(Problem("starts_at", "timezone_required"))
    if ends_at is not None:
        if ends_at.tzinfo is None:
            problems.append(Problem("ends_at", "timezone_required"))
        elif starts_at.tzinfo is not None:
            if ends_at <= starts_at:
                problems.append(Problem("ends_at", "end_before_start"))
            elif ends_at - starts_at > LONGEST:
                problems.append(Problem("ends_at", "downtime_too_long"))
    if description is not None and len(description) > DESCRIPTION_MAX:
        problems.append(Problem("description", "value_too_long"))
    return problems


def is_stale(stored_version: int | None, incoming_version: int) -> bool:
    """An event at or below the version already applied changes nothing (out of order, replayed)."""
    return stored_version is not None and incoming_version <= stored_version
