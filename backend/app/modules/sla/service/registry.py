"""Record types that have SLAs (WP-025; wp-025-plan.md §3.1, the same pattern as automation).

The sla module never reads work-item tables. A record type registers here when its module is
imported: the fields its policy conditions may use (the shared filter DSL), and nothing else.
Inside a save, the owning module passes a snapshot of the record (field name -> value) to
`sla.on_change`, which returns what to stamp on the record. So `sla` never imports `work_items`.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api.filters import ResourceFields

if TYPE_CHECKING:
    from app.modules.sla.domain.escalation import Level

# The snapshot keys the clock itself reads (beyond the condition fields).
PRIORITY = "priority"
SITE = "site_id"
GROUP = "group_id"
STATUS_CATEGORY = "status_category"
STATUS = "status"
FIRST_RESPONDED_AT = "first_responded_at"

Snapshot = Mapping[str, Any]


@dataclass(frozen=True)
class Fired:
    """One thing the waker fired on a record: a warning, a breach or an escalation level."""

    what: str  # "warning", "breached", "escalated"
    kind: str  # the target kind
    position: int | None = None  # the level, for "escalated"
    run_id: uuid.UUID | None = None
    skipped: bool = False


class FiredHook(Protocol):
    """The owning module stamps the record: SLA columns, history from source "sla", an event."""

    async def __call__(  # noqa: D102 - the protocol's one call, documented on the class
        self,
        session: AsyncSession,
        record_id: uuid.UUID,
        columns: Mapping[str, Any],
        fired: list[Fired],
        *,
        now: datetime,
    ) -> None: ...


class LockHook(Protocol):
    """The owning module locks the record row (FOR UPDATE).

    Every path locks the record before its clocks: the owning module's saves before calling
    `on_change`, the waker through this hook before `fire` locks the clocks. One order, so a
    save and a firing on the same record never deadlock.
    """

    async def __call__(  # noqa: D102 - the protocol's one call, documented on the class
        self, session: AsyncSession, record_id: uuid.UUID
    ) -> None: ...


class ActionsHook(Protocol):
    """The owning module runs a level's actions; one outcome per action, never raising."""

    async def __call__(  # noqa: D102 - the protocol's one call, documented on the class
        self, session: AsyncSession, record_id: uuid.UUID, level: "Level", *, now: datetime
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class SlaRecordType:
    """One record type with SLAs."""

    code: str  # "incident"
    fields: ResourceFields  # what conditions may filter on (validated and evaluated in memory)
    priorities: tuple[str, ...]  # its priority codes, highest first ("p1" ... "p4")
    lock_record: LockHook | None = None  # session 3: the record row first, then the clocks
    on_fired: FiredHook | None = None  # session 3: warnings, breaches and levels fired
    run_actions: ActionsHook | None = None  # session 3: a level's actions (REQ-SLA-024)


_TYPES: dict[str, SlaRecordType] = {}


def register_record_type(record_type: SlaRecordType) -> None:
    """Called by the owning module when it is imported (idempotent)."""
    _TYPES[record_type.code] = record_type


def record_type(code: str) -> SlaRecordType | None:
    """A registered record type, or None."""
    return _TYPES.get(code)


def record_types() -> list[str]:
    """Every registered record type code."""
    return sorted(_TYPES)
