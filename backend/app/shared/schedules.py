"""Periodic jobs that modules declare (WP-018): `ModuleSpec(schedules=[ScheduleSpec(...)])`.

The consumers worker runs every schedule every `every_seconds`. A schedule runs on one worker at
a time across replicas: each run holds a PostgreSQL transaction-level advisory lock named after
the schedule, and a worker that cannot take it skips that tick. Handlers must be idempotent and
quick to re-run (they decide themselves whether there is work, e.g. "last anchor older than an
hour"). Temporal (WP-025, D-055) takes over durable timers later; these are housekeeping loops.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.config import Settings
from app.core.database import Database

ScheduleHandler = Callable[[Database, Settings], Awaitable[None]]
_NAME = re.compile(r"^[a-z][a-z0-9_]*__[a-z][a-z0-9_]*$")


class ScheduleRegistrationError(RuntimeError):
    """A schedule declaration breaks the rules. Always a programming error."""


@dataclass(frozen=True)
class ScheduleSpec:
    """One periodic job: `<module>__<purpose>`, its period and its handler."""

    name: str
    every_seconds: float
    handler: ScheduleHandler

    def __post_init__(self) -> None:
        """Reject bad names and periods at declaration time."""
        if not _NAME.fullmatch(self.name):
            msg = f"schedule {self.name!r} must be named '<module>__<purpose>'"
            raise ScheduleRegistrationError(msg)
        if self.every_seconds <= 0:
            msg = f"schedule {self.name!r} needs a positive period"
            raise ScheduleRegistrationError(msg)
