"""Required erasure ports whose modules have none yet (the readiness check, 2026-11-14).

`service_catalog` (lane A) holds person data, so REQUIRED_PORTS lists it and, until it
registers, approval and the job refuse (`erasure_port_missing`). Tests that run the job or
approve stand in no-op ports for it; its real port's PR removes its key here (assets' did).
"""

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.service.person_data import (
    ErasureBatch,
    PersonData,
    register_person_data,
    registered_ports,
    unregister_person_data,
)

PENDING: tuple[str, ...] = ()  # every required port is real: assets (#519), service_catalog (#518)


def _stand_in(key: str) -> PersonData:
    class StandIn:
        module: ClassVar[str] = key
        order: ClassVar[int] = 585  # before files (590): files go last of the owned band
        kinds: ClassVar[frozenset[str]] = frozenset({"nothing_held"})  # never returned (as sla)

        async def erase_person(
            self,
            session: AsyncSession,
            person_id: uuid.UUID,
            *,
            successor_id: uuid.UUID,
            keep_files: Mapping[uuid.UUID, str],
            now: datetime,
            cursor: str | None,
        ) -> ErasureBatch:
            del session, person_id, successor_id, keep_files, now, cursor
            return ErasureBatch({})

    return StandIn()


@contextmanager
def pending_ports_stood_in() -> Iterator[None]:
    """No-op ports for PENDING while a test runs, never replacing a real one, then removed."""
    have = {port.module for port in registered_ports()}
    added = [key for key in PENDING if key not in have]
    for key in added:
        register_person_data(_stand_in(key))
    try:
        yield
    finally:
        for key in added:
            unregister_person_data(key)
