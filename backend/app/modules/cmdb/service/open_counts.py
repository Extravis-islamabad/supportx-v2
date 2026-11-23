"""Open ticket counts per CI on maps and business views (REQ-CMDB-009; the S2 port, S5 fills it).

The counts need the work item ↔ CI link (`work_item_cis`), which work_items builds in WP-053 S5
(lane A). Until then no port is registered and every node says "no counts yet" (`None`), never
a zero that would read as "nothing open".

The port lives in work_items' public service and is registered here at its import, like the
erasure mentions ports, so cmdb never imports work_items (lane A's conditions, the design §6):

- (a) only records the subject may see, through each type's own view scope (never all, then
  filtered), so no total includes an unseen record;
- (b) open = the status category is not resolved, closed or canceled; deleted or trashed rows
  never count;
- (c) one query per type for all the `ci_ids`, at most the map's node cap (`NODE_MAX`);
- (d) its event carries the CI IDs and the record's ID and type, never counts: the map refetches
  the counts (§8.3), since a group or assignee change alters what each person sees;
- (e) registered through `register_open_counts`, the CMDB's public interface.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.domain.relationships import NODE_MAX
from app.modules.identity_access import Subject


@dataclass(frozen=True, slots=True)
class OpenCounts:
    """Open records linked to one CI that the reader may see."""

    incident: int = 0
    problem: int = 0
    change: int = 0


class OpenCountsPort(Protocol):
    """What work_items answers (S5): counts for up to NODE_MAX CIs, batched per type."""

    async def open_counts(
        self, session: AsyncSession, subject: Subject, ci_ids: Sequence[uuid.UUID]
    ) -> Mapping[uuid.UUID, OpenCounts]:
        """Counts per CI; a CI with nothing open may be left out (it reads as all zero)."""
        ...


_PORTS: list[OpenCountsPort] = []


def register_open_counts(port: OpenCountsPort) -> None:
    """Register the counts port (work_items' import does, in S5; idempotent)."""
    if port not in _PORTS:
        _PORTS.clear()  # one port: the latest registration wins
        _PORTS.append(port)


async def counts_for(
    session: AsyncSession, subject: Subject, ci_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, OpenCounts] | None:
    """Counts for the CIs, or None while no port is registered ("no counts yet")."""
    if not _PORTS:
        return None
    unique = list(dict.fromkeys(ci_ids))[:NODE_MAX]
    if not unique:
        return {}
    found = await _PORTS[0].open_counts(session, subject, unique)
    return {ci_id: found.get(ci_id, OpenCounts()) for ci_id in unique}
