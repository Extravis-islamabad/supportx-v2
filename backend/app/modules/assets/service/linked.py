"""The work items linked to an asset (WP-049b s4a; REQ-AST-044, 045), through a port.

Work items keep their own link table (REQ-AST-025) and assets never read it. Lane A's
`work_items` registers the port (`register_linked_records`) once its side is on main; until then
nothing is registered, the API answers "not available" and the asset page hides the panel.

The port, as agreed with lane A (the coordinator, 2026-11-11):
- `linked_counts(session, subject, asset_id)` -> {kind: (still_worked, total)} per work-item
  type. "Still worked" is open, paused, or resolved and not yet closed; never "open".
- `linked_page(session, subject, asset_id, kind, *, cursor=None, limit=25)` ->
  (rows, next_cursor): newest first, keyset on the ID, at most 100.
- `asset_ids_of(session, work_item_id)` -> the assets a work item is linked to, for live
  updates when its status changes.
All of them see only the records the viewer may see; the counters too (D-158).

`work_items.asset_link.changed` with `at_creation: true` means the work item was raised with the
asset (REQ-AST-045): the asset's history then says "INC-n raised from this asset".
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FieldError, NotFound, ValidationFailed
from app.modules.assets.infra.models import Asset
from app.modules.assets.service.assets import RECORD_TYPE, get_asset
from app.modules.identity_access import Subject
from app.shared.events import EventEnvelope
from app.shared.history import Change, record_changes

PAGE_DEFAULT, PAGE_MAX = 25, 100
RAISED_FIELD = "raised_work_item"  # the history line of REQ-AST-045
_KIND = re.compile(r"^[a-z][a-z_]{0,39}$")


@dataclass(frozen=True, slots=True)
class LinkedRecord:
    """A linked work item as the asset page lists it: never more than this."""

    id: uuid.UUID
    kind: str  # the work-item type code: incident, service_request, problem, change, release
    display_id: str
    subject: str
    status: str  # the status code; the screen labels it
    still_worked: bool
    updated_at: datetime


class LinkedRecords(Protocol):
    """Lane A's port (work_items): visible records only, for every call."""

    async def linked_counts(
        self, session: AsyncSession, subject: Subject, asset_id: uuid.UUID
    ) -> Mapping[str, tuple[int, int]]:
        """{kind: (still worked, total)}."""
        ...

    async def linked_page(  # noqa: PLR0913 - the port's agreed signature
        self,
        session: AsyncSession,
        subject: Subject,
        asset_id: uuid.UUID,
        kind: str,
        *,
        cursor: str | None = None,
        limit: int = PAGE_DEFAULT,
    ) -> tuple[Sequence[LinkedRecord], str | None]:
        """One page, newest first; the next page's cursor or None."""
        ...

    async def asset_ids_of(self, session: AsyncSession, work_item_id: uuid.UUID) -> list[uuid.UUID]:
        """The assets the work item is linked to."""
        ...


_PORT: list[LinkedRecords] = []


def register_linked_records(port: LinkedRecords) -> None:
    """Called by work_items at import (lane A, after their ports PR lands)."""
    _PORT[:] = [port]


def unregister_linked_records() -> None:
    """Forget the port (tests)."""
    _PORT.clear()


def linked_port() -> LinkedRecords | None:
    """The registered port, or None while work items have not registered one."""
    return _PORT[0] if _PORT else None


@dataclass(frozen=True, slots=True)
class KindCount:
    """One kind's counters on the asset."""

    kind: str
    still_worked: int
    total: int


@dataclass(frozen=True, slots=True)
class LinkedSummary:
    """The panel's counters; `available` False while no port is registered."""

    available: bool
    kinds: list[KindCount]


# D-158 (Haider, 2026-11-11): the counters count only the records the viewer may see, overriding
# REQ-AST-044 AC3 (a count of hidden records is still information). One behaviour, no switch:
# the port answers for the viewer, and this module adds nothing it did not return.
async def linked_summary(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID
) -> LinkedSummary:
    """Per kind, the still-worked and total counters of the work items linked to the asset."""
    await get_asset(session, subject, asset_id)  # 404 unless the caller may see the asset
    port = linked_port()
    if port is None:
        return LinkedSummary(available=False, kinds=[])
    counts = await port.linked_counts(session, subject, asset_id)
    return LinkedSummary(
        available=True,
        kinds=[
            KindCount(kind=kind, still_worked=worked, total=total)
            for kind, (worked, total) in sorted(counts.items())
        ],
    )


async def linked_page(  # noqa: PLR0913 - the page's parts, explicit
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    kind: str,
    *,
    cursor: str | None = None,
    limit: int = PAGE_DEFAULT,
) -> tuple[Sequence[LinkedRecord], str | None]:
    """One page of one kind's linked records the caller may see (404 while not available)."""
    await get_asset(session, subject, asset_id)
    port = linked_port()
    if port is None:
        raise NotFound(code="linked_records_not_available")
    if not _KIND.match(kind):
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="path.kind",
                    code="invalid_choice",
                    message_key="errors.field.invalid_choice",
                )
            ]
        )
    return await port.linked_page(
        session, subject, asset_id, kind, cursor=cursor, limit=max(1, min(limit, PAGE_MAX))
    )


async def assets_of_work_item(session: AsyncSession, work_item_id: uuid.UUID) -> list[uuid.UUID]:
    """The assets a work item is linked to (none while no port is registered)."""
    port = linked_port()
    return [] if port is None else await port.asset_ids_of(session, work_item_id)


async def on_asset_link_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """REQ-AST-045: a work item raised with this asset adds a line to the asset's history.

    Only for `at_creation` links (lane A's new flag); a link made later is the panel's, not the
    history's. Idempotent: the consumer runs each event once (its claim), and a line is written
    only when the asset still exists.
    """
    assert session is not None  # noqa: S101 - transactional consumer
    payload = envelope.payload
    if not payload.get("at_creation") or payload.get("change") != "added":
        return
    asset = await session.scalar(
        select(Asset).where(Asset.id == uuid.UUID(str(payload["asset_id"])))
    )
    if asset is None:
        return
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=asset.id,
        version=asset.version,
        kind="child_added",
        changes=[
            Change(
                RAISED_FIELD,
                None,
                {
                    "work_item_id": str(payload["work_item_id"]),
                    # Lane A may add these to the event; the line names the record when it can.
                    "display_id": payload.get("display_id"),
                    "type": payload.get("type"),
                },
            )
        ],
        source="system",
    )
