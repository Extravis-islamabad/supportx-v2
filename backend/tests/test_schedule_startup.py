"""Schedules start spread out and never hold more of the pool than the gate allows (polish).

Found on the shared stack (2026-11-03): every schedule ran in the consumers worker's first second
and twenty failed with "QueuePool limit of size 10 overflow 10 reached".
"""

import asyncio
from typing import Any

from app.core.config import Settings
from app.shared.schedules import ScheduleSpec
from workers.consumers import schedules


async def _nothing(database: Any, settings: Any) -> None:  # noqa: ANN401 - a schedule handler
    del database, settings


def _settings(pool: int, overflow: int) -> Settings:
    return Settings.load(env_file=None, profile="test").model_copy(
        update={"db_pool_size": pool, "db_max_overflow": overflow}
    )


def test_the_gate_is_a_quarter_of_the_pool_and_at_least_one() -> None:
    assert schedules.concurrency(_settings(10, 10)) == 5
    assert schedules.concurrency(_settings(1, 0)) == 1


def test_first_runs_spread_over_the_period_capped() -> None:
    daily = ScheduleSpec("audit__anchor", 86400, _nothing)
    minutely = ScheduleSpec("integrations__mail_fetch", 60, _nothing)
    fast = ScheduleSpec("work_items__bulk_jobs", 5, _nothing)
    assert schedules.first_delay(daily, lambda: 0.999) < schedules.FIRST_RUN_SPREAD
    assert schedules.first_delay(minutely, lambda: 0.5) == schedules.FIRST_RUN_SPREAD / 2
    assert schedules.first_delay(fast, lambda: 0.999) < 5
    assert schedules.first_delay(fast, lambda: 0.0) == 0


async def test_thirty_schedules_never_run_more_than_the_gate_at_once() -> None:
    settings = _settings(10, 10)
    gate = asyncio.Semaphore(schedules.concurrency(settings))
    stop = asyncio.Event()
    running, most, done = 0, 0, 0
    specs = [ScheduleSpec(f"audit__job{n}", 3600, _nothing) for n in range(30)]

    async def tick(spec: ScheduleSpec, database: Any, settings: Any) -> bool:  # noqa: ANN401
        nonlocal running, most, done
        del spec, database, settings
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.01)  # a run holding its connections
        running -= 1
        done += 1
        if done == len(specs):
            stop.set()
        return True

    await asyncio.wait_for(
        asyncio.gather(
            *(
                schedules.run_schedule(spec, None, settings, stop, gate=gate, delay=0, tick=tick)  # type: ignore[arg-type]  # no database: the tick is a fake
                for spec in specs
            )
        ),
        timeout=10,
    )
    assert done == len(specs)  # every schedule ran
    assert most == schedules.concurrency(settings)  # gated, and the gate was used in full
