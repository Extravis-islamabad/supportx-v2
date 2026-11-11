"""Work items as the assets module's linked-records port (WP-049b s4a; REQ-AST-044, D-158).

Registered from this module's __init__ into assets' public `register_linked_records` (lane A
agreed, rule 8). A thin adapter over lane A's own visible-only queries in asset_links.py: it adds
no query of its own, so what the asset panel counts and lists is exactly what the viewer may see
(D-158). Rows become the assets module's `LinkedRecord`; the cursor is the record ID as text.
"""

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest
from app.modules.assets import LinkedRecord
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import asset_links
from app.shared.history import Source

# "Still worked" as lane A counts it (D-153): open, paused or resolved; not closed or canceled.
_WORKED = frozenset(
    {StatusCategory.OPEN.value, StatusCategory.PAUSED.value, StatusCategory.RESOLVED.value}
)


def _record(row: WorkItem) -> LinkedRecord:
    return LinkedRecord(
        id=row.id,
        kind=str(row.type),
        display_id=row.display_id,
        subject=row.subject,
        status=row.status,
        still_worked=row.status_category in _WORKED,
        updated_at=row.updated_at,
    )


class WorkItemLinkedRecords:
    """The port, as assets' `LinkedRecords` Protocol defines it."""

    async def linked_counts(
        self, session: AsyncSession, subject: Subject, asset_id: uuid.UUID
    ) -> Mapping[str, tuple[int, int]]:
        """{kind: (still worked, total)}, visible records only (lane A's query)."""
        return await asset_links.linked_counts(session, subject, asset_id)

    async def linked_page(  # noqa: PLR0913 - the port's agreed signature
        self,
        session: AsyncSession,
        subject: Subject,
        asset_id: uuid.UUID,
        kind: str,
        *,
        cursor: str | None = None,
        limit: int = 25,
    ) -> tuple[Sequence[LinkedRecord], str | None]:
        """One page, newest first, visible records only (lane A's query)."""
        after: uuid.UUID | None = None
        if cursor is not None:
            try:
                after = uuid.UUID(cursor)
            except ValueError:
                raise BadRequest(code="invalid_cursor") from None
        rows, following = await asset_links.linked_page(
            session, subject, asset_id, kind, cursor=after, limit=limit
        )
        return [_record(r) for r in rows], None if following is None else str(following)

    async def asset_ids_of(self, session: AsyncSession, work_item_id: uuid.UUID) -> list[uuid.UUID]:
        """The assets the record links now."""
        return await asset_links.asset_ids_of(session, work_item_id)

    async def repoint_links(  # noqa: PLR0913 - the port's agreed signature
        self,
        session: AsyncSession,
        from_asset_id: uuid.UUID,
        to_asset_id: uuid.UUID,
        *,
        from_label: str,
        to_label: str,
        source: Source,
    ) -> int:
        """An asset merge (WP-049b S4b): lane A's `repoint_asset_links`, called as it is."""
        return await asset_links.repoint_asset_links(
            session, from_asset_id, to_asset_id, from_label=from_label, to_label=to_label,
            source=source,
        )  # fmt: skip


PORT = WorkItemLinkedRecords()
