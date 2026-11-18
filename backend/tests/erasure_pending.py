"""Required erasure and mention ports whose modules have none yet (the readiness check).

A module that holds person data is listed in REQUIRED_PORTS (or names people in its text, in
REQUIRED_MENTION_PORTS) before its port exists, so approval refuses until it registers
(`erasure_port_missing`, `erasure_report_unavailable`). Tests that build a report, approve or
run the job stand in no-op ports for those keys; the real port's PR removes its key here.
"""

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.domain.mentions import MentionTerms
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.service.person_data import (
    ErasureBatch,
    Mention,
    MentionBatch,
    PersonData,
    PersonMentions,
    mention_ports,
    register_mentions,
    register_person_data,
    registered_ports,
    unregister_mentions,
    unregister_person_data,
)

PENDING: tuple[str, ...] = ()  # every required port is real: assets (#519), service_catalog (#518)
# Every mentions port is real: cmdb joined with 0176 (CI names, descriptions and snapshots).
PENDING_MENTIONS: tuple[str, ...] = ()


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


def _mentions_stand_in(key: str) -> PersonMentions:
    class StandIn:
        module: ClassVar[str] = key

        async def find_mentions(
            self,
            session: AsyncSession,
            person_id: uuid.UUID,
            *,
            terms: MentionTerms,
            cursor: str | None,
        ) -> MentionBatch:
            del session, person_id, terms, cursor
            return MentionBatch(())

        async def redact_mention(
            self,
            session: AsyncSession,
            mention: Mention,
            *,
            terms: MentionTerms,
            marker: str,
            now: datetime,
        ) -> bool:
            del session, mention, terms, marker, now
            return False

        async def passage(
            self, session: AsyncSession, subject: Subject, mention: Mention
        ) -> str | None:
            del session, subject, mention
            return None

    return StandIn()


@contextmanager
def pending_ports_stood_in() -> Iterator[None]:
    """No-op ports for PENDING and PENDING_MENTIONS while a test runs, never replacing a real
    one, then removed."""
    have = {port.module for port in registered_ports()}
    added = [key for key in PENDING if key not in have]
    have_mentions = {port.module for port in mention_ports()}
    added_mentions = [key for key in PENDING_MENTIONS if key not in have_mentions]
    for key in added:
        register_person_data(_stand_in(key))
    for key in added_mentions:
        register_mentions(_mentions_stand_in(key))
    try:
        yield
    finally:
        for key in added:
            unregister_person_data(key)
        for key in added_mentions:
            unregister_mentions(key)
