"""Runs the modules' periodic jobs inside the consumers worker (app/shared/schedules.py).

Each schedule gets its own loop. A run holds `pg_try_advisory_xact_lock` on a key derived from
the schedule's name for its whole duration, so with several worker replicas exactly one runs a
given tick and the others skip it. A failing run is logged and retried on the next tick.

Every schedule used to start in the same second, and each run holds one connection for its lock
plus those its handler opens, so twenty-odd schedules exhausted the pool ("QueuePool limit of
size 10 overflow 10 reached") on the first tick. So:
- each schedule's first run waits a random part of its period (at most FIRST_RUN_SPREAD
  seconds), spreading the start;
- one gate per worker lets at most `concurrency(settings)` runs work at a time, well under the
  pool, leaving room for the event consumers. A run that waits keeps its own period from its
  start.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable, Iterable

from sqlalchemy import text

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.modules import ModuleSpec
from app.shared.schedules import ScheduleRegistrationError, ScheduleSpec
from workers import runtime

log = get_logger(__name__)
LOCK_CLASS = 724119  # first key of the two-int advisory lock: "module schedules"
FIRST_RUN_SPREAD = 30.0  # seconds: the latest first run of any schedule after the worker starts
CONNECTIONS_PER_RUN = 4  # the lock's own, plus what a handler typically holds at once


def concurrency(settings: Settings) -> int:
    """How many schedule runs may work at once: a quarter of the pool, at least one."""
    return max(1, (settings.db_pool_size + settings.db_max_overflow) // CONNECTIONS_PER_RUN)


def first_delay(spec: ScheduleSpec, chance: Callable[[], float] = random.random) -> float:
    """When this schedule's first run starts: a random part of its period, spread-capped."""
    return chance() * min(spec.every_seconds, FIRST_RUN_SPREAD)


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


Tick = Callable[[ScheduleSpec, Database, Settings], Awaitable[bool]]


async def run_schedule(  # noqa: PLR0913 - the schedule, its collaborators and the gate
    spec: ScheduleSpec,
    database: Database,
    settings: Settings,
    stop: asyncio.Event,
    *,
    gate: asyncio.Semaphore | None = None,
    delay: float | None = None,
    tick: Tick = run_once,
) -> None:
    """Run `spec` every `every_seconds` until `stop`, after a spread first delay, gated."""
    await runtime.pause(stop, first_delay(spec) if delay is None else delay)
    gate = gate or asyncio.Semaphore(concurrency(settings))
    while not stop.is_set():
        try:
            async with gate:
                await tick(spec, database, settings)
        except Exception:
            log.exception("schedule_failed", schedule=spec.name)
        await runtime.pause(stop, spec.every_seconds)
