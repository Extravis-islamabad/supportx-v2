"""The work items linked to a CI, for its Associations tab (WP-053 S5c; REQ-CMDB-019).

Work items keep their own link table (`work_item_cis`, lane A) and the CMDB never reads it. They
register this port (`register_ci_linked_records`), as they do assets' `LinkedRecords`; until then
nothing is registered, the API answers "not available" and the CI page hides the tab.

Visible-only, for every call (D-158; the coordinator's S5c condition): a record the reader may not
see is never listed, never counted and never hinted at (no placeholder, unlike an unseen CI on a
map, ADR-053). The counts come from the existing `OpenCountsPort` (per type, each through its own
view scope), so the tab's "open of total" and its list agree on what "open" means.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FieldError, NotFound, ValidationFailed
from app.modules.cmdb.service import cis
from app.modules.cmdb.service.open_counts import LINKED_TYPES, Count, linked_counts_for
from app.modules.identity_access import Subject

PAGE_DEFAULT, PAGE_MAX = 25, 100
NOT_AVAILABLE = "linked_records_not_available"


@dataclass(frozen=True, slots=True)
class CiLinkedRecord:
    """A linked work item as the CI page lists it: never more than this."""

    id: uuid.UUID
    kind: str  # incident, service_request, problem, change or release
    display_id: str
    subject: str
    status: str  # the status code; the screen labels it
    open: bool  # as OpenCountsPort counts it, so the list and the count agree
    updated_at: datetime


class CiLinkedRecords(Protocol):
    """Lane A's port (work_items): visible records only, for every call."""

    async def linked_page(  # noqa: PLR0913 - the port's agreed signature
        self,
        session: AsyncSession,
        subject: Subject,
        ci_id: uuid.UUID,
        kind: str,
        *,
        cursor: str | None = None,
        limit: int = PAGE_DEFAULT,
    ) -> tuple[Sequence[CiLinkedRecord], str | None]:
        """One page, newest first; the next page's cursor or None."""
        ...

    async def ci_ids_of(self, session: AsyncSession, work_item_id: uuid.UUID) -> list[uuid.UUID]:
        """The CIs the work item is linked to now (for live updates on its changes)."""
        ...


_PORT: list[CiLinkedRecords] = []


def register_ci_linked_records(port: CiLinkedRecords) -> None:
    """Work items' implementation (one; registering again replaces it)."""
    _PORT[:] = [port]


def clear_ci_linked_records() -> None:
    """Tests only: back to no port."""
    _PORT.clear()


def linked_records_port() -> CiLinkedRecords | None:
    """The registered port, or None before work items registers one."""
    return _PORT[0] if _PORT else None


@dataclass(frozen=True, slots=True)
class LinkedKind:
    """One work-item type's linked records the reader may see: open, and all of them."""

    kind: str
    open: int
    total: int


async def linked_kinds(
    session: AsyncSession, subject: Subject, ci_id: uuid.UUID
) -> list[LinkedKind]:
    """Open and total per type (404 for an unseen CI; "not available" without the port)."""
    await cis.get_ci(session, subject, ci_id)  # the CI's own read check, narrowing included
    if linked_records_port() is None:
        raise NotFound(code=NOT_AVAILABLE)
    counts = await linked_counts_for(session, subject, [ci_id])
    found = (counts or {}).get(ci_id, {})
    return [
        LinkedKind(kind, found.get(kind, Count()).open, found.get(kind, Count()).total)
        for kind in LINKED_TYPES
    ]


async def linked_page(  # noqa: PLR0913 - the CI, the type and paging, explicit
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    kind: str,
    *,
    cursor: str | None = None,
    limit: int = PAGE_DEFAULT,
) -> tuple[Sequence[CiLinkedRecord], str | None]:
    """One type's linked records the reader may see, newest first."""
    if kind not in LINKED_TYPES:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="path.kind",
                    code="invalid_choice",
                    message_key="errors.field.invalid_choice",
                )
            ]
        )
    await cis.get_ci(session, subject, ci_id)
    port = linked_records_port()
    if port is None:
        raise NotFound(code=NOT_AVAILABLE)
    return await port.linked_page(
        session, subject, ci_id, kind, cursor=cursor, limit=min(max(limit, 1), PAGE_MAX)
    )


async def ci_ids_of(session: AsyncSession, work_item_id: uuid.UUID) -> list[uuid.UUID]:
    """The CIs a work item is linked to (empty without the port)."""
    port = linked_records_port()
    return [] if port is None else await port.ci_ids_of(session, work_item_id)
