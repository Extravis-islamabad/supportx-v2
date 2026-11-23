"""SLA's slice of a person's erasure (ADR-052 §4; D-171).

SLA holds no person's own data: no owner, no private rows, nothing acting with a person's rights.
What names a person is an ID: an escalation level's recipient, fallback or "reassign to" target,
and who caused a pause. Those IDs stay. They point at the person's anonymised row (ADR-052 §3
step 5), an escalation reaches active people only, and a reassignment to someone who has left
falls back to the group (work_items' `place_person`). So the port changes nothing and counts
nothing (ADR-052: a second call counts zero, and so does the first). It is registered so the
erasure knows SLA was considered, not forgotten.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import ErasureBatch, register_person_data


class Sla:
    """`sla`: nothing of the person's own to erase (band 100-199)."""

    module: ClassVar[str] = "sla"
    order: ClassVar[int] = 190
    kinds: ClassVar[frozenset[str]] = frozenset({"nothing_held"})  # never returned

    async def erase_person(  # noqa: PLR0913 - the port contract
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """Nothing to change (see the module docstring)."""
        del session, person_id, successor_id, keep_files, now, cursor
        return ErasureBatch({})


PORT = Sla()


def register() -> None:
    """At import (the registry refuses the job while it is missing)."""
    register_person_data(PORT)
