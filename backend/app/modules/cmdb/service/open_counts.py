"""Linked record counts per CI: map badges and Associations counters (REQ-CMDB-009, 019).

The map's open badges and the Associations counters, open and total per type. The S2 port,
widened in S5; work_items fills it.

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
- (e) registered through `register_open_counts`, the CMDB's public interface;
- (f) S5 (REQ-CMDB-019): open and total per type, for incidents, service requests, problems,
  changes and releases; total counts every visible linked record, open those not finished.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.domain.relationships import NODE_MAX
from app.modules.identity_access import Subject

# The work item types a CI's Associations count (REQ-CMDB-019), as work_items' type codes.
LINKED_TYPES: tuple[str, ...] = ("incident", "service_request", "problem", "change", "release")


@dataclass(frozen=True, slots=True)
class Count:
    """Records of one type linked to a CI that the reader may see: open, and all of them."""

    open: int = 0
    total: int = 0


@dataclass(frozen=True, slots=True)
class OpenCounts:
    """Open records linked to one CI that the reader may see (the map's node badges)."""

    incident: int = 0
    problem: int = 0
    change: int = 0


class OpenCountsPort(Protocol):
    """What work_items answers (S5): per CI and type, open and total, batched per type.

    `{ci_id: {type_code: Count}}` for up to NODE_MAX CIs and the LINKED_TYPES; a CI or type
    with nothing linked may be left out (it reads as zero). Each type through its own view
    scope, so no count includes a record the reader may not see (a).
    """

    async def linked_counts(
        self, session: AsyncSession, subject: Subject, ci_ids: Sequence[uuid.UUID]
    ) -> Mapping[uuid.UUID, Mapping[str, Count]]:
        """Counts per CI and type."""
        ...


_PORTS: list[OpenCountsPort] = []


def register_open_counts(port: OpenCountsPort) -> None:
    """Register the counts port (work_items' import does, in S5; idempotent)."""
    if port not in _PORTS:
        _PORTS.clear()  # one port: the latest registration wins
        _PORTS.append(port)


async def linked_counts_for(
    session: AsyncSession, subject: Subject, ci_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Count]] | None:
    """Every LINKED_TYPES count for each CI, or None while no port is registered."""
    if not _PORTS:
        return None
    unique = list(dict.fromkeys(ci_ids))[:NODE_MAX]
    if not unique:
        return {}
    found = await _PORTS[0].linked_counts(session, subject, unique)
    return {
        ci_id: {code: found.get(ci_id, {}).get(code, Count()) for code in LINKED_TYPES}
        for ci_id in unique
    }


async def counts_for(
    session: AsyncSession, subject: Subject, ci_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, OpenCounts] | None:
    """The map's open badges for the CIs, or None while no port is registered ("no counts yet")."""
    linked = await linked_counts_for(session, subject, ci_ids)
    if linked is None:
        return None
    return {
        ci_id: OpenCounts(
            incident=by_type["incident"].open,
            problem=by_type["problem"].open,
            change=by_type["change"].open,
        )
        for ci_id, by_type in linked.items()
    }
