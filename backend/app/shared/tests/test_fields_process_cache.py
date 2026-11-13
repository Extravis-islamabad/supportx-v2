"""The data-key cache is per event loop and Valkey (lane B, 2026-11-13; ADR-050).

A Valkey client belongs to the loop it was made on: one cache per loop, and a closed loop's
cache is dropped. One loop and one Valkey (production) keep one cache.
"""

import asyncio

from app.shared.fields import process_cache
from conftest import make_settings


def _cache_in_new_loop(settings: object) -> object:
    async def inner() -> object:
        return process_cache(settings)  # type: ignore[arg-type]  # Settings, from make_settings

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(inner())
    finally:
        loop.close()


async def test_one_loop_and_one_valkey_keep_one_cache() -> None:
    settings = make_settings(valkey_url="valkey://localhost:6379/0")
    assert process_cache(settings) is process_cache(settings)
    other = make_settings(valkey_url="valkey://localhost:6379/0")  # another key prefix
    assert process_cache(other) is not process_cache(settings)


def test_each_loop_gets_its_own_cache() -> None:
    settings = make_settings(valkey_url="valkey://localhost:6379/0")
    first = _cache_in_new_loop(settings)
    second = _cache_in_new_loop(settings)
    assert first is not None
    assert first is not second  # never a client bound to a closed loop


def test_no_valkey_no_cache() -> None:
    assert _cache_in_new_loop(make_settings(valkey_url=None)) is None
