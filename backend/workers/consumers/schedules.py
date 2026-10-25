"""Runs the modules' periodic jobs inside the consumers worker (app/shared/schedules.py).

Each schedule gets its own loop. A run holds `pg_try_advisory_xact_lock` on a key derived from
the schedule's name for its whole duration, so with several worker replicas exactly one runs a
given tick and the others skip it. A failing run is logged and retried on the next tick.
"""

import asyncio
from collections.abc import Iterable

from sqlalchemy import text

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.modules import ModuleSpec
from app.shared.schedules import ScheduleRegistrationError, ScheduleSpec
from workers import runtime

log = get_logger(__name__)
LOCK_CLASS = 724119  # first key of the two-int advisory lock: "module schedules"


def schedules_from_modules(modules: Iterable[ModuleSpec]) -> list[ScheduleSpec]:
    """Every declared schedule, checked for unique names and the module prefix."""
    found: list[ScheduleSpec] = []
    names: set[str] = set()
    for module in modules:
        for spec in module.schedules:
            if not isinstance(spec, ScheduleSpec):
                msg = f"{module.name}: schedules must be ScheduleSpec instances"
                raise ScheduleRegistrationError(msg)
            if not spec.name.startswith(f"{module.name}__") or spec.name in names:
                msg = f"schedule {spec.name!r}: wrong module prefix or declared twice"
                raise ScheduleRegistrationError(msg)
            names.add(spec.name)
            found.append(spec)
    return found


async def run_once(spec: ScheduleSpec, database: Database, settings: Settings) -> bool:
    """One tick: True if this worker held the lock and ran the handler."""
    async with database.platform_session() as session:
        locked = await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:c, hashtext(:n))"),
            {"c": LOCK_CLASS, "n": spec.name},
        )
        if not locked:
            return False
        await spec.handler(database, settings)
        return True


async def run_schedule(
    spec: ScheduleSpec, database: Database, settings: Settings, stop: asyncio.Event
) -> None:
    """Run `spec` every `every_seconds` until `stop`."""
    while not stop.is_set():
        try:
            await run_once(spec, database, settings)
        except Exception:
            log.exception("schedule_failed", schedule=spec.name)
        await runtime.pause(stop, spec.every_seconds)
